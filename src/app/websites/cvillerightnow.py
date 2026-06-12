from .base import EventsWebsite
from typing import Optional
import json
import re
import requests
from bs4 import Tag, BeautifulSoup
from datetime import date, datetime, time, timezone
from urllib.parse import parse_qs, urljoin, urlparse

from ..utils import clean_text

# CitySpark listing tiles: csEvWrap + csEventTile + csEvFindMe (omit varying csRand* / optional csMin).
_EVENT_TILE_SELECTOR = "div.csEvWrap.csEventTile.csEvFindMe"
# Virtualized grids unmount off-screen tiles; browser sweep accumulates hrefs into #__scraper_vlist_accum__.
# Listing fetch uses virtualized_list_return_full_html so the response includes real tile nodes for
# parse_listing_cards (accum JSON is still present and merged in extract_links).
# Do not require csEventTile on the same node as the link (nested layouts vary); http_client filters hrefs.
_VIRTUALIZED_DETAIL_LINK_SELECTOR = (
    "a[href*='#/details/'], "
    "a[href*='/details/'], "
    "div.csEvWrap a[href*='details'], "
    "div[class*='csEvent'] a[href*='details']"
)
# Browser injects JSON array of href strings (see http_client virtual list sweep).
# The response HTML is usually *minimal*: only this script tag — not real <a> nodes inside it.
_ACCUM_JSON_SCRIPT_SELECTOR = 'script#__scraper_vlist_accum__'
# Legacy/fallback; minimal HTML has no <a> under #__scraper_vlist_accum__ (JSON only).
_ACCUM_LINK_SELECTOR = "#__scraper_vlist_accum__ a.event-link[href]"

# SPA: comma-separated wait_for_selector uses querySelector which returns the *first* match document-wide;
# main/h1 ("Events") wins before CitySpark mounts — require the event card + populated date block instead.
_DETAIL_WAIT_ALL_SELECTORS = [
    "div.csEvHolder",
    "div.csEvHolder div.csName.csSegment",
    "div.csEvHolder div.csDates.csSegment",
]
_DETAIL_DATES_TEXT_SELECTOR = "div.csEvHolder div.csDates.csSegment"
_SHELL_PAGE_TITLES_LOWER = frozenset({"events", "event"})

_WEEKDAY_DATE_RE = re.compile(
    r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})",
    re.I,
)
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2}:\d{2}\s*[ap]m)\s*-\s*(\d{1,2}:\d{2}\s*[ap]m)",
    re.I,
)
# Many CitySpark rows are start-only (e.g. "Thu, Apr 10, 2026 , 8:00pm") with no end time.
_AP_TIME_TOKEN_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*[ap]m)\b", re.I)
_SPARK_TAIL_DT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?$",
    re.I,
)
_BG_IMAGE_URL_RE = re.compile(
    r"background-image:\s*url\(\s*[\"']?([^)\"']+)[\"']?\s*\)",
    re.I,
)
_DETAIL_FRAGMENT_RE = re.compile(
    r"#/?details/([^/]+)/(\d+)/(\d{4}-\d{2}-\d{2}T[^/?#\s]+)",
    re.I,
)


def _spark_cost_text_to_db_value(cost_text: str) -> Optional[float]:
    """Map CitySpark price line to DB `cost` (float). Free -> 0.0; first dollar amount if present."""
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


def _parse_ap_time(raw: str) -> Optional[time]:
    s = (raw or "").strip().lower().replace(" ", "")
    if not s:
        return None
    for fmt in ("%I:%M%p", "%I%M%p"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def _date_time_from_spark_url_tail(tail: str) -> tuple[Optional[date], Optional[time]]:
    """Fragment tail like 2026-04-10T20 or 2026-04-10T20:30 → local wall time (T20 = 8pm)."""
    m = _SPARK_TAIL_DT_RE.match((tail or "").strip())
    if not m:
        return None, None
    try:
        d = date.fromisoformat(m.group(1))
    except ValueError:
        return None, None
    h = int(m.group(2))
    mi = int(m.group(3) or 0)
    se = int(m.group(4) or 0)
    if h > 23 or mi > 59 or se > 59:
        return d, None
    return d, time(h, mi, se)


def _parse_schedule_row(row: Tag) -> Optional[tuple[date, Optional[time], Optional[time]]]:
    text = clean_text(row.get_text(" ", strip=True))
    dm = _WEEKDAY_DATE_RE.search(text)
    if not dm:
        return None
    date_str = f"{dm.group(1)}, {dm.group(2)} {dm.group(3)}, {dm.group(4)}"
    try:
        d = datetime.strptime(date_str, "%a, %b %d, %Y").date()
    except ValueError:
        return None
    tm = _TIME_RANGE_RE.search(text)
    if tm:
        st = _parse_ap_time(tm.group(1))
        et = _parse_ap_time(tm.group(2))
        return (d, st, et)
    tokens = _AP_TIME_TOKEN_RE.findall(text)
    if tokens:
        st = _parse_ap_time(tokens[0])
        et = _parse_ap_time(tokens[1]) if len(tokens) > 1 else None
        return (d, st, et)
    return (d, None, None)


def _tail_from_date_time(d: date, t: Optional[time], sample_tail: str) -> str:
    """Match CitySpark URL fragments like 2026-04-05T08 or 2026-04-05T08:30."""
    if t is None:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})T(.+)$", sample_tail or "")
        if m:
            return f"{d.isoformat()}T{m.group(2)}"
        return f"{d.isoformat()}T08"
    if t.minute == 0 and t.second == 0 and re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{1,2}$", sample_tail or ""
    ):
        return f"{d.isoformat()}T{t.hour:02d}"
    if t.second == 0:
        return f"{d.isoformat()}T{t.hour:02d}:{t.minute:02d}"
    return f"{d.isoformat()}T{t.hour:02d}:{t.minute:02d}:{t.second:02d}"


def _parse_detail_url(url: str) -> Optional[tuple[str, str, str, str]]:
    """Return (origin_events_prefix, slug, spark_id, datetime_tail) or None."""
    p = urlparse(url)
    frag = (p.fragment or "").strip().strip("/")
    parts = [x for x in frag.split("/") if x]
    slug = eid = tail = ""
    if len(parts) >= 4 and parts[0].lower() == "details":
        slug, eid, tail = parts[1], parts[2], parts[3]
    else:
        m = _DETAIL_FRAGMENT_RE.search(url)
        if not m:
            return None
        slug, eid, tail = m.group(1), m.group(2), m.group(3)
    origin = f"{p.scheme}://{p.netloc}"
    path = (p.path or "").rstrip("/")
    if not path.endswith("/events"):
        path = "/events"
    prefix = f"{origin}{path}/"
    return (prefix, slug, eid, tail)


def _build_detail_url(prefix: str, slug: str, eid: str, dt_tail: str) -> str:
    return f"{prefix}#/details/{slug}/{eid}/{dt_tail}"


def _title_from_url_slug(url: str) -> str:
    """Fallback when the WP shell is captured: derive a label from .../details/learn-rugby/id/..."""
    p = _parse_detail_url(url)
    if not p:
        return ""
    slug = p[1]
    if not slug:
        return ""
    parts = [w for w in slug.replace("-", " ").split() if w]
    return " ".join(w[:1].upper() + w[1:].lower() if w else "" for w in parts)


def _google_calendar_fallback(holder: Tag) -> Optional[tuple[date, date, Optional[time], Optional[time]]]:
    a = holder.select_one('a[href*="calendar.google.com/calendar/render"]')
    if not a:
        return None
    href = (a.get("href") or "").strip()
    if "dates=" not in href:
        return None
    q = parse_qs(urlparse(href).query)
    raw_dates = (q.get("dates") or [None])[0]
    if not raw_dates or "/" not in raw_dates:
        return None
    start_s, _, end_s = raw_dates.partition("/")
    try:
        ds = datetime.strptime(start_s.strip().upper().replace("Z", ""), "%Y%m%dT%H%M%S")
        de = datetime.strptime(end_s.strip().upper().replace("Z", ""), "%Y%m%dT%H%M%S")
        return (ds.date(), de.date(), ds.time(), de.time())
    except ValueError:
        return None


class CvilleRightNowWebsite(EventsWebsite):
    """SPA listing at /events/#/…; always fetch BASE_EVENTS_URL so the calendar view is loaded."""

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.cvillerightnow.com"
        self._events_path_base = f"{self.BASE_URL}/events/"
        self.BASE_EVENTS_URL = f"{self.BASE_URL}/events/#/show?start={date.today().isoformat()}"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        if self.soup:
            return

        from ..http_client import HybridClient, NoDriverClient

        session = client.session if client else requests.Session()
        if "User-Agent" not in getattr(session, "headers", {}):
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )

        fetch_url = self.BASE_EVENTS_URL
        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                print(
                    "[CvilleRightNowWebsite] CitySpark: interleave (scroll + more events) "
                    "then virtual sweep → link accum …",
                    flush=True,
                )
                response = client.get(
                    fetch_url,
                    timeout=7200,
                    wait_for_selector=_EVENT_TILE_SELECTOR,
                    wait_for_timeout=35,
                    load_more_text_contains="more events",
                    load_more_pause_sec=0.65,
                    interleave_scroll_and_load_more_rounds=220,
                    # Exit after N consecutive *stale* rounds: no load-more click AND no growth in
                    # accum link count AND no growth in tile count (http_client resets otherwise).
                    interleave_stop_after_consecutive_misses=11,
                    scroll_load_growth_selector=_EVENT_TILE_SELECTOR,
                    scroll_load_settle_max_ms=7500,
                    scroll_load_settle_poll_ms=220,
                    scroll_load_settle_quiet_polls=4,
                    virtualized_list_link_selector=_VIRTUALIZED_DETAIL_LINK_SELECTOR,
                    # Required: CitySpark unmounts off-screen rows; stepped sweep collects all hrefs.
                    virtualized_list_collect_max_steps=2000,
                    # Minimal HTML is JSON-only; need full outerHTML so BeautifulSoup sees tile divs.
                    virtualized_list_return_full_html=True,
                )
            else:
                response = session.get(fetch_url, timeout=10)

            status = response.status_code
            print(f"[CvilleRightNowWebsite] GET {fetch_url} -> {status}", flush=True)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
            n = len(self.soup.select(_EVENT_TILE_SELECTOR))
            na = 0
            jn = self.soup.select_one(_ACCUM_JSON_SCRIPT_SELECTOR)
            if jn and (jn.get("type") or "").strip().lower() == "application/json":
                try:
                    arr = json.loads((jn.string or jn.get_text() or "").strip() or "[]")
                    na = len(arr) if isinstance(arr, list) else 0
                except json.JSONDecodeError:
                    na = 0
            if na == 0:
                na = len(self.soup.select(_ACCUM_LINK_SELECTOR))
            print(
                f"[CvilleRightNowWebsite] soup {len(response.text)} chars, {n} tiles, {na} accumulated links",
                flush=True,
            )
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[CvilleRightNowWebsite] HTTP ERROR GET {fetch_url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(
                f"[CvilleRightNowWebsite] GET {fetch_url} -> network error: {e}",
                flush=True,
            )
            self.soup = None

    def parse_listing_cards(self, client: Optional[requests.Session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        return self.soup.select(_EVENT_TILE_SELECTOR)

    def extract_event_from_card(self, card: Tag) -> dict:
        event_link_el = card.select_one("a[href^='#/details'], a[href*='/details/']")
        href = (event_link_el.get("href") or "").strip() if event_link_el else ""
        event_link = urljoin(self._events_path_base, href) if href else ""
        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        """Collect detail URLs from listing tiles (``parse_listing_cards`` / ``extract_event_from_card``),
        then union with ``#__scraper_vlist_accum__`` JSON and legacy accum anchors from ``http_client``.
        """
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        out: set[str] = set()
        for card in self.parse_listing_cards(client):
            link = self.extract_event_from_card(card).get("event_link") or ""
            if link:
                out.add(link)
        jnode = self.soup.select_one(_ACCUM_JSON_SCRIPT_SELECTOR)
        if jnode and (jnode.get("type") or "").strip().lower() == "application/json":
            raw = (jnode.string or jnode.get_text() or "").strip()
            if raw:
                try:
                    arr = json.loads(raw)
                    if isinstance(arr, list):
                        for href in arr:
                            if isinstance(href, str) and href.strip():
                                out.add(urljoin(self._events_path_base, href.strip()))
                except json.JSONDecodeError:
                    pass
        for a in self.soup.select(_ACCUM_LINK_SELECTOR):
            href = (a.get("href") or "").strip()
            if href:
                out.add(urljoin(self._events_path_base, href))
        return list(out)

    def get_events(self, client: Optional[requests.Session] = None) -> list[dict]:
        return []

    def __str__(self):
        return f"CvilleRightNowWebsite w/ URL: {self.url}"


class CvilleRightNowEventWebsite(EventsWebsite):
    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.cvillerightnow.com"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        if self.soup:
            return

        from ..http_client import HybridClient, NoDriverClient

        session = client.session if client else requests.Session()
        if "User-Agent" not in getattr(session, "headers", {}):
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )

        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                response = client.get(
                    self.url,
                    timeout=180,
                    wait_for_timeout=90,
                    wait_for_all_selectors=_DETAIL_WAIT_ALL_SELECTORS,
                    wait_for_nonempty_text_selector=_DETAIL_DATES_TEXT_SELECTOR,
                    wait_for_nonempty_text_min_len=14,
                    # CitySpark hides extra rows under "Show more dates" (often <a class="cs-pseudo-link">).
                    load_more_text_contains="show more dates",
                    max_load_more_clicks=15,
                    load_more_pause_sec=1.0,
                )
            else:
                response = session.get(self.url, timeout=10)

            status = response.status_code
            print(f"[CvilleRightNowEventWebsite] GET {self.url} -> {status}", flush=True)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[CvilleRightNowEventWebsite] HTTP ERROR GET {self.url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(
                f"[CvilleRightNowEventWebsite] GET {self.url} -> network error: {e}",
                flush=True,
            )
            self.soup = None

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    @staticmethod
    def _detail_root(soup: BeautifulSoup) -> Tag:
        h = soup.select_one("div.csEvHolder")
        return h if h else soup

    @staticmethod
    def _first_image_url(holder: Tag, base: str) -> str:
        for node in holder.select("div.csimg[style*='background-image']"):
            style = (node.get("style") or "") + " " + (node.get("title") or "")
            m = _BG_IMAGE_URL_RE.search(style)
            if m:
                raw = m.group(1).strip().strip('"').strip("'")
                if raw.startswith("//"):
                    raw = "https:" + raw
                full = urljoin(base, raw)
                if "cityspark" in full.lower() or "portalimages" in full.lower():
                    return full
                if "logo" not in full.lower():
                    return full
        img = holder.select_one("img[src]")
        if img:
            href = urljoin(base, (img.get("src") or "").strip())
            if "logo" not in href.lower():
                return href
        return ""

    @staticmethod
    def _location_address(holder: Tag) -> str:
        loc = holder.select_one(".csLocation")
        if not loc:
            return ""
        parts: list[str] = []
        for s in loc.stripped_strings:
            t = clean_text(str(s))
            if not t or t.lower() in ("location", "directions"):
                continue
            if t not in parts:
                parts.append(t)
        return ", ".join(parts)

    @staticmethod
    def _contact_fields(holder: Tag) -> tuple[str, str, str]:
        block = holder.select_one(".csContact")
        if not block:
            return "", "", ""
        organizer = email = phone = ""
        for div in block.select(":scope > div"):
            t = clean_text(div.get_text(" ", strip=True))
            if not t or re.fullmatch(r"event contact", t, re.I):
                continue
            if "@" in t:
                email = t
            elif re.search(r"\(\d{3}\)\s*\d{3}[-\s]?\d{4}|\d{3}[-.\s]\d{3}[-.\s]\d{4}", t):
                phone = t
            elif not organizer:
                organizer = t
        return organizer, email, phone

    @staticmethod
    def _description(holder: Tag) -> str:
        box = holder.select_one(".csDescription .csText") or holder.select_one(
            ".csSegment.csDescription"
        )
        if not box:
            return ""
        return clean_text(box.get_text("\n", strip=True))

    @staticmethod
    def _event_website(holder: Tag, base: str) -> str:
        a = holder.select_one("a.csPillLink[href]")
        if not a:
            return ""
        href = (a.get("href") or "").strip()
        return href if href.startswith("http") else urljoin(base, href)

    @staticmethod
    def _cost(holder: Tag) -> Optional[float]:
        el = holder.select_one(".csSegment.csPrice") or holder.select_one(".csPrice")
        if not el:
            return None
        return _spark_cost_text_to_db_value(clean_text(el.get_text(" ", strip=True)))

    @staticmethod
    def _lat_lon(holder: Tag) -> tuple[str, str]:
        ll = holder.select_one("div[name='_ll_']")
        if not ll:
            return "", ""
        raw = clean_text(ll.get_text(" ", strip=True))
        if "," not in raw:
            return "", ""
        lat, _, lon = raw.partition(",")
        return lat.strip(), lon.strip()

    @staticmethod
    def _detail_title(scope: Tag, page_url: str) -> str:
        root = scope.select_one("div.csEvHolder") or scope
        for sel in (
            "div.csTId div.csName.csSegment",
            "div.csTId div.csName",
            "div.csEvHolder div.csName.csSegment",
            "div.csName.csSegment",
        ):
            el = root.select_one(sel)
            if not el:
                continue
            t = clean_text(el.get_text(" ", strip=True))
            if t and t.strip().lower() not in _SHELL_PAGE_TITLES_LOWER:
                return t
        h1 = root.select_one("div.csEvHolder h1")
        if h1:
            t = clean_text(h1.get_text(" ", strip=True))
            if t and t.strip().lower() not in _SHELL_PAGE_TITLES_LOWER:
                return t
        return _title_from_url_slug(page_url)

    @staticmethod
    def _collect_occurrences(
        holder: Tag, page_url: str
    ) -> list[tuple[date, date, Optional[time], Optional[time], str]]:
        """Each row is (start_date, end_date, start_time, end_time, event_link)."""
        parsed = _parse_detail_url(page_url)
        sample_tail = parsed[3] if parsed else ""
        seen: set[tuple] = set()
        blocks: list[tuple[date, date, Optional[time], Optional[time]]] = []

        def _add(sd: date, ed: date, st: Optional[time], et: Optional[time]) -> None:
            key = (sd, ed, st, et)
            if key not in seen:
                seen.add(key)
                blocks.append((sd, ed, st, et))

        dates_seg = holder.select_one(".csDates.csSegment") or holder.select_one("div.csDates")
        if dates_seg:
            for row in dates_seg.find_all("div", recursive=False):
                p = _parse_schedule_row(row)
                if not p:
                    continue
                d, st, et = p
                _add(d, d, st, et)

        add = holder.select_one(".csAdditionalDates")
        if add:
            for child in add.find_all("div", recursive=False):
                cls = child.get("class") or []
                if "cs-bold" in cls:
                    continue
                tlow = child.get_text(" ", strip=True).lower()
                if "show more" in tlow and len(tlow) < 48:
                    continue
                inner = child.find("div", recursive=False)
                block_el = inner if inner else child
                p = _parse_schedule_row(block_el)
                if not p:
                    continue
                d, st, et = p
                _add(d, d, st, et)

        if not blocks:
            g = _google_calendar_fallback(holder)
            if g:
                sd, ed, st, et = g
                _add(sd, ed, st, et)

        if not blocks and parsed:
            m = re.match(r"^(\d{4}-\d{2}-\d{2})T", sample_tail)
            if m:
                d0 = date.fromisoformat(m.group(1))
                _add(d0, d0, None, None)

        if not blocks:
            return []

        out: list[tuple[date, date, Optional[time], Optional[time], str]] = []
        if not parsed:
            for sd, ed, st, et in blocks:
                out.append((sd, ed, st, et, page_url))
            return out

        prefix, slug, eid, tail_s = parsed
        for sd, ed, st, et in blocks:
            dt_tail = _tail_from_date_time(sd, st, tail_s)
            out.append((sd, ed, st, et, _build_detail_url(prefix, slug, eid, dt_tail)))
        return out

    def get_events(self, client: Optional[requests.Session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        holder = self._detail_root(self.soup)
        title = self._detail_title(holder, self.url)

        description = self._description(holder)
        image_url = self._first_image_url(holder, self.BASE_URL)
        address = self._location_address(holder)
        organizer, email, phone = self._contact_fields(holder)
        website = self._event_website(holder, self.BASE_URL) or self.BASE_URL
        lat, lon = self._lat_lon(holder)
        cost = self._cost(holder)

        occurrences = self._collect_occurrences(holder, self.url)
        if not occurrences:
            return []

        scraped_at = datetime.now(timezone.utc).isoformat()
        events: list[dict] = []
        for sd, ed, st, et, link in occurrences:
            if st is None:
                parsed_link = _parse_detail_url(link)
                if parsed_link:
                    td, tt = _date_time_from_spark_url_tail(parsed_link[3])
                    if tt is not None and td == sd:
                        st = tt
            start_t_str = st.isoformat() if st else ""
            end_t_str = et.isoformat() if et else ""
            ev: dict = {
                "event_link": link,
                "scraped_at": scraped_at,
                "title": title,
                "description": description,
                "address": address,
                "phone": phone,
                "organizer": organizer,
                "website": website,
                "image_url": image_url,
                "start_date": sd.isoformat(),
                "end_date": ed.isoformat(),
                "start_time": start_t_str,
                "end_time": end_t_str,
                "latitude": lat,
                "longitude": lon,
                "email": email,
                "contact": organizer,
                "cost": cost,
            }
            events.append(ev)
        return events

    def __str__(self):
        return f"CvilleRightNowEventWebsite w/ URL: {self.url}"
