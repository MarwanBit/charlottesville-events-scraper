from .base import EventsWebsite
from typing import Optional
import json
import re
import requests
from bs4 import Tag, BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

from ..utils import clean_text

class CharlottesvilleFamilyWebsite(EventsWebsite):
    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.charlottesvillefamily.com"
        self.BASE_EVENTS_URL = self.BASE_URL + "/top-family-events"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """
        TEC list views often hydrate in the browser; pass wait_for_selector so HybridClient
        uses Chromium (same pattern as TheParamountWebsite).
        """
        if self.soup:
            return

        from ..http_client import HybridClient, NoDriverClient

        session = client.session if client else requests.Session()
        if "User-Agent" not in getattr(session, "headers", {}):
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )

        wait_sel = (
            "li.tribe-events-calendar-list__event-row, "
            "#tribe-events-content, "
            ".tribe-events-c-nav"
        )

        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector=wait_sel,
                    wait_for_timeout=45,
                )
            else:
                response = session.get(self.url, timeout=10)

            status = response.status_code
            print(f"[CharlottesvilleFamilyWebsite] GET {self.url} -> {status}", flush=True)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
            n = len(self.soup.select("li.tribe-events-calendar-list__event-row"))
            print(
                f"[CharlottesvilleFamilyWebsite] soup {len(response.text)} chars, {n} list rows",
                flush=True,
            )
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[CharlottesvilleFamilyWebsite] HTTP ERROR GET {self.url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(
                f"[CharlottesvilleFamilyWebsite] GET {self.url} -> network error: {e}",
                flush=True,
            )
            self.soup = None

    def parse_listing_cards(self, client: Optional[requests.Session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.soup.select("li.tribe-common-g-row.tribe-events-calendar-list__event-row")
        return cards

    def extract_event_from_card(self, card: Tag) -> dict:
        """
        List row title link (The Events Calendar), e.g.
        <a href=".../event/..." class="tribe-events-calendar-list__event-title-link tribe-common-anchor-thin"
           rel="bookmark" ...>
        """
        event_link_el = card.select_one(
            "a.tribe-events-calendar-list__event-title-link[href]"
        ) or card.select_one('a[rel="bookmark"][href*="/event/"]')
        href = (event_link_el.get("href") or "").strip() if event_link_el else ""
        event_link = urljoin(self.BASE_URL, href) if href else ""
        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_events(self, client: Optional[requests.Session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        return []

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        res: set[str] = set()
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            if event_link:
                res.add(event_link)
        # The Events Calendar list pagination: rel="next" on .tribe-events-c-nav__list-item--next
        next_el = self.soup.select_one('a[rel="next"][href]') or self.soup.select_one(
            "li.tribe-events-c-nav__list-item--next a[href]"
        )
        href = (next_el.get("href") or "").strip() if next_el else ""
        if href and href != "#":
            res.add(urljoin(self.BASE_URL, href))
        return list(res)

    def __str__(self):
        return f"CharlottesvilleFamilyWebsite w/ URL: {self.url}"


class CharlottesvilleFamilyEventWebsite(EventsWebsite):
    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.charlottesvillefamily.com"
        self.BASE_EVENTS_URL = self.BASE_URL + "/top-family-events"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """
        Single-event pages may rely on theme/JS (blocks, venue, subscribe UI).
        wait_for_selector forces HybridClient to render with Chromium.
        """
        if self.soup:
            return

        from ..http_client import HybridClient, NoDriverClient

        session = client.session if client else requests.Session()
        if "User-Agent" not in getattr(session, "headers", {}):
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )

        wait_sel = (
            "h1.tribe-events-single-event-title, "
            "div.type-tribe_events.tribe_events, "
            "address.tribe-block__venue__address, "
            "address.tribe-events-address"
        )

        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector=wait_sel,
                    wait_for_timeout=45,
                )
            else:
                response = session.get(self.url, timeout=10)

            status = response.status_code
            print(f"[CharlottesvilleFamilyEventWebsite] GET {self.url} -> {status}", flush=True)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
            has_root = bool(self._event_post_root(self.soup))
            print(
                f"[CharlottesvilleFamilyEventWebsite] soup {len(response.text)} chars, "
                f"event_root={has_root}",
                flush=True,
            )
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[CharlottesvilleFamilyEventWebsite] HTTP ERROR GET {self.url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(
                f"[CharlottesvilleFamilyEventWebsite] GET {self.url} -> network error: {e}",
                flush=True,
            )
            self.soup = None

    @staticmethod
    def _event_post_root(soup: BeautifulSoup) -> Optional[Tag]:
        """
        WordPress + The Events Calendar wrap the single event in a post div, e.g.
        <div id="post-41528" class="post-41528 tribe_events type-tribe_events ...">
        Select by type class (id changes per post).
        """
        return soup.select_one("div.type-tribe_events.tribe_events") or soup.select_one(
            "div.tribe_events.type-tribe_events"
        )

    @staticmethod
    def _hhmm_from_12h(chunk: str) -> Optional[str]:
        chunk = clean_text(chunk.replace("\xa0", " ").strip())
        m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)\b", chunk, re.I)
        if not m:
            return None
        h, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
        if mm > 59 or h > 12:
            return None
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return f"{h:02d}:{mm:02d}"

    @classmethod
    def _parse_meta_schedule(cls, soup: BeautifulSoup) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        start_date = end_date = start_time = end_time = None
        abbr_start = soup.select_one("abbr.tribe-events-start-date[title]")
        if abbr_start and abbr_start.get("title"):
            t = abbr_start["title"].strip()[:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", t):
                start_date = t
        abbr_end = soup.select_one("abbr.tribe-events-end-date[title]")
        if abbr_end and abbr_end.get("title"):
            t = abbr_end["title"].strip()[:10]
            if re.match(r"^\d{4}-\d{2}-\d{2}$", t):
                end_date = t
        time_el = soup.select_one(".tribe-events-start-time")
        raw_time = time_el.get_text(" ", strip=True) if time_el else ""
        m = re.search(
            r"(\d{1,2}:\d{2}\s*(?:am|pm))\s*[-\u2013]\s*(\d{1,2}:\d{2}\s*(?:am|pm))",
            raw_time,
            re.I,
        )
        if m:
            start_time = cls._hhmm_from_12h(m.group(1))
            end_time = cls._hhmm_from_12h(m.group(2))
        elif raw_time:
            start_time = cls._hhmm_from_12h(raw_time)
        if end_date is None and start_date:
            end_date = start_date
        return start_date, end_date, start_time, end_time

    @staticmethod
    def _schedule_from_google_calendar_link(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        a = soup.select_one(
            'a.tribe-events-c-subscribe-dropdown__list-item-link[href*="google.com/calendar/event"]'
        )
        if not a or not a.get("href"):
            return None, None, None, None
        qs = parse_qs(urlparse(a["href"]).query)
        dates = (qs.get("dates") or [None])[0]
        if not dates or "/" not in dates:
            return None, None, None, None

        def piece(s: str) -> tuple[Optional[str], Optional[str]]:
            s = s.strip()
            if len(s) >= 9 and s[8] == "T":
                day = f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
                tail = s[9:]
                if len(tail) >= 4 and tail.isdigit():
                    h, mm = int(tail[0:2]), int(tail[2:4])
                    return day, f"{h:02d}:{mm:02d}"
                return day, None
            if len(s) >= 8 and s[:8].isdigit():
                return f"{s[0:4]}-{s[4:6]}-{s[6:8]}", None
            return None, None

        left, _, right = dates.partition("/")
        sd, st = piece(left)
        ed, et = piece(right)
        return sd, st, ed, et

    @staticmethod
    def _description_from_block_editor_prose(scope: Tag) -> str:
        """
        TEC single template with tribe-blocks-editor outputs body copy as bare <p> siblings
        after the featured image (no .tribe-events-single-event-description wrapper).
        """
        paras = scope.select("div.tribe-events-event-image ~ p")
        if not paras:
            paras = scope.select("div.tribe-events-schedule ~ p")
        parts = [
            clean_text(p.get_text("\n", strip=True))
            for p in paras
            if clean_text(p.get_text("\n", strip=True))
        ]
        return "\n\n".join(parts) if parts else ""

    @classmethod
    def _extract_description(cls, scope: Tag, soup: BeautifulSoup) -> str:
        desc_el = scope.select_one(".tribe-events-single-event-description.tribe-events-content")
        if not desc_el:
            desc_el = scope.select_one(".tribe-events-single-event-description")
        if desc_el:
            return clean_text(desc_el.get_text("\n", strip=True))
        prose = cls._description_from_block_editor_prose(scope)
        if prose:
            return prose
        # Last resort: Yoast / schema often mirrors description in JSON-LD
        script = soup.select_one('script.yoast-schema-graph[type="application/ld+json"]')
        if script and script.string:
            try:
                data = json.loads(script.string)
                for node in (data.get("@graph") or []):
                    if node.get("@type") == "Event" and node.get("description"):
                        return clean_text(node["description"])
            except (json.JSONDecodeError, TypeError):
                pass
        return ""

    @staticmethod
    def _address_from_venue_meta(scope: Tag, soup: BeautifulSoup) -> str:
        """
        When there is no street <address> block, TEC still lists a venue in the event meta
        sidebar (e.g. "Downtown Pedestrian Mall, Charlottesville" linking to /venue/...).
        """
        for container in (
            scope.select_one(".tribe-events-meta-group-venue"),
            soup.select_one(".tribe-events-meta-group-venue"),
        ):
            if not container:
                continue
            link = container.select_one(
                "li.tribe-venue a[href], li.tribe-events-meta-item.tribe-venue a[href]"
            )
            if link:
                t = clean_text(link.get_text(" ", strip=True))
                if t:
                    return t
            li = container.select_one("li.tribe-venue, li.tribe-events-meta-item.tribe-venue")
            if li:
                t = clean_text(li.get_text(" ", strip=True))
                if t:
                    return t
        return ""

    @staticmethod
    def _extract_address(soup: BeautifulSoup, scope: Tag) -> str:
        """
        Classic TEC: address.tribe-events-address
        Block editor: address.tribe-block__venue__address with span.tribe-address
        Fallback: venue label from .tribe-events-meta-group-venue (sidebar)
        """
        addr_el = None
        for sel in (
            "address.tribe-events-address",
            "address.tribe-block__venue__address",
        ):
            addr_el = scope.select_one(sel) or soup.select_one(sel)
            if addr_el:
                break
        if addr_el:
            line_el = addr_el.select_one("span.tribe-address")
            if line_el:
                return clean_text(line_el.get_text(" ", strip=True))
            text = clean_text(addr_el.get_text(" ", strip=True))
            return re.sub(r"\s*\+\s*Google Map\s*$", "", text, flags=re.I).strip()

        return CharlottesvilleFamilyEventWebsite._address_from_venue_meta(scope, soup)

    def get_events(self, client: Optional[requests.Session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        root = self._event_post_root(self.soup)
        scope = root or self.soup

        title_el = self.soup.select_one("h1.tribe-events-single-event-title")
        title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""

        description = self._extract_description(scope, self.soup)

        img_el = scope.select_one(".tribe-events-event-image img[src]")
        image_href = (img_el.get("src") or "").strip() if img_el else ""
        image_url = urljoin(self.BASE_URL, image_href) if image_href else ""

        address = self._extract_address(self.soup, scope)

        event_site_el = scope.select_one(".tribe-events-event-url a[href]")
        event_website = (event_site_el.get("href") or "").strip() if event_site_el else ""

        start_date, end_date, start_time, end_time = self._parse_meta_schedule(scope)
        if not start_date:
            gs, gt, ge, gendt = self._schedule_from_google_calendar_link(scope)
            start_date = start_date or gs
            end_date = end_date or ge
            start_time = start_time or gt
            end_time = end_time or gendt
        if end_date is None and start_date:
            end_date = start_date

        scraped_at = datetime.now(timezone.utc).isoformat()
        event_link = self.url.split("?", 1)[0].rstrip("/")

        return [
            {
                "title": title,
                "event_link": event_link,
                "description": description,
                "address": address,
                "phone": "",
                "organizer": "Charlottesville Family",
                "website": event_website or self.BASE_URL,
                "image_url": image_url,
                "start_date": start_date,
                "end_date": end_date,
                "start_time": start_time,
                "end_time": end_time,
                "scraped_at": scraped_at,
            }
        ]

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"CharlottesvilleFamilyEventWebsite w/ URL: {self.url}"