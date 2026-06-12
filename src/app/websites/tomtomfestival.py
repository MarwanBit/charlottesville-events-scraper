from .base import EventsWebsite
from typing import Optional
from bs4 import Tag, BeautifulSoup, NavigableString
import os
import re
import threading
import time
import requests
from datetime import date, datetime, timezone
from datetime import time as dt_time
from urllib.parse import unquote, unquote_plus, urljoin, urlparse

from ..utils import clean_text

# Sched `/venues` index and Nominatim are cached / rate-limited across event pages.
_venues_address_by_base: dict[str, dict[str, str]] = {}
_venues_lock = threading.Lock()
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_MIN_INTERVAL = 1.1  # https://operations.osmfoundation.org/policies/nominatim/
_nominatim_lock = threading.Lock()
_last_nominatim_mono = 0.0


# Sched.com time line: "Wednesday April 22, 2026  9:30am - 11:30am <span class='tz'>EDT</span>"
# or compact: "Wednesday April 22, 2026 9:30am - 11:30amEDT"
_TZ_SUFFIX_RE = re.compile(
    r"\s+(?:EDT|EST|Eastern|CST|CDT|Central|MST|MDT|Mountain|PST|PDT|Pacific|UTC|ET|CT|MT|PT)\s*$",
    re.I,
)
_GLUED_TZ_RE = re.compile(
    r"(?i)(?<=[ap]m)(EDT|EST|Eastern|CST|CDT|Central|MST|MDT|Mountain|PST|PDT|Pacific|UTC|ET|CT|MT|PT)(?=[\s$]|$)",
)
_DATE_LINE_RE = re.compile(
    r"^(?P<dow>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(?P<mon>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\s+(?P<rest>.+)$",
    re.I,
)
# End of range may repeat weekday+date when crossing midnight, e.g.
# "Sunday April 26, 2026  2:00am" after "10:00pm - …".
_RANGE_END_DATED_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(?P<mon>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\s+(?P<timestr>.+)$",
    re.I,
)


def _parse_sched_range_end(
    segment: str, start_date: date
) -> tuple[date, Optional[dt_time]]:
    """Parse text after ' - ' in the time range: bare time (same day) or 'Weekday Mon DD, YYYY time'."""
    seg = segment.strip()
    if not seg:
        return start_date, None
    t = _parse_sched_12h(seg)
    if t is not None:
        return start_date, t
    m = _RANGE_END_DATED_RE.match(seg)
    if not m:
        return start_date, None
    mon = m.group("mon")
    d = int(m.group("day"))
    y = int(m.group("year"))
    timestr = m.group("timestr").strip()
    try:
        end_d = datetime.strptime(f"{mon} {d}, {y}", "%B %d, %Y").date()
    except ValueError:
        return start_date, None
    return end_d, _parse_sched_12h(timestr)


def parse_sched_event_time_line(
    raw: str,
) -> tuple[Optional[date], Optional[date], Optional[dt_time], Optional[dt_time]]:
    """Parse Sched `sched-event-details-timeandplace` text into date and time range."""
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if not s:
        return None, None, None, None
    s = _GLUED_TZ_RE.sub(r" \1", s)
    m = _DATE_LINE_RE.match(s)
    if not m:
        return None, None, None, None
    month_str = m.group("mon")
    day = int(m.group("day"))
    year = int(m.group("year"))
    rest = m.group("rest").strip()
    rest = _TZ_SUFFIX_RE.sub("", rest).strip()
    parts = [p.strip() for p in re.split(r"\s+-\s+", rest) if p.strip()]
    if not parts:
        return None, None, None, None
    try:
        start_date = datetime.strptime(f"{month_str} {day}, {year}", "%B %d, %Y").date()
    except ValueError:
        return None, None, None, None
    start_time = _parse_sched_12h(parts[0])
    end_date = start_date
    end_time: Optional[dt_time] = None
    if len(parts) > 1:
        end_date, end_time = _parse_sched_range_end(parts[1], start_date)
    return start_date, end_date, start_time, end_time


def _parse_sched_12h(s: str) -> Optional[dt_time]:
    s = re.sub(r"\s+", " ", s.strip())
    s = _TZ_SUFFIX_RE.sub("", s).strip()
    if not s:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})\s*([AP]M)$", s, re.I)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if ap == "PM" and h != 12:
            h += 12
        if ap == "AM" and h == 12:
            h = 0
        return dt_time(h % 24, mi)
    m = re.match(r"^(\d{1,2})\s*([AP]M)$", s, re.I)
    if m:
        h, ap = int(m.group(1)), m.group(2).upper()
        if ap == "PM" and h != 12:
            h += 12
        if ap == "AM" and h == 12:
            h = 0
        return dt_time(h % 24, 0)
    return None


def _cost_text_to_db_value(cost_text: str) -> Optional[float]:
    """Map scraped cost text to DB `cost` (float). Free -> 0.0; dollar amounts parsed."""
    t = (cost_text or "").strip().lower()
    if not t:
        return None
    if re.search(r"\bfree\b", t):
        return 0.0
    m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", cost_text or "")
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _find_sched_cost_li(soup: BeautifulSoup) -> Optional[Tag]:
    """Sched exposes cost in `ul.tip-custom-fields` as <li><strong>Cost</strong> ..."""
    for li in soup.select("ul.tip-custom-fields li"):
        strong = li.find("strong")
        if strong and strong.get_text(strip=True).lower() == "cost":
            return li
    return None


def _anchor_in_tip_custom_fields(a: Tag) -> bool:
    """Cost / area links live under `ul.tip-custom-fields` inside `sched-event-type`."""
    for ul in a.find_parents("ul"):
        classes = ul.get("class") or []
        if isinstance(classes, str):
            classes = [classes]
        if any("tip-custom" in str(c) for c in classes):
            return True
    return False


def _href_looks_like_sched_track(href: str) -> bool:
    """Sched uses `type/Track+Name` (any case); path may be URL-encoded."""
    if not (href or "").strip():
        return False
    decoded = unquote((href or "").strip())
    return bool(re.search(r"type[/\\]", decoded, flags=re.I))


def _sched_event_type_text(soup: BeautifulSoup) -> str:
    """
    Sched track / event type label in `div.sched-event-type`, e.g.
    <a href="type/Civic+Futures+Summit">...</a>.
    Match `type/` case-insensitively after URL-decoding; skip `ul.tip-custom-fields` links (Cost, etc.).
    """
    div = soup.select_one("div.sched-event-type")
    if not div:
        return ""
    for a in div.find_all("a", href=True):
        if _anchor_in_tip_custom_fields(a):
            continue
        if _href_looks_like_sched_track(a.get("href") or ""):
            return clean_text(a.get_text(" ", strip=True))
    return ""


def _sched_list_single_location_venue_name(soup: BeautifulSoup) -> str:
    """
    Sched list layout: `div.list-single__details` > `div.list-single__location` >
    `a[href*='venue']` (venue label). Skips `#map-toggle` and Google Maps links.
    """
    loc = soup.select_one("div.list-single__location")
    if not loc:
        return ""
    for a in loc.find_all("a", href=True):
        if (a.get("id") or "").strip() == "map-toggle":
            continue
        href = (a.get("href") or "").strip()
        if not href:
            continue
        hlow = href.lower()
        if "maps.google" in hlow or hlow.startswith("//maps."):
            continue
        if "venue" in hlow:
            return clean_text(a.get_text(" ", strip=True))
    return ""


def _sched_time_place_datetime_text(el: Tag) -> str:
    """Date/time line only (before `<br>` / venue link). Full get_text includes the venue name and breaks time parsing."""
    chunks: list[str] = []
    for child in el.children:
        name = getattr(child, "name", None)
        if name in ("br", "a"):
            break
        if isinstance(child, NavigableString):
            chunks.append(str(child))
        elif name:
            chunks.append(child.get_text(" ", strip=True))
    return clean_text(" ".join(chunks))


def _sched_time_place_em_address(el: Optional[Tag]) -> str:
    """Sched sometimes adds a postal line in `<em>` after the venue link (e.g. The Bebedero)."""
    if not el:
        return ""
    em = el.find("em")
    if not em:
        return ""
    t = clean_text(em.get_text(" ", strip=True))
    if not t:
        return ""
    if re.search(r"\b229\d{2}\b", t):
        return t
    if re.search(r"\d", t) and "charlottesville" in t.lower():
        return t
    return ""


def _tomtom_venues_fallback_line(
    vmap: dict[str, str],
    venue_label: str,
    event_title: str,
) -> str:
    """Map vague composite venue names to `/venues` rows that include a street tail in the URL."""
    low = (venue_label or "").strip().lower()
    tit = (event_title or "").strip().lower()

    def g(key: str) -> str:
        return (vmap.get(_norm_venue_key(key)) or "").strip()

    # Title beats venue: Sched often leaves "West Stage | Downtown Mall" for Ting / stage shows.
    if re.search(r"ting\s*pav", tit):
        return g("Ting Pavilion") or g("Ting Pavilion & City Hall")
    if "central stage" in tit or tit.startswith("central stage"):
        return g("Market Street Park")
    if "irving" in low and "code" in low:
        return g("CODE Building")
    if re.search(r"west stage", tit, re.I):
        return g("Downtown Mall")
    if "west stage" in low and ("downtown mall" in low or "downtown" in low):
        return g("Downtown Mall")
    if not (venue_label or "").strip() and "downtown mall" in tit and "block party" in tit:
        return g("Downtown Mall")
    return ""


def _norm_venue_key(label: str) -> str:
    return re.sub(r"\s+", " ", (label or "").strip()).lower()


def _venue_path_segments(href: str) -> list[str]:
    """Return decoded path segments for `/venue/slug` or `/venue/slug/street city state…`."""
    href = (href or "").strip()
    if not href:
        return []
    path = urlparse(href).path if href.startswith("http") else href.split("?", 1)[0]
    return [unquote_plus(seg) for seg in path.strip("/").split("/") if seg]


def _street_address_from_venue_href(href: str) -> Optional[str]:
    segs = _venue_path_segments(href)
    if len(segs) >= 3 and segs[0].lower() == "venue":
        line = segs[2].strip()
        return line or None
    return None


def _looks_like_street_address(s: str) -> bool:
    """True if Sched gave us (or we resolved) something geocoder-grade, not just a venue nickname."""
    t = (s or "").strip()
    if not t:
        return False
    if re.search(r"\d", t):
        return True
    if "," in t and ("va" in t.lower() or "charlottesville" in t.lower()):
        return True
    return False


_STREET_TYPE = (
    r"St\.?|Street|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|Boulevard|Blvd\.?|Court|Ct\.?|"
    r"Place|Pl\.?|Terrace|Trl\.?|Trail|Parkway|Pkwy\.?|Circle|Cir\.?|Way|Highway|Hwy\.?"
)
_TOMTOM_REJECT_SUBSTRINGS = (
    "various porches",
    "irving theater, code building",
    "west stage | downtown mall",
    "west stage|downtown mall",
)


def _nominatim_short_address(row: dict) -> Optional[str]:
    """Build one U.S. postal line from Nominatim `address` (when addressdetails=1)."""
    a = row.get("address")
    if not isinstance(a, dict) or not a:
        return None
    hn = (a.get("house_number") or "").strip()
    road = (
        a.get("road")
        or a.get("pedestrian")
        or a.get("path")
        or a.get("retail")
        or ""
    ).strip()
    line1 = " ".join(x for x in (hn, road) if x)
    city = (
        a.get("city")
        or a.get("town")
        or a.get("village")
        or a.get("hamlet")
        or a.get("municipality")
        or ""
    ).strip()
    state = (a.get("state") or "").strip()
    pc = (a.get("postcode") or "").strip()
    if not line1 and road:
        line1 = road
    if not line1:
        return None
    tail_parts: list[str] = []
    if city and state:
        tail_parts.append(f"{city}, {state}{' ' + pc if pc else ''}".rstrip())
    elif state and pc:
        tail_parts.append(f"{state} {pc}")
    elif city:
        tail_parts.append(city + (f" {pc}" if pc else ""))
    elif pc:
        tail_parts.append(pc)
    if not tail_parts:
        return line1
    return f"{line1}, {tail_parts[0]}"


def _normalize_tomtom_address_line(raw: str) -> str:
    """Strip Sched/Nominatim noise; pull out an embedded `Address:` line or leading street segment."""
    s = clean_text(raw)
    if not s:
        return ""
    if re.search(r"(?i)\baddress\s*:", s):
        s = re.split(r"(?i)\baddress\s*:", s)[-1].strip()
    s = clean_text(s)
    # "Downtown Mall 407 E. Main St." -> start at numbered street segment
    m = re.search(
        rf"(?P<street>\d{{1,5}}[A-Za-z]?\s+(?:[NSEW]\.?\s+)?[A-Za-z0-9.'\-\s]{{1,55}}?\b(?:{_STREET_TYPE})\b\.?)(?=\s*[,\s]|$)",
        s,
        re.I,
    )
    if m and m.start() > 0 and m.start() < max(30, len(s) // 2):
        s = s[m.start() :].strip()
    s = re.sub(r",?\s*United States\.?$", "", s, flags=re.I).strip()
    s = re.sub(r",?\s*USA\.?$", "", s, flags=re.I).strip()
    return clean_text(s)


def _maybe_suffix_charlottesville_va(raw: str) -> str:
    """
    Sched often omits city/state. If we have a numbered street line but no locality, add context.
    """
    s = (raw or "").strip()
    if not s or not re.search(r"\d", s):
        return s
    low = s.lower()
    if "229" in s and re.search(r"\b229\d{2}\b", s):
        return s
    if "charlottesville" in low:
        return s
    if re.search(r",\s*va\b", low):
        return s
    if re.search(r",\s*virginia\b", low):
        return s
    if not re.search(rf"^(?:\d{{1,5}}|[NSEW]?\d{{1,2}}(?:st|nd|rd|th))\b", s, re.I) and not re.search(
        rf"\b(?:{_STREET_TYPE})\b", s, re.I
    ):
        return s
    if re.search(rf"^\d{{1,5}}\b.*\b(?:{_STREET_TYPE})\b", s, re.I):
        return f"{s}, Charlottesville, VA"
    if re.search(rf"^[NSEW]?\d{{1,2}}(?:st|nd|rd|th)\b.*\b(?:{_STREET_TYPE})\b", s, re.I):
        return f"{s}, Charlottesville, VA"
    return s


def tomtom_postal_address_is_valid(addr: str) -> bool:
    """True if the string is specific enough to store as a postal-style U.S. event address."""
    t = clean_text(addr)
    if not t:
        return False
    low = t.lower().strip()
    if low in ("charlottesville, virginia, united states", "charlottesville, va, united states"):
        return False
    if re.fullmatch(r"charlottesville, virginia, united states\.?", low):
        return False
    if (
        len(low) < 80
        and low.startswith("charlottesville,")
        and "united states" in low
        and not re.search(r"\d", t)
    ):
        return False
    for sub in _TOMTOM_REJECT_SUBSTRINGS:
        if sub in low:
            return False
    if "|" in t and not re.search(r"\b229\d{2}\b", t):
        # e.g. "West Stage | Downtown Mall" — not a single postal location
        if not re.search(rf"\b(?:{_STREET_TYPE})\b", t, re.I):
            return False
    has_zip = bool(re.search(r"\b229\d{2}\b", t))
    has_street_num = bool(
        re.match(r"^\d{1,5}[A-Za-z]?\s+", t)
        or re.search(r",\s*\d{1,5}\s+[A-Za-z]", t)
        or re.match(r"^[NSEW]?\d{1,2}(?:st|nd|rd|th)\b", t, re.I)
    )
    has_locality = bool(
        "charlottesville" in low
        or re.search(r",\s*va\b", low)
        or re.search(r",\s*virginia\b", low)
    )
    if has_zip:
        return True
    return bool(has_street_num and has_locality)


def apply_tomtom_address_validation(
    addr: str,
    latitude: Optional[float],
    longitude: Optional[float],
) -> tuple[str, Optional[float], Optional[float]]:
    """Normalize; require a postal-grade line. Drop coords when we reject the address text."""
    normalized = _normalize_tomtom_address_line(addr)
    suffixed = _maybe_suffix_charlottesville_va(normalized)
    if tomtom_postal_address_is_valid(suffixed):
        return suffixed, latitude, longitude
    print(f"[TomTomFestivalEventWebsite] rejected address, clearing: {addr[:100]!r}", flush=True)
    return "", None, None


def _http_session(client) -> requests.Session:
    """Use HTTPClient's real Session when available. HybridClient/NoDriver set session=self — not requests-compatible."""
    if client is not None:
        raw = getattr(client, "session", None)
        if isinstance(raw, requests.Session):
            return raw
    s = requests.Session()
    s.headers.update(_default_headers())
    return s


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; CharlottesvilleEventsScraper/1.0; +https://github.com/local)",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _load_sched_venues_street_map(base_url: str, session: requests.Session) -> dict[str, str]:
    """Fetch `/venues` once; map normalized venue label -> street line from `href` tail when present."""
    url = urljoin(base_url.rstrip("/") + "/", "venues")
    r = session.get(url, timeout=20, headers=_default_headers())
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out: dict[str, str] = {}
    for a in soup.select('a[href*="/venue/"]'):
        href = a.get("href") or ""
        label = clean_text(a.get_text(strip=True))
        if not label:
            continue
        line = _street_address_from_venue_href(href)
        if line:
            out[_norm_venue_key(label)] = line
    return out


def _get_sched_venues_street_map(base_url: str, session: requests.Session) -> dict[str, str]:
    with _venues_lock:
        cached = _venues_address_by_base.get(base_url)
        if cached is not None:
            return cached
        try:
            mapping = _load_sched_venues_street_map(base_url, session)
        except requests.RequestException as e:
            print(f"[TomTomFestivalEventWebsite] venues index GET failed: {e}", flush=True)
            mapping = {}
        _venues_address_by_base[base_url] = mapping
        return mapping


def _nominatim_resolve(
    query: str,
    session: requests.Session,
) -> tuple[Optional[str], Optional[float], Optional[float]]:
    """Search OSM Nominatim; return (display_name, lat, lon)."""
    if not (query or "").strip():
        return None, None, None
    if os.environ.get("TOMTOM_DISABLE_NOMINATIM", "").strip().lower() in ("1", "true", "yes"):
        return None, None, None

    global _last_nominatim_mono
    params = {"q": query.strip(), "format": "json", "limit": "1", "addressdetails": "1"}
    try:
        with _nominatim_lock:
            wait = _NOMINATIM_MIN_INTERVAL - (time.monotonic() - _last_nominatim_mono)
            if wait > 0:
                time.sleep(wait)
            r = session.get(
                _NOMINATIM_URL,
                params=params,
                timeout=25,
                headers=_default_headers(),
            )
            _last_nominatim_mono = time.monotonic()
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[TomTomFestivalEventWebsite] Nominatim error for {query[:80]!r}: {e}", flush=True)
        return None, None, None
    if not data:
        return None, None, None
    row = data[0]
    line = _nominatim_short_address(row) or row.get("display_name")
    try:
        lat = float(row["lat"])
        lon = float(row["lon"])
    except (KeyError, TypeError, ValueError):
        lat, lon = None, None
    return line, lat, lon


def resolve_tomtom_venue_address(
    venue_href: str,
    venue_label: str,
    event_title: str,
    base_url: str,
    client,
    em_postal: str = "",
) -> tuple[str, Optional[float], Optional[float]]:
    """Prefer Sched URL, optional `<em>` line, `/venues` map + Tom Tom fallbacks; then Nominatim."""
    session = _http_session(client)
    line_from_link = _street_address_from_venue_href(venue_href)
    resolved = (line_from_link or "").strip()
    lat: Optional[float] = None
    lon: Optional[float] = None

    if _looks_like_street_address(resolved):
        return resolved, lat, lon

    em_line = clean_text(em_postal or "").strip()
    if _looks_like_street_address(em_line):
        return em_line, lat, lon

    vmap = _get_sched_venues_street_map(base_url, session)
    mapped = (vmap.get(_norm_venue_key(venue_label)) or "").strip()
    fallback = _tomtom_venues_fallback_line(vmap, venue_label, event_title)
    resolved = (mapped or fallback).strip()

    if _looks_like_street_address(resolved):
        return resolved, lat, lon

    vl = (venue_label or "").lower()
    tit = (event_title or "").strip()
    geo_hints: list[str] = []
    if tit and re.search(r"ting\s*pav", tit, re.I):
        geo_hints.append("Ting Pavilion, 700 East Main Street, Charlottesville, VA 22902")
    if tit and re.search(r"central stage", tit, re.I):
        geo_hints.append("Market Street Park, 101 East Market Street, Charlottesville, VA 22902")
    if "irving" in vl and "code" in vl:
        geo_hints.append("CODE Building, 240 West Main Street, Charlottesville, VA 22902")
    if tit and re.search(r"west stage", tit, re.I):
        geo_hints.append("East Main Street, Downtown Mall, Charlottesville, VA 22902")
    if "west stage" in vl and ("downtown mall" in vl or "downtown" in vl):
        geo_hints.append("East Main Street, Downtown Mall, Charlottesville, VA 22902")

    for q in (
        *geo_hints,
        f"{venue_label}, Charlottesville, Virginia, United States",
        f"{event_title}, Charlottesville, Virginia, United States" if tit else "",
    ):
        qt = (q or "").strip()
        if not qt:
            continue
        display, nlat, nlon = _nominatim_resolve(qt, session)
        if display and _looks_like_street_address(display):
            return display, nlat, nlon
        if display:
            return display, nlat, nlon

    return (venue_label or resolved).strip(), lat, lon


class TomTomFestivalWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://tomtomfestival2026.sched.com"
        self.BASE_EVENTS_URL = self.BASE_URL + "/list/simple"

    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.soup.select("span.event")
        return cards

    def extract_event_from_card(self, card: Tag) -> dict:
        a = card.find("a", href=True) if card else None
        href = (a.get("href") or "").strip() if a else ""
        if href and not href.startswith("http"):
            event_link = f"{self.BASE_URL.rstrip('/')}/{href.lstrip('/')}"
        else:
            event_link = href
        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        return []

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        res = set[str]()
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            if event_link not in res:
                res.add(event_link)
        return list(res)

    def __str__(self):
        return f"TomTomFestivalWebsite w/ URL: {self.url}"


class TomTomFestivalEventWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://tomtomfestival2026.sched.com"
        self.BASE_EVENTS_URL = self.BASE_URL + "/list/simple"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """Fetch event page. Longer read timeout than base (10s) — Sched responses can be slow."""
        if self.soup:
            return
        session = client.session if client and hasattr(client, "session") else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )
        try:
            response = session.get(self.url, timeout=30)
            status = response.status_code
            print(f"[TomTomFestivalEventWebsite] GET {self.url} -> {status}", flush=True)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[TomTomFestivalEventWebsite] HTTP ERROR GET {self.url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(
                f"[TomTomFestivalEventWebsite] GET {self.url} -> network error: {e}",
                flush=True,
            )
            self.soup = None

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        title_el = self.soup.select_one("#sched-content-inner a.name") or self.soup.select_one("a.name")
        description_el = self.soup.select_one("div.tip-description")
        time_place_el = self.soup.select_one("div.sched-event-details-timeandplace")
        cost_el = _find_sched_cost_li(self.soup)
        secondary_category = _sched_event_type_text(self.soup)
        if not secondary_category and self.soup.select_one("div.sched-event-type"):
            print(
                "[TomTomFestivalEventWebsite] sched-event-type block found but no track link "
                f"(check page HTML): {self.url}",
                flush=True,
            )

        title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""
        description = clean_text(description_el.get_text(" ", strip=True)) if description_el else ""

        cost_text = ""
        if cost_el:
            cost_text = clean_text(cost_el.get_text(" ", strip=True))
        cost = _cost_text_to_db_value(cost_text)

        time_place_text = _sched_time_place_datetime_text(time_place_el) if time_place_el else ""
        start_date, end_date, start_time, end_time = parse_sched_event_time_line(time_place_text)

        venue_href = ""
        venue_label = ""
        em_postal = _sched_time_place_em_address(time_place_el)
        if time_place_el:
            venue_a = time_place_el.select_one('a[href*="venue"]')
            if venue_a:
                venue_href = (venue_a.get("href") or "").strip()
                venue_label = clean_text(venue_a.get_text(strip=True))

        location_name = _sched_list_single_location_venue_name(self.soup) or venue_label

        address, latitude, longitude = resolve_tomtom_venue_address(
            venue_href,
            venue_label,
            title,
            self.BASE_URL,
            client,
            em_postal=em_postal,
        )
        address, latitude, longitude = apply_tomtom_address_validation(
            address, latitude, longitude
        )

        og_image = self.soup.select_one('meta[property="og:image"]')
        image_url = clean_text(og_image.get("content")) if og_image and og_image.get("content") else ""
        if image_url.startswith("//"):
            image_url = "https:" + image_url

        scraped_at = datetime.now(timezone.utc).isoformat()
        event_link = self.url.split("?", 1)[0].rstrip("/")

        events: list[dict] = [
            {
                "title": title,
                "event_link": event_link,
                "description": description,
                "image_url": image_url,
                "organizer": "Tom Tom Festival",
                "location_name": location_name,
                "address": address,
                "latitude": latitude,
                "longitude": longitude,
                "scraped_at": scraped_at,
                "website": self.BASE_URL,
                "phone": "",
                "secondary_category": secondary_category,
                "start_date": start_date,
                "end_date": end_date,
                "start_time": start_time,
                "end_time": end_time,
                "cost": cost,
            }
        ]
        return events

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"TomTomFestivalEventWebsite w/ URL: {self.url}"
