"""
Migration script: event_records -> events_processed, with city extracted from address.

Alignment with docs/Bulk event import (CSV).pdf (stored columns):
- id, name (trim + whitespace collapsed, max 255), description, address, start/end times,
  primary_category (canonical list + normalize), tags (comma-separated, 1–30 chars, max 10),
  thumbnail_image, external_link (from event_link), is_paid (inferred, not CSV default-false).
- city: extracted then lowercased per PDF, max 100 chars.
- latitude/longitude: filled by insert_latitude_and_longitude (may be NULL until then; not a hard
  failure like the bulk-import API when coords are missing).
- location_name, additional_images: columns exist; not populated from event_records in this script.
- Times: taken from get_backend_info_from_event_records.sql (ISO-style); not re-derived from IANA TZ
  using lat/lon like a full bulk-import pipeline.
- thumbnail_image / additional_images: normalized to http(s) via _normalize_http_image_url /
  _normalize_additional_images_csv (// → https:, www. → https://; HTML entities unescaped; invalid → NULL).
- Response-only CSV columns (status, error_message) are not stored.

City extraction uses the usaddress library (US address parser with NLP) instead of
custom regex. Data engineers typically use:
  - usaddress  — US addresses, pip install, returns PlaceName = city
  - libpostal  — international, requires C library + data
  - Geocoding APIs (Google, Mapbox) — full address + lat/lon, paid/rate-limited
"""
import html
import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus

import pprint
import requests

# Project root on path so "src" package resolves when running script directly.
_root = Path(__file__).resolve().parents[1]
_scripts_dir = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.app.models import connection_scope
from src.app.constants import build_tags_csv, normalize_primary_category
from sqlalchemy import text

def _events_processed_id(row) -> str:
    """Bind value for events_processed.id — str works for TEXT (legacy) and BIGINT columns."""
    return str(row.id)


def _normalize_http_image_url(value):
    """Bulk CSV PDF: image URLs must start with http:// or https://. Fix // and www.; drop invalid."""
    if value is None:
        return None
    s = html.unescape(str(value)).strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("https://"):
        return s
    if low.startswith("http://"):
        return s
    if s.startswith("//"):
        return "https:" + s
    if low.startswith("www."):
        return "https://" + s
    return None


def _normalize_additional_images_csv(value):
    """Comma-separated image URLs; each normalized with _normalize_http_image_url; empty -> None."""
    if value is None:
        return None
    raw = html.unescape(str(value))
    parts = [p.strip() for p in re.split(r"\s*,\s*", raw) if p.strip()]
    if not parts:
        return None
    out = []
    for p in parts:
        n = _normalize_http_image_url(p)
        if n:
            out.append(n)
    return ", ".join(out) if out else None


def cleanup_events_processed_image_urls():
    """
    Re-apply URL normalization to every row: fix // and www., unescape HTML, drop invalid URLs.
    thumbnail_image / additional_images become NULL when no valid http(s) URL remains.
    """
    select_sql = text(
        "SELECT id, thumbnail_image, additional_images FROM events_processed"
    )
    update_sql = text(
        """
        UPDATE events_processed
        SET thumbnail_image = :thumbnail_image,
            additional_images = :additional_images
        WHERE id = :id
        """
    )
    with connection_scope() as session:
        rows = session.execute(select_sql).all()
    nrows = len(rows)
    updated = 0
    with connection_scope() as session:
        for i, row in enumerate(rows):
            new_thumb = _normalize_http_image_url(row.thumbnail_image)
            new_add = _normalize_additional_images_csv(row.additional_images)
            old_thumb, old_add = row.thumbnail_image, row.additional_images
            if (old_thumb != new_thumb) or (old_add != new_add):
                session.execute(
                    update_sql,
                    {
                        "id": _events_processed_id(row),
                        "thumbnail_image": new_thumb,
                        "additional_images": new_add,
                    },
                )
                updated += 1
            if (i + 1) % 2000 == 0 or (i + 1) == nrows:
                print(
                    f"  cleanup image URLs: {i + 1}/{nrows} scanned, {updated} row(s) updated so far",
                    flush=True,
                )
        session.commit()
        session.close()
    print(
        f"cleanup_events_processed_image_urls done: {nrows} row(s) scanned, {updated} row(s) updated."
    )


# docs/Bulk event import (CSV).pdf — name max 255 (trim + collapse spaces), city max 100 (lowercased when stored)
def _truncate_events_processed_str(value, max_len: int):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= max_len else s[:max_len]

try:
    import usaddress
    _HAS_USADDRESS = True
except ImportError:
    _HAS_USADDRESS = False

# Geocoding: US Census Bureau (free, no API key), then OSM Nominatim if no street-level match.
# Census often returns no match for road names without a house number; Nominatim usually does.
GEOCODE_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
GEOCODE_RATE_LIMIT_SECONDS = 0.5  # min seconds between API calls (~2 req/sec)
_last_geocode_time = 0.0
_geocode_cache = {}  # normalized address -> (lat, lon) or (None, None)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_MIN_INTERVAL = 1.1  # https://operations.osmfoundation.org/policies/nominatim/
_last_nominatim_mono = 0.0
_nominatim_lock = threading.Lock()


def _normalize_address_for_geocode(address: str) -> str:
    """Whitespace + common abbreviations so Census/Nominatim match more reliably."""
    s = (address or "").strip()
    if not s:
        return s
    s = re.sub(r"\bLn\.?\b", "Lane", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s


def _rate_limit_geocode():
    """Sleep so we don't exceed GEOCODE_RATE_LIMIT_SECONDS between requests."""
    global _last_geocode_time
    elapsed = time.monotonic() - _last_geocode_time
    if elapsed < GEOCODE_RATE_LIMIT_SECONDS:
        time.sleep(GEOCODE_RATE_LIMIT_SECONDS - elapsed)
    _last_geocode_time = time.monotonic()


def _geocode_nominatim(address: str) -> tuple:
    """OSM Nominatim search; returns (lat, lon) or (None, None)."""
    if not address or not address.strip():
        return None, None
    if os.environ.get("MIGRATE_DISABLE_NOMINATIM", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return None, None
    global _last_nominatim_mono
    params = {
        "q": address.strip(),
        "format": "json",
        "limit": "1",
        "addressdetails": "1",
        "countrycodes": "us",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CharlottesvilleEventsMigrate/1.0; +https://github.com/)",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        with _nominatim_lock:
            wait = NOMINATIM_MIN_INTERVAL - (time.monotonic() - _last_nominatim_mono)
            if wait > 0:
                time.sleep(wait)
            resp = requests.get(
                NOMINATIM_URL, params=params, timeout=25, headers=headers
            )
            _last_nominatim_mono = time.monotonic()
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None, None
    if not data:
        return None, None
    row = data[0]
    try:
        lat = float(row["lat"])
        lon = float(row["lon"])
    except (KeyError, TypeError, ValueError):
        return None, None
    return lat, lon


def geocode_address(address, use_cache=True):
    """
    Return (latitude, longitude) using Census Geocoder first, then Nominatim if unmatched.
    Returns (None, None) only if both fail. Rate-limited. Cache is keyed by normalized address.
    Set MIGRATE_DISABLE_NOMINATIM=1 to skip the Nominatim fallback.
    """
    if not address or not address.strip():
        return None, None
    norm = _normalize_address_for_geocode(address)
    if not norm:
        return None, None
    if use_cache and norm in _geocode_cache:
        return _geocode_cache[norm]
    _rate_limit_geocode()
    try:
        params = {
            "address": norm,
            "benchmark": "Public_AR_Current",
            "format": "json",
        }
        resp = requests.get(GEOCODE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        matches = data.get("result", {}).get("addressMatches") or []
        if matches:
            coords = matches[0].get("coordinates", {})
            lon = coords.get("x")
            lat = coords.get("y")
            if lat is not None and lon is not None:
                result = (float(lat), float(lon))
                _geocode_cache[norm] = result
                return result
    except Exception:
        pass
    lat, lon = _geocode_nominatim(norm)
    if lat is not None and lon is not None:
        _geocode_cache[norm] = (lat, lon)
        return lat, lon
    _geocode_cache[norm] = (None, None)
    return None, None


# Common street suffixes and directional prefixes (used only when usaddress unavailable)
_STREET_SUFFIXES = frozenset(
    {
        "st", "st.", "street", "ave", "ave.", "avenue", "blvd", "blvd.",
        "road", "rd", "rd.", "drive", "dr", "dr.", "lane", "ln", "ln.",
        "way", "circle", "cir", "court", "ct", "ct.", "place", "pl", "pl.",
        "terrace", "ter", "trail", "trl", "highway", "hwy", "pkwy", "parkway",
        "square", "sq", "main", "n", "s", "e", "w", "n.", "s.", "e.", "w.",
        "nw", "sw", "ne", "se", "nw.", "sw.", "ne.", "se.",  # directional (e.g. NW Washington -> Washington)
    }
)


# US state abbreviations (2-letter) for fallback parsing of addresses without commas
_US_STATE_ABBREVS = re.compile(
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b(?:\s+\d{5}(-\d{4})?)?\s*$",
    re.I,
)


def _extract_city_usaddress(address):
    """Extract city using usaddress library (PlaceName component). Returns None on parse error."""
    if not _HAS_USADDRESS:
        return None
    try:
        tagged, _ = usaddress.tag(address)
        # PlaceName is the city/locality in usaddress
        city = tagged.get("PlaceName")
        if city:
            return city.strip().rstrip(",")
    except Exception:
        pass
    return None


def extract_city_from_address(address):
    """Extract city from an address string. Uses usaddress when available, else custom parsing."""
    if not address or not isinstance(address, str):
        return None
    city = _extract_city_usaddress(address)
    if city:
        return city
    # Fallback: custom parsing when usaddress not installed or failed
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 2:
        # Find the last segment that looks like state/zip (has digits or is short state abbr)
        state_zip_idx = None
        for i in range(len(parts) - 1, -1, -1):
            if re.search(r"\d", parts[i]) or (
                len(parts[i]) <= 3 and parts[i].upper() == parts[i]
            ):
                state_zip_idx = i
                break
        if state_zip_idx is not None and state_zip_idx > 0:
            city_candidate = parts[state_zip_idx - 1].strip()
            if city_candidate:
                words = city_candidate.split()
                if len(words) <= 2:
                    if len(words) == 1 and len(words[0]) > 2:
                        for suf in sorted(_STREET_SUFFIXES, key=len, reverse=True):
                            if words[0].lower().startswith(suf) and len(words[0]) > len(suf):
                                rest = words[0][len(suf):].strip()
                                if rest and rest[0].isupper():
                                    return rest
                    return city_candidate
                last_two = words[-2:]
                if last_two[0].lower().rstrip(".") in _STREET_SUFFIXES:
                    last_word = words[-1]
                    if len(last_word) > 2:
                        for suf in sorted(_STREET_SUFFIXES, key=len, reverse=True):
                            if last_word.lower().startswith(suf) and len(last_word) > len(suf):
                                rest = last_word[len(suf):].lstrip()
                                if rest and rest[0].isupper():
                                    return rest
                    return last_word
                return " ".join(last_two)
    # Fallback: single part or no comma — look for "City State ZIP" or "City State" at end
    if len(parts) == 1:
        rest = parts[0]
    else:
        rest = " ".join(parts)
    m = _US_STATE_ABBREVS.search(rest)
    if not m:
        return None
    before_state = rest[: m.start()].strip()
    if not before_state:
        return None
    # City is typically the last 1–2 words before state (e.g. "100 Main St Macon GA" -> "Macon")
    words = before_state.split()
    if not words:
        return None
    if len(words) <= 2:
        return before_state
    last_two = words[-2:]
    if last_two[0].lower().rstrip(".") in _STREET_SUFFIXES:
        return words[-1]
    return " ".join(last_two)


# Street-type tokens that sometimes appear concatenated before the city name (e.g. "Preston Ave.Charlottesville")
# Matches: optional leading text + suffix + optional period/space + (city starting with capital)
_CONCAT_STREET_PATTERN = re.compile(
    r"(?i).*?(st|ave|rd|blvd|street|avenue|road|drive|parkway|pkwy|cir|court|lane|suite|ste|boulevard)\.?\s*([A-Z][a-zA-Z]+.*)$"
)

# Known typos in extracted cities -> correct city name
_CITY_TYPO_MAP = {
    "dultuh": "Duluth",
    "kewsick": "Keswick",
    "atonton": "Eatonton",
    "inder": "Jasper",
    "dekalb": "DeKalb",
    "lagrange": "LaGrange",
    "mcallen": "McAllen",
    "atesboro": "Statesboro",
    "ockton": "Eatonton",
    "marys": "St. Marys",
}

# Leading tokens to strip (order matters: longer first); use lower() for case-insensitive match
_STRIP_PREFIXES = (
    "of virginia",
    "virginia ",
    "boulevard ",
    "farm ",
    "area ",
    "level ",
    "one ",
    "dc ",
    "station ",
    "airport ",
    "in lane",
    "mall. ",
    "turnpike ",
    "ation ",  # "Ation Arlington" -> Arlington
    "park ",
    "lane ",
    "c ",
    "k ",
    "south",
    "east ",
    "west ",
    "on ave. ",
    "on avenue ",
    "on city ",
    "reet",  # "Reetcharlottesville" -> Charlottesville
)

# Obvious fragments to reject (return None); keep set minimal to avoid nulling valid cities
_REJECT_FRAGMENTS = frozenset({"ock", "ele", "roville", "on city", "ockbridge"})

# State/zip pattern - reject or strip
_STATE_ZIP_PATTERN = re.compile(r"^[A-Z]{2}\s*\d{5}(-\d{4})?$")
_LEADING_NUMBER_PATTERN = re.compile(r"^\d+\s*")
_STE_SUITE_PATTERN = re.compile(r"^(?:Ste|Suite)\s*\d+\s*", re.I)


def normalize_city(city):
    """Normalize and clean an extracted city name. Returns None if not a valid city."""
    if not city or not isinstance(city, str):
        return None
    s = city.strip()
    if not s:
        return None
    # Reject state+zip only (e.g. "AZ 85251") or state abbr only ("AZ")
    if _STATE_ZIP_PATTERN.match(s) or (len(s) <= 3 and s.upper() == s):
        return None
    # Title-case
    s = s.title()
    # Typo correction
    key = s.lower()
    if key in _CITY_TYPO_MAP:
        s = _CITY_TYPO_MAP[key]
    # Strip concatenated street suffix + city (e.g. "Preston Ave.Charlottesville" -> "Charlottesville")
    m = _CONCAT_STREET_PATTERN.search(s)
    if m:
        s = m.group(2).strip().title()
    # Strip leading directionals (again, for "SE Charlottesville" or "Nw Charlottesville")
    words = s.split()
    if words and words[0].lower().rstrip(".") in _STREET_SUFFIXES:
        s = " ".join(words[1:])
    for directional in ("South", "North", "East", "West"):
        if s.startswith(directional) and len(s) > len(directional) and s[len(directional)].isupper():
            s = s[len(directional) :].strip()
            break
    # Strip known noise prefixes (case-insensitive); don't strip "C " when it would break "Charlottesville"
    for prefix in _STRIP_PREFIXES:
        if s.lower().startswith(prefix):
            remainder = s[len(prefix) :].strip()
            if remainder.lower() in ("harlottesville", "charlottesville"):
                s = "Charlottesville"
            else:
                s = remainder
            break
    # Strip leading numbers (e.g. "502 Washington", "1000 Washington")
    s = _LEADING_NUMBER_PATTERN.sub("", s).strip()
    # Strip "Ste 190" / "Suite 101" at start
    s = _STE_SUITE_PATTERN.sub("", s).strip()
    # Strip state+zip at start (e.g. "VA 22901Charlottesville" -> "Charlottesville")
    s = re.sub(r"^[A-Z]{2}\s*\d{5}\s*", "", s, flags=re.I).strip()
    # Normalize concatenated *charlottesville (e.g. "Of Virginiacharlottesville", "Ccharlottesville")
    if re.search(r"[^ ]charlottesville$", s, re.I):
        s = "Charlottesville"
    if s.lower() == "charlottesville":
        s = "Charlottesville"
    # Reject known fragments
    if s.lower() in _REJECT_FRAGMENTS:
        return None
    # Reject if nothing left or looks like zip
    if not s or len(s) <= 2:
        return None
    if s.upper() in ("AZ", "VA", "GA", "TX", "IL", "DC", "VIRGINIA"):
        return None
    # Final title case for any remaining lowercase (e.g. after stripping "reet" -> "charlottesville")
    s = s.title()
    return s if s else None


def create_events_processed_table():
    sql_path = _scripts_dir / "create_events_processed_table.sql"
    with connection_scope() as session:
        with open(sql_path, 'r') as f:
            sql = f.read()
        session.execute(text(sql))
        session.commit()
        session.close()


def ensure_events_processed_schema():
    """CREATE TABLE IF NOT EXISTS does not add new columns to old tables; patch those here."""
    with connection_scope() as session:
        session.execute(
            text("ALTER TABLE events_processed ADD COLUMN IF NOT EXISTS tags TEXT")
        )
        session.execute(
            text("ALTER TABLE events_processed ADD COLUMN IF NOT EXISTS additional_images TEXT")
        )
        session.execute(
            text("ALTER TABLE events_processed ADD COLUMN IF NOT EXISTS secondary_category TEXT")
        )
        session.commit()
        session.close()
    print(
        "ensure_events_processed_schema: tags / additional_images / secondary_category "
        "columns present (added if missing)."
    )


def ensure_events_processed_unique_name_start_end():
    """Deduplicate (name, start_time, end_time), then add UNIQUE NULLS NOT DISTINCT (PostgreSQL 15+)."""
    dedupe_sql = """
    WITH ranked AS (
      SELECT ctid,
             ROW_NUMBER() OVER (
               PARTITION BY name, start_time, end_time
               ORDER BY (id::text)::bigint DESC
             ) AS rn
      FROM events_processed
    )
    DELETE FROM events_processed WHERE ctid IN (SELECT ctid FROM ranked WHERE rn > 1);
    """
    constraint_sql = """
    DO $c$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_events_processed_name_start_end'
      ) THEN
        ALTER TABLE events_processed
          ADD CONSTRAINT uq_events_processed_name_start_end
          UNIQUE NULLS NOT DISTINCT (name, start_time, end_time);
      END IF;
    END $c$;
    """
    with connection_scope() as session:
        session.execute(text(dedupe_sql))
        session.execute(text(constraint_sql))
        session.commit()
        session.close()
    print(
        "ensure_events_processed_unique_name_start_end: "
        "deduped + unique (name, start_time, end_time) present."
    )


def insert_from_event_records():
    sql_path = _scripts_dir / "get_backend_info_from_event_records.sql"
    print(f"Loading SQL from {sql_path}")
    with connection_scope() as session:
        with open(sql_path, 'r') as f:
            sql = f.read()
        print("Executing query to fetch event records...")
        cursor_result = session.execute(text(sql))
        rows = cursor_result.all()
        print(f"Fetched {len(rows)} event record(s)")
        for i, row in enumerate(rows):
            if (i + 1) % 10 == 0 or i == 0:
                name_preview = (row.name or "")[:50]
                print(f"  Inserting row {i + 1}/{len(rows)}: id={row.id}, name={name_preview!r}...")
            # INSERT INTO events_processed
            insert_sql = text('''
            INSERT INTO events_processed
            (
                id,
                name,
                description,
                address,
                location_name,
                start_time,
                end_time,
                primary_category,
                secondary_category,
                tags,
                thumbnail_image,
                additional_images,
                external_link
            )
            VALUES
            (
                :id,
                :name,
                :description,
                :address,
                :location_name,
                :start_time,
                :end_time,
                :primary_category,
                :secondary_category,
                :tags,
                :thumbnail_image,
                :additional_images,
                :external_link
            )
            ON CONFLICT (name, start_time, end_time) DO UPDATE SET
                id = EXCLUDED.id,
                description = EXCLUDED.description,
                address = EXCLUDED.address,
                location_name = EXCLUDED.location_name,
                name = EXCLUDED.name,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                primary_category = EXCLUDED.primary_category,
                secondary_category = EXCLUDED.secondary_category,
                tags = EXCLUDED.tags,
                thumbnail_image = EXCLUDED.thumbnail_image,
                additional_images = EXCLUDED.additional_images,
                external_link = EXCLUDED.external_link
            ''')
            tags = build_tags_csv(
                getattr(row, "audience", None),
                getattr(row, "location_type", None),
            )
            sec = getattr(row, "secondary_category", None)
            if isinstance(sec, str):
                sec = sec.strip() or None
            loc_name = getattr(row, "location_name", None)
            if isinstance(loc_name, str):
                loc_name = loc_name.strip() or None
            session.execute(insert_sql, {
                "id": _events_processed_id(row),
                "name": _truncate_events_processed_str(row.name, 255),
                "description": row.description,
                "address": row.address,
                "location_name": _truncate_events_processed_str(loc_name, 255),
                "start_time": row.start_time,
                "end_time": row.end_time,
                "primary_category": normalize_primary_category(row.primary_category),
                "secondary_category": sec,
                "tags": tags,
                "thumbnail_image": _normalize_http_image_url(
                    getattr(row, "thumbnail_image", None)
                ),
                "additional_images": _normalize_additional_images_csv(
                    getattr(row, "additional_images", None)
                ),
                "external_link": row.external_link,
            })
        print(f"Committing {len(rows)} row(s) to events_processed...")
        session.commit()
        session.close()
    print("insert_from_event_records done.")

def insert_city():
    sql_path = _scripts_dir / "select_events_processed.sql"
    print(f"Loading SQL from {sql_path}")
    with connection_scope() as session:
        with open(sql_path, "r") as f:
            sql = f.read()
        print("Executing query to fetch events_processed rows...")
        cursor_result = session.execute(text(sql))
        rows = cursor_result.all()
        print(f"Fetched {len(rows)} row(s), extracting city from address and updating...")
        update_sql = text(
            "UPDATE events_processed SET city = :city WHERE id = :id"
        )
        for i, row in enumerate(rows):
            city = extract_city_from_address(row.address)
            city = normalize_city(city)
            city = _truncate_events_processed_str(city, 100)
            # PDF: city stored normalized (e.g. lowercased)
            if city is not None:
                city = city.lower()
            session.execute(update_sql, {"id": _events_processed_id(row), "city": city})
            if (i + 1) % 5000 == 0 or i == 0:
                print(f"  Updated row {i + 1}/{len(rows)}: id={row.id}, city={city!r}")
        session.commit()
        session.close()
    print("insert_city done.")


# Score-based is_paid inference: search name + description, count paid vs free signals.
# More signals = higher score; paid_score > free_score -> True, else False, tie/zero -> None.
# Paid: avoid bare "cost" so "no cost" isn't counted paid; use "costs" or dollar context.
_PAID_WORDS = re.compile(
    r"\b(ticket|tickets|admission\s*fee|fee|fees|registration|register\s*now|buy|purchase|"
    r"paid\s*event|cover\s*charge|entry\s*fee|price|pricing|costs\b|cost\s*is|cost\s*of|rsvp|"
    r"reservation|reservations|purchase\s*ticket|buy\s*ticket|ticketed|donation\s*requested|"
    r"suggested\s*donation\s*\$|charged\s*\$\d|general\s*admission|advance\s*ticket)\b",
    re.I,
)
_FREE_WORDS = re.compile(
    r"\b(free|complimentary|no\s*cost|no\s*charge|no\s*fee|gratis|donation\s*only|"
    r"free\s*admission|free\s*event|free\s*entry|free\s*to\s*attend|open\s*to\s*the\s*public|"
    r"no\s*admission\s*charge|free\s*and\s*open)\b",
    re.I,
)
_DOLLAR_AMOUNT = re.compile(r"\$\s*\d+(\.\d{2})?|\d+\s*(dollars?|USD)\b", re.I)


def infer_is_paid_from_text(name, description):
    """
    Infer is_paid from event name + description using weighted signals.
    Returns True (paid), False (free), or None (unknown). Uses both name and description.
    """
    parts = []
    if name and isinstance(name, str):
        parts.append(name.strip())
    if description and isinstance(description, str):
        parts.append(description.strip())
    text = " ".join(parts)
    if not text:
        return None
    text = " " + text + " "
    paid_score = len(_PAID_WORDS.findall(text)) + (2 if _DOLLAR_AMOUNT.search(text) else 0)
    free_score = len(_FREE_WORDS.findall(text))
    # Strong single signal: "free" in title/description often means free event
    if free_score >= 1 and paid_score == 0:
        return False
    if paid_score >= 1 and free_score == 0:
        return True
    if paid_score > free_score:
        return True
    if free_score > paid_score:
        return False
    return None


def insert_is_paid():
    """Set is_paid from name + description when possible (score-based keyword matching)."""
    with connection_scope() as session:
        result = session.execute(
            text("SELECT id, name, description FROM events_processed")
        )
        rows = result.all()
    if not rows:
        print("No rows. insert_is_paid done.")
        return
    print(f"insert_is_paid: inferring is_paid from name + description for {len(rows)} row(s)...")
    update_sql = text("UPDATE events_processed SET is_paid = :is_paid WHERE id = :id")
    paid = 0
    free = 0
    unknown = 0
    with connection_scope() as session:
        for i, row in enumerate(rows):
            is_paid = infer_is_paid_from_text(row.name, row.description)
            session.execute(update_sql, {"id": _events_processed_id(row), "is_paid": is_paid})
            if is_paid is True:
                paid += 1
            elif is_paid is False:
                free += 1
            else:
                unknown += 1
            if (i + 1) % 5000 == 0 or i == 0:
                print(f"  Processed {i + 1}/{len(rows)}: id={row.id}, is_paid={is_paid}")
        session.commit()
        session.close()
    print(f"insert_is_paid done. paid={paid}, free={free}, unknown={unknown}.")


def insert_latitude_and_longitude():
    """Look up lat/lon for each row's address via Census Geocoder API (rate-limited, cached)."""
    start = time.monotonic()
    with connection_scope() as session:
        result = session.execute(
            text("""
                SELECT id, address FROM events_processed
                WHERE address IS NOT NULL AND address != ''
                  AND (latitude IS NULL OR longitude IS NULL)
                ORDER BY id
            """)
        )
        rows = result.all()
    if not rows:
        print("No rows missing latitude/longitude. insert_latitude_and_longitude done.")
        return
    unique_addresses = len({(row.address or "").strip() for row in rows})
    # ETA: only unique addresses hit the API; each takes GEOCODE_RATE_LIMIT_SECONDS
    eta_seconds = unique_addresses * GEOCODE_RATE_LIMIT_SECONDS
    eta_mins = eta_seconds / 60
    print(f"insert_latitude_and_longitude: {len(rows)} row(s) to update, {unique_addresses} unique address(es).")
    print(f"  Census: ~{1.0 / GEOCODE_RATE_LIMIT_SECONDS:.1f} req/s; Nominatim fallback: max ~{1.0 / NOMINATIM_MIN_INTERVAL:.1f} req/s when Census has no match.")
    print(f"  Cache: normalized address string; no duplicate API calls per run.")
    print(f"  Minimum time if every unique address needs Census only: ~{eta_mins:.0f} min (add ~1s per Nominatim fallback).")
    update_sql = text(
        "UPDATE events_processed SET latitude = :lat, longitude = :lon WHERE id = :id"
    )
    ok = 0
    api_calls = 0
    with connection_scope() as session:
        for i, row in enumerate(rows):
            norm = _normalize_address_for_geocode((row.address or "").strip())
            was_cached = norm in _geocode_cache
            lat, lon = geocode_address(row.address)
            if not was_cached:
                api_calls += 1
            session.execute(
                update_sql,
                {"id": _events_processed_id(row), "lat": lat, "lon": lon},
            )
            if lat is not None and lon is not None:
                ok += 1
            n = i + 1
            elapsed = time.monotonic() - start
            if n == 1 or n % 100 == 0 or n == len(rows):
                rate = n / elapsed if elapsed > 0 else 0
                remaining = (len(rows) - n) / rate if rate > 0 else 0
                print(f"  [{n}/{len(rows)}] ok={ok} | elapsed {elapsed/60:.1f} min | ETA {remaining/60:.1f} min | id={row.id} lat={lat} lon={lon}")
        session.commit()
        session.close()
    total_elapsed = time.monotonic() - start
    print(f"insert_latitude_and_longitude done in {total_elapsed/60:.1f} min. Geocoded {ok}/{len(rows)} successfully ({api_calls} API calls, cache hits saved {len(rows) - api_calls} requests).")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "cleanup-images":
        cleanup_events_processed_image_urls()
    else:
        create_events_processed_table()
        ensure_events_processed_schema()
        ensure_events_processed_unique_name_start_end()
        insert_from_event_records()
        insert_city()
        insert_is_paid()
        insert_latitude_and_longitude()