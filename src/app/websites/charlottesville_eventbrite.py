from .base import EventsWebsite
from typing import Any, Optional
import json
import re
import requests
from bs4 import Tag, BeautifulSoup
from datetime import date, datetime, time, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from ..utils import clean_text

# Eventbrite Discover horizontal cards; module hash (e.g. ___2_FKN) changes between builds.
_EVENTBRITE_HORIZONTAL_CARD_SELECTOR = (
    'section[class*="DiscoverHorizontalEventCard-module__cardWrapper"]'
)


def _canonical_eventbrite_event_url(url: str) -> str:
    """Drop tracking query params; keep path for stable event_link."""
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


_MONTH_NAME_TO_NUM = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

# e.g. "Friday April 24, 2026 (4-6pm)" — multi-session Eventbrite pages (no subEvent in JSON-LD)
_EVENTBRITE_SESSION_HEADING_RE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s*(\d{4})\s*\(([^)]+)\)",
    re.IGNORECASE,
)


def _parse_hm_ampm(hm: str, ampm: str) -> time:
    hm = hm.strip().lower()
    if ":" in hm:
        h_s, m_s = hm.split(":", 1)
        h, mi = int(h_s), int(m_s)
    else:
        h, mi = int(hm), 0
    ap = ampm.lower()
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return time(h, mi)


def _parse_eventbrite_time_range(range_str: str) -> tuple[time, time] | None:
    """US-style ranges: ``4-6pm``, ``10am-12pm``, ``12-2pm``."""
    r = re.sub(r"\s+", "", range_str.strip().lower())
    m = re.match(r"^(\d{1,2}(?::\d{2})?)(am|pm)-(\d{1,2}(?::\d{2})?)(am|pm)$", r)
    if m:
        return _parse_hm_ampm(m.group(1), m.group(2)), _parse_hm_ampm(m.group(3), m.group(4))
    m = re.match(r"^(\d{1,2}(?::\d{2})?)-(\d{1,2}(?::\d{2})?)(am|pm)$", r)
    if m:
        mer = m.group(3)
        return _parse_hm_ampm(m.group(1), mer), _parse_hm_ampm(m.group(2), mer)
    return None


def _discover_pagination_page_count_number(soup: BeautifulSoup) -> tuple[int | None, int | None]:
    """Return ``(page_count, page_number)`` from embedded ``pagination`` JSON, if present."""
    text = str(soup)
    m = re.search(r'"pagination"\s*:\s*\{([^}]*)\}', text)
    if not m:
        return None, None
    inner = m.group(1)
    mc = re.search(r'"page_count"\s*:\s*(\d+)', inner)
    mn = re.search(r'"page_number"\s*:\s*(\d+)', inner)
    if not mc or not mn:
        return None, None
    return int(mc.group(1)), int(mn.group(1))


def _discover_listing_url_with_query(listing_url: str, page: str) -> str:
    parts = urlparse(listing_url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q.pop("continuation", None)
    q["page"] = page
    new_query = urlencode(sorted(q.items()))
    return urlunparse(
        (parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment)
    )


def _next_discover_listing_page_url(listing_url: str, soup: BeautifulSoup) -> str | None:
    """
    Discover listing pagination uses the ``page`` query param; **``page=0`` and ``page=1`` are
    duplicate first screens**. The next slice after either is ``page=2`` (see SSR ``page_number``).

    When ``pagination`` JSON is in the HTML, we compute the next URL **without** requiring the
    Next button (HybridClient / partial DOM often omits it).

    If JSON is missing, we require the Next button and treat ``page`` 0 and 1 like the first
    page when advancing.
    """
    page_count, page_number = _discover_pagination_page_count_number(soup)
    if page_count is not None and page_number is not None and page_number >= page_count:
        return None

    if page_number is not None:
        return _discover_listing_url_with_query(listing_url, str(page_number + 1))

    btn = soup.select_one('button[data-testid="page-next"]') or soup.select_one(
        'button[aria-label="Next Page"]'
    )
    if btn is None:
        return None
    if str(btn.get("aria-disabled", "")).strip().lower() == "true":
        return None

    parts = urlparse(listing_url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    try:
        cur = int(str(q.get("page", "0")).strip() or "0")
    except ValueError:
        cur = 0
    if cur in (0, 1):
        nxt = "2"
    else:
        nxt = str(cur + 1)
    return _discover_listing_url_with_query(listing_url, nxt)


class CharlottesvilleEventbriteWebsite(EventsWebsite):
    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.eventbrite.com"
        self.BASE_EVENTS_URL = self.BASE_URL + "/d/va--charlottesville/all-events/"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        if self.soup:
            return
        from ..http_client import HybridClient, NoDriverClient

        session = getattr(client, "session", client) if client else requests.Session()
        if "User-Agent" not in getattr(session, "headers", {}):
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )
        try:
            if isinstance(client, (HybridClient, NoDriverClient)):
                response = client.get(
                    self.url,
                    timeout=120,
                    # querySelector accepts a comma list (first match wins).
                    wait_for_selector=(
                        'section[class*="DiscoverHorizontalEventCard-module__cardWrapper"],'
                        'button[data-testid="page-next"]'
                    ),
                    wait_for_timeout=45,
                )
            else:
                response = session.get(self.url, timeout=20)
            print(
                f"[{type(self).__name__}] GET {self.url} -> {response.status_code}",
                flush=True,
            )
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[{type(self).__name__}] HTTP ERROR GET {self.url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(
                f"[{type(self).__name__}] GET {self.url} -> {e}",
                flush=True,
            )
            self.soup = None

    def get_events(self, client: Optional[requests.Session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        return []

    def parse_listing_cards(self, client: Optional[requests.Session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.soup.select(_EVENTBRITE_HORIZONTAL_CARD_SELECTOR)
        if not cards:
            cards = self.soup.select("div.event-card.event-card__horizontal")
        return cards

    def extract_event_from_card(self, card: Tag) -> dict:
        """Detail URL from horizontal card: primary link is ``a.event-card-link`` to ``/e/...`` tickets."""
        event_link_el = (
            card.select_one('a.event-card-link[href*="eventbrite.com/e/"]')
            or card.select_one('a.event-card-link[href*="/e/"]')
            or card.select_one('a[href*="eventbrite.com/e/"]')
        )
        href = (event_link_el.get("href") or "").strip() if event_link_el else ""
        if href.startswith("http"):
            event_link = href
        elif href.startswith("/"):
            event_link = self.BASE_URL.rstrip("/") + href
        elif href:
            event_link = self.BASE_URL.rstrip("/") + "/" + href.lstrip("/")
        else:
            event_link = ""
        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        res = set[str]()
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            if event_link not in res:
                res.add(event_link)
        next_page = _next_discover_listing_page_url(self.url, self.soup)
        if next_page and next_page.rstrip("/") != (self.url or "").rstrip("/"):
            res.add(next_page)
        return list[str](res)

    def __str__(self):
        return f"{type(self).__name__} w/ URL: {self.url}"


class CharlottesvilleEventbriteEventWebsite(EventsWebsite):
    """Single event page: ``eventbrite.com/e/{slug}-tickets-{id}`` — JSON-LD Event + DOM fallbacks."""

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.eventbrite.com"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        if self.soup:
            return
        from ..http_client import HybridClient, NoDriverClient

        session = getattr(client, "session", client) if client else requests.Session()
        if "User-Agent" not in getattr(session, "headers", {}):
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )
        try:
            if isinstance(client, (HybridClient, NoDriverClient)):
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector='script[type="application/ld+json"], h1',
                    wait_for_timeout=45,
                )
            else:
                response = session.get(self.url, timeout=20)
            print(
                f"[CharlottesvilleEventbriteEventWebsite] GET {self.url} -> {response.status_code}",
                flush=True,
            )
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[CharlottesvilleEventbriteEventWebsite] HTTP ERROR GET {self.url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(
                f"[CharlottesvilleEventbriteEventWebsite] GET {self.url} -> {e}",
                flush=True,
            )
            self.soup = None

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    # --- JSON-LD helpers ---

    @classmethod
    def _iter_json_ld_objects(cls, soup: BeautifulSoup):
        for script in soup.find_all("script", attrs={"type": lambda t: t and "ld+json" in str(t).lower()}):
            raw = (script.string or script.get_text() or "").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            yield from cls._flatten_ld(data)

    @classmethod
    def _flatten_ld(cls, data: Any):
        if isinstance(data, list):
            for item in data:
                yield from cls._flatten_ld(item)
        elif isinstance(data, dict):
            if "@graph" in data:
                yield from cls._flatten_ld(data["@graph"])
            else:
                yield data

    @classmethod
    def _is_schema_org_event(cls, types: Any) -> bool:
        """Eventbrite uses subtypes (e.g. EducationEvent), not always schema.org Event."""
        if types == "Event":
            return True
        if isinstance(types, list):
            return any(cls._is_schema_org_event(t) for t in types)
        if isinstance(types, str) and types.endswith("Event"):
            return True
        return False

    @classmethod
    def _find_schema_event(cls, soup: BeautifulSoup) -> dict | None:
        for obj in cls._iter_json_ld_objects(soup):
            if cls._is_schema_org_event(obj.get("@type")):
                return obj
        return None

    @staticmethod
    def _parse_iso_to_dt(value: str | None) -> datetime | None:
        if not value or not isinstance(value, str):
            return None
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    @classmethod
    def _postal_address_lines(cls, addr: dict) -> str:
        if not addr or not isinstance(addr, dict):
            return ""
        if addr.get("@type") == "PostalAddress" or "streetAddress" in addr:
            street = (addr.get("streetAddress") or "").strip()
            # Eventbrite often puts a full line in streetAddress; avoid duplicating city/state/zip.
            if street and re.search(r"\d{5}", street):
                return clean_text(street)
            parts = [
                addr.get("streetAddress"),
                addr.get("addressLocality"),
                addr.get("addressRegion"),
                addr.get("postalCode"),
            ]
            line = ", ".join(p.strip() for p in parts if p and str(p).strip())
            return clean_text(line)
        return ""

    @classmethod
    def _place_to_address(cls, loc: Any) -> str:
        if not loc:
            return ""
        if isinstance(loc, str):
            return clean_text(loc)
        if not isinstance(loc, dict):
            return ""
        if loc.get("@type") == "VirtualLocation":
            return clean_text(loc.get("name") or loc.get("url") or "")
        name = clean_text(loc.get("name") or "")
        addr = loc.get("address")
        if isinstance(addr, str):
            return clean_text(f"{name}, {addr}".strip(", ").strip()) if name else clean_text(addr)
        if isinstance(addr, dict):
            lines = cls._postal_address_lines(addr)
            if name and lines:
                n, ln = name.lower(), lines.lower()
                if ln in n or n in ln:
                    return lines or name
                venue = name.split(",")[0].strip()
                if venue and re.match(r"^\d", lines):
                    return f"{venue}, {lines}"
                return f"{name}, {lines}"
            return name or lines
        return name

    @classmethod
    def _offer_price(cls, offers: Any) -> float | None:
        if offers is None:
            return None
        if isinstance(offers, list):
            best: float | None = None
            for o in offers:
                if not isinstance(o, dict):
                    continue
                p = o.get("price") or o.get("lowPrice") or o.get("highPrice")
                if p is None:
                    continue
                try:
                    v = float(str(p).replace(",", "").strip())
                    best = v if best is None else min(best, v)
                except ValueError:
                    continue
            return best
        if not isinstance(offers, dict):
            return None
        price = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
        if price is None:
            return None
        try:
            return float(str(price).replace(",", "").strip())
        except ValueError:
            return None

    @classmethod
    def _geo_lat_lon(cls, loc: Any) -> tuple[float | None, float | None]:
        if not isinstance(loc, dict):
            return None, None
        geo = loc.get("geo") or loc
        if not isinstance(geo, dict):
            return None, None
        try:
            lat = geo.get("latitude")
            lon = geo.get("longitude")
            if lat is None or lon is None:
                return None, None
            return float(lat), float(lon)
        except (TypeError, ValueError):
            return None, None

    @classmethod
    def _organizer_info(cls, org: Any) -> tuple[str, str, str]:
        """name, url, email (often empty on Eventbrite public pages)."""
        if not org:
            return "", "", ""
        if isinstance(org, str):
            return clean_text(org), "", ""
        if not isinstance(org, dict):
            return "", "", ""
        name = clean_text(org.get("name") or "")
        web = (org.get("url") or org.get("sameAs") or "")
        if isinstance(web, list):
            web = web[0] if web else ""
        web = str(web).strip() if web else ""
        email = clean_text(org.get("email") or "")
        return name, web, email

    @classmethod
    def _image_url_from_event(cls, ev: dict, base: str) -> str:
        img = ev.get("image")
        if isinstance(img, str):
            return cls._abs_url(img, base)
        if isinstance(img, list) and img:
            first = img[0]
            if isinstance(first, str):
                return cls._abs_url(first, base)
            if isinstance(first, dict):
                u = first.get("url") or first.get("contentUrl")
                if u:
                    return cls._abs_url(str(u), base)
        if isinstance(img, dict):
            u = img.get("url") or img.get("contentUrl")
            if u:
                return cls._abs_url(str(u), base)
        return ""

    @staticmethod
    def _abs_url(u: str, base: str) -> str:
        u = (u or "").strip()
        if not u:
            return ""
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        return urljoin(base, u)

    @classmethod
    def _payload_from_json_ld(cls, soup: BeautifulSoup, base: str) -> dict | None:
        ev = cls._find_schema_event(soup)
        if not ev:
            return None
        title = clean_text(ev.get("name") or "")
        desc = ev.get("description") or ""
        if isinstance(desc, str):
            description = clean_text(re.sub(r"<[^>]+>", " ", desc))
        else:
            description = clean_text(str(desc))
        loc = ev.get("location")
        address = cls._place_to_address(loc)
        lat, lon = cls._geo_lat_lon(loc if isinstance(loc, dict) else None)
        org = ev.get("organizer")
        organizer, org_url, email = cls._organizer_info(org)
        phone = ""
        if isinstance(org, dict):
            phone = clean_text(org.get("telephone") or "")
        image_url = cls._image_url_from_event(ev, base)
        cost = cls._offer_price(ev.get("offers"))
        start = cls._parse_iso_to_dt(ev.get("startDate"))
        end = cls._parse_iso_to_dt(ev.get("endDate"))
        return {
            "title": title,
            "description": description,
            "address": address,
            "latitude": lat,
            "longitude": lon,
            "organizer": organizer,
            "website": org_url or base,
            "email": email,
            "phone": phone,
            "image_url": image_url,
            "cost": cost,
            "start": start,
            "end": end,
        }

    # --- DOM fallbacks (when JSON-LD is incomplete) ---

    @staticmethod
    def _meta_content(soup: BeautifulSoup, prop: str) -> str:
        m = soup.find("meta", attrs={"property": prop})
        return (m.get("content") or "").strip() if m else ""

    @staticmethod
    def _detail_root(soup: BeautifulSoup) -> Tag:
        return soup.select_one("main") or soup.body or soup

    @classmethod
    def _detail_title(cls, soup: BeautifulSoup, holder: Tag, url: str) -> str:
        og = cls._meta_content(soup, "og:title")
        if og:
            return clean_text(og)
        h1 = holder.select_one("h1")
        if h1:
            return clean_text(h1.get_text(" ", strip=True))
        return ""

    @classmethod
    def _description(cls, soup: BeautifulSoup, holder: Tag) -> str:
        og = cls._meta_content(soup, "og:description")
        if og:
            return clean_text(og)
        for sel in ("[data-testid='about']", "section[aria-label='Overview']", ".event-description"):
            node = holder.select_one(sel)
            if node:
                return clean_text(node.get_text(" ", strip=True))
        return ""

    @classmethod
    def _first_image_url(cls, soup: BeautifulSoup, holder: Tag, base: str) -> str:
        og = cls._meta_content(soup, "og:image")
        if og:
            return cls._abs_url(og, base)
        img = holder.select_one('img[class*="hero"], img[alt*="primary image"], img.event-card-image')
        if img and img.get("src"):
            return cls._abs_url(img["src"], base)
        return ""

    @classmethod
    def _location_address(cls, holder: Tag) -> str:
        loc = holder.select_one(
            "[data-testid='location-info'], .location-info--address, address, [class*='LocationCard']"
        )
        if loc:
            return clean_text(loc.get_text(" ", strip=True))
        return ""

    @classmethod
    def _contact_fields(cls, holder: Tag) -> tuple[str, str, str]:
        org = holder.select_one("[class*='organizer-name'], a[href*='/organizations/']")
        name = clean_text(org.get_text(" ", strip=True)) if org else ""
        return name, "", ""

    @classmethod
    def _event_website(cls, holder: Tag, base: str) -> str:
        a = holder.select_one('a[href*="eventbrite.com/o/"], a[href*="/organizations/"]')
        if a and a.get("href"):
            return cls._abs_url(a["href"], base)
        return ""

    @classmethod
    def _lat_lon_from_meta(cls, soup: BeautifulSoup) -> tuple[float | None, float | None]:
        lat_s = cls._meta_content(soup, "event:location:latitude")
        lon_s = cls._meta_content(soup, "event:location:longitude")
        if not lat_s or not lon_s:
            return None, None
        try:
            return float(lat_s), float(lon_s)
        except ValueError:
            return None, None

    @classmethod
    def _datetimes_from_meta(cls, soup: BeautifulSoup) -> tuple[datetime | None, datetime | None]:
        st = cls._meta_content(soup, "event:start_time")
        en = cls._meta_content(soup, "event:end_time")
        return cls._parse_iso_to_dt(st), cls._parse_iso_to_dt(en)

    @classmethod
    def _lat_lon(cls, holder: Tag) -> tuple[float | None, float | None]:
        return None, None

    @classmethod
    def _cost_from_dom(cls, holder: Tag) -> float | None:
        t = holder.get_text(" ", strip=True)
        m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", t)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None

    @classmethod
    def _merge_payload(cls, soup: BeautifulSoup, base: str) -> dict:
        payload = cls._payload_from_json_ld(soup, base) or {}
        holder = cls._detail_root(soup)
        if not payload.get("title"):
            payload["title"] = cls._detail_title(soup, holder, "")
        if not payload.get("description"):
            payload["description"] = cls._description(soup, holder)
        if not payload.get("image_url"):
            payload["image_url"] = cls._first_image_url(soup, holder, base)
        if not payload.get("address"):
            payload["address"] = cls._location_address(holder)
        if not payload.get("organizer"):
            o, _, _ = cls._contact_fields(holder)
            payload["organizer"] = o
        if not payload.get("website") or payload.get("website") == base:
            ew = cls._event_website(holder, base)
            if ew:
                payload["website"] = ew
        pl_lat, pl_lon = payload.get("latitude"), payload.get("longitude")
        if pl_lat is None or pl_lon is None:
            mlat, mlon = cls._lat_lon_from_meta(soup)
            if mlat is not None and mlon is not None:
                payload["latitude"], payload["longitude"] = mlat, mlon
            elif pl_lat is None and pl_lon is None:
                payload["latitude"], payload["longitude"] = cls._lat_lon(holder)
        if not payload.get("start") and not payload.get("end"):
            st, en = cls._datetimes_from_meta(soup)
            if st:
                payload["start"] = st
            if en:
                payload["end"] = en
        if payload.get("cost") is None:
            c = cls._cost_from_dom(holder)
            if c is not None:
                payload["cost"] = c
        return payload

    @classmethod
    def _tuple_from_start_end(
        cls,
        start_dt: datetime | None,
        end_dt: datetime | None,
        link: str,
    ) -> tuple[date, date, time | None, time | None, str] | None:
        if not isinstance(start_dt, datetime):
            return None
        sd = start_dt.date()
        st = start_dt.time()
        if isinstance(end_dt, datetime):
            ed = end_dt.date()
            et = end_dt.time()
        else:
            ed = sd
            et = None
        return (sd, ed, st, et, link)

    @classmethod
    def _occurrence_link_for_block(cls, block: dict, fallback: str) -> str:
        raw = block.get("url") or block.get("@id")
        if isinstance(raw, str) and raw.startswith("http"):
            return _canonical_eventbrite_event_url(raw)
        return fallback

    @classmethod
    def _occurrences_from_schedule_headings(
        cls, soup: BeautifulSoup, canonical: str
    ) -> list[tuple[date, date, time | None, time | None, str, str]]:
        """
        Multi-session Eventbrite pages often repeat session times as ``h2``/``h3`` lines like
        ``Friday April 24, 2026 (4-6pm)`` without ``subEvent`` in JSON-LD (parent event is one
        multi-day ``EducationEvent``). Dedupe duplicate headings (mobile + desktop).
        """
        seen: set[str] = set()
        out: list[tuple[date, date, time | None, time | None, str, str]] = []
        for tag in soup.find_all(["h2", "h3", "h4"]):
            text = tag.get_text(" ", strip=True)
            m = _EVENTBRITE_SESSION_HEADING_RE.fullmatch(text)
            if not m:
                continue
            if text in seen:
                continue
            seen.add(text)
            _wd, month_s, day_s, year_s, trange = m.groups()
            month_i = _MONTH_NAME_TO_NUM.get(month_s.lower())
            if not month_i:
                continue
            try:
                d = date(int(year_s), month_i, int(day_s))
            except ValueError:
                continue
            times = _parse_eventbrite_time_range(trange)
            if not times:
                continue
            st_t, et_t = times
            out.append((d, d, st_t, et_t, canonical, text))
        return out

    @classmethod
    def _collect_occurrences(
        cls, soup: BeautifulSoup, url: str
    ) -> list[tuple[date, date, time | None, time | None, str, str | None]]:
        """
        One row per occurrence. Order: ``subEvent`` in JSON-LD; else **session headings** in the
        DOM when 2+ distinct lines match (multi-day workshop pages); else single JSON-LD /
        meta times.

        Returns 6-tuples ``(..., session_title)`` where ``session_title`` is set for heading rows.
        """
        base = "https://www.eventbrite.com"
        canonical = _canonical_eventbrite_event_url(url)
        ev = cls._find_schema_event(soup)
        rows: list[tuple[date, date, time | None, time | None, str, str | None]] = []

        if ev:
            subs = ev.get("subEvent")
            if subs:
                if not isinstance(subs, list):
                    subs = [subs]
                for sub in subs:
                    if not isinstance(sub, dict):
                        continue
                    occ_link = cls._occurrence_link_for_block(sub, canonical)
                    t = cls._tuple_from_start_end(
                        cls._parse_iso_to_dt(sub.get("startDate")),
                        cls._parse_iso_to_dt(sub.get("endDate")),
                        occ_link,
                    )
                    if t:
                        sd, ed, st, et, lk = t
                        rows.append((sd, ed, st, et, lk, None))
            if rows:
                return rows

            heading_rows = cls._occurrences_from_schedule_headings(soup, canonical)
            if len(heading_rows) >= 2:
                return [
                    (sd, ed, st, et, lk, sess)
                    for sd, ed, st, et, lk, sess in heading_rows
                ]

            t = cls._tuple_from_start_end(
                cls._parse_iso_to_dt(ev.get("startDate")),
                cls._parse_iso_to_dt(ev.get("endDate")),
                canonical,
            )
            if t:
                sd, ed, st, et, lk = t
                return [(sd, ed, st, et, lk, None)]

        heading_rows = cls._occurrences_from_schedule_headings(soup, canonical)
        if len(heading_rows) >= 2:
            return [
                (sd, ed, st, et, lk, sess)
                for sd, ed, st, et, lk, sess in heading_rows
            ]

        payload = cls._merge_payload(soup, base)
        start_dt = payload.get("start")
        end_dt = payload.get("end")
        t = cls._tuple_from_start_end(start_dt, end_dt, canonical)
        if t:
            sd, ed, st, et, lk = t
            return [(sd, ed, st, et, lk, None)]
        return []

    def get_events(self, client: Optional[requests.Session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        payload = self._merge_payload(self.soup, self.BASE_URL)
        title = payload.get("title") or ""
        description = payload.get("description") or ""
        image_url = payload.get("image_url") or ""
        address = payload.get("address") or ""
        organizer = payload.get("organizer") or ""
        email = payload.get("email") or ""
        phone = payload.get("phone") or ""
        website = (payload.get("website") or "").strip() or self.BASE_URL
        lat = payload.get("latitude")
        lon = payload.get("longitude")
        cost = payload.get("cost")

        occurrences = self._collect_occurrences(self.soup, self.url)
        if not occurrences:
            return []

        scraped_at = datetime.now(timezone.utc).isoformat()
        events: list[dict] = []
        for sd, ed, st, et, link, session_title in occurrences:
            row_title = f"{title} — {session_title}" if session_title else title
            ev = {
                "event_link": link,
                "scraped_at": scraped_at,
                "title": row_title,
                "description": description,
                "address": address,
                "phone": phone,
                "organizer": organizer,
                "website": website,
                "image_url": image_url,
                "start_date": sd.isoformat(),
                "end_date": ed.isoformat(),
                "start_time": st.isoformat() if st else "",
                "end_time": et.isoformat() if et else "",
                "latitude": lat,
                "longitude": lon,
                "email": email,
                "contact": organizer,
                "cost": cost,
            }
            events.append(ev)
        return events

    def __str__(self):
        return f"CharlottesvilleEventbriteEventWebsite w/ URL: {self.url}"


