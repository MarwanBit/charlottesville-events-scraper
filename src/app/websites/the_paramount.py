from .base import EventsWebsite
from typing import Optional
import re
import requests
from bs4 import Tag, BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import urljoin

from ..utils import clean_text


class TheParamountWebsite(EventsWebsite):
    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.theparamount.net"
        self.BASE_EVENTS_URL = self.BASE_URL + "/events"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """
        /events/ loads cards via Ajax Load More; plain HTTP returns an empty .alm-listing.
        With HybridClient / NoDriverClient, wait for the first listing card before parsing.
        """
        if self.soup:
            return

        from ..http_client import HybridClient, NoDriverClient

        session = client.session if client else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )

        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector=".post-col.post-col-border",
                    wait_for_timeout=45,
                )
            else:
                response = session.get(self.url, timeout=10)

            status = response.status_code
            print(f"[TheParamountWebsite] GET {self.url} -> {status}", flush=True)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
            n_cards = len(self.soup.select(".post-col.post-col-border"))
            print(
                f"[TheParamountWebsite] soup {len(response.text)} chars, {n_cards} cards",
                flush=True,
            )
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[TheParamountWebsite] HTTP ERROR GET {self.url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(
                f"[TheParamountWebsite] GET {self.url} -> network error: {e}",
                flush=True,
            )
            self.soup = None

    def _listing_urls_from_load_more(self) -> list[str]:
        """
        button.alm-load-more-btn has no href; Paramount pairs it with .alm-paging
        <a href=".../events/?pg=N"> for no-JS / crawler pagination.
        Skip when the button is .done (nothing left to load).
        """
        if not self.soup:
            return []
        btn = self.soup.select_one("button.alm-load-more-btn")
        if not btn:
            return []
        if "done" in (btn.get("class") or []):
            return []
        urls: list[str] = []
        for a in self.soup.select(".alm-paging a[href]"):
            href = (a.get("href") or "").strip()
            if href:
                urls.append(urljoin(self.BASE_URL, href))
        return urls

    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        # Paramount /events/ uses Ajax Load More: cards are div.post-col.post-col-border
        # inside .alm-listing (some rows also have .alm-filters on the same element).
        cards = self.soup.select(".post-col.post-col-border")
        return cards

    def extract_event_from_card(self, card: Tag) -> dict:
        """
        Use the <a href="...">Learn More</a> CTA under .post-col-content.
        Falls back to title or any /event/ link if that anchor is missing.
        """
        content = card.select_one(".post-col-content")
        if not content:
            return {
                "event_link": "",
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
        event_link_el = None
        for a in content.find_all("a", href=True):
            if a.get_text(strip=True) == "Learn More":
                event_link_el = a
                break
        if not event_link_el:
            event_link_el = content.select_one("a.title[href]") or content.select_one(
                'a[href*="/event/"]'
            )
        href = (event_link_el.get("href") or "").strip() if event_link_el else ""
        event_link = urljoin(self.BASE_URL, href) if href else ""
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
            link = self.extract_event_from_card(card)["event_link"]
            if link:
                res.add(link)
        for listing_url in self._listing_urls_from_load_more():
            res.add(listing_url)
        return list(res)

    def __str__(self) -> str:
        return f"TheParamountWebsite w/ URL: {self.url}"


class TheParamountEventWebsite(EventsWebsite):
    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.theparamount.net"
        self.BASE_EVENTS_URL = self.BASE_URL + "/events"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """
        Event pages can rely on theme/JS for layout; use the same Chromium path as the listing
        when HybridClient / NoDriverClient is available so content matches what users see.
        """
        if self.soup:
            return

        from ..http_client import HybridClient, NoDriverClient

        session = client.session if client else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )

        # First match in document order (title, body copy, or sidebar schedule).
        wait_sel = "h2.font-bold.no-margin, div.main-content, div.info.info-desktop"

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
            print(f"[TheParamountEventWebsite] GET {self.url} -> {status}", flush=True)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
            has_title = bool(self.soup.select_one("h2.font-bold.no-margin"))
            has_main = bool(self.soup.select_one("div.main-content"))
            has_info = bool(
                self.soup.select_one("div.info.info-desktop")
                or self.soup.select_one("div.info")
            )
            print(
                f"[TheParamountEventWebsite] soup {len(response.text)} chars "
                f"(title={has_title} main={has_main} info={has_info})",
                flush=True,
            )
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[TheParamountEventWebsite] HTTP ERROR GET {self.url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(
                f"[TheParamountEventWebsite] GET {self.url} -> network error: {e}",
                flush=True,
            )
            self.soup = None

    @staticmethod
    def _parse_time_12h_us(s: str) -> Optional[str]:
        s = clean_text((s or "").replace("\xa0", " "))
        m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)\b", s, re.I)
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
    def _year_for_month_day_in_main_content(
        cls, soup: BeautifulSoup, month: str, day: int
    ) -> Optional[int]:
        """Sidebar DATE often omits year; same show page usually spells it in main copy (e.g. 'April 4, 2026')."""
        main = soup.select_one("div.main-content")
        if not main:
            return None
        text = main.get_text(" ", strip=True)
        pat = re.compile(rf"\b{re.escape(month)}\s+{day}\b\s*,?\s*(\d{{4}})\b", re.I)
        m = pat.search(text)
        return int(m.group(1)) if m else None

    @classmethod
    def _schedule_from_soup(cls, soup: BeautifulSoup) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Sidebar: div.info.info-desktop (or div.info) → .time-date with DATE line and ul.event-list time.
        Year is taken from div.main-content when the DATE line has no year.
        """
        info = soup.select_one("div.info.info-desktop") or soup.select_one("div.info")
        if not info:
            return None, None, None, None
        time_date = info.select_one(".time-date") or info

        date_line = ""
        for p in time_date.find_all("p"):
            tag = p.find("span", class_="label-tag")
            if not tag:
                continue
            if "DATE" not in (tag.get_text() or "").upper():
                continue
            raw = p.get_text(" ", strip=True)
            date_line = clean_text(re.sub(r"^\s*DATE\s*", "", raw, flags=re.I)).strip()
            break

        time_li = time_date.select_one("ul.event-list li")
        time_raw = time_li.get_text(" ", strip=True) if time_li else ""

        start_time = cls._parse_time_12h_us(time_raw) if time_raw else None

        start_date: Optional[str] = None
        if date_line:
            has_year = bool(re.search(r"\b\d{4}\s*$", date_line))
            if has_year:
                for fmt in ("%A, %B %d, %Y", "%A, %B %d %Y"):
                    try:
                        start_date = datetime.strptime(date_line, fmt).date().isoformat()
                        break
                    except ValueError:
                        continue
            if not start_date:
                m = re.match(
                    r"^(?P<wd>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,\s*"
                    r"(?P<mon>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
                    r"(?P<d>\d{1,2})\s*$",
                    date_line,
                    re.I,
                )
                if m:
                    mon, d = m.group("mon"), int(m.group("d"))
                    year = cls._year_for_month_day_in_main_content(soup, mon, d)
                    if year is None:
                        year = datetime.now(timezone.utc).year
                    try:
                        full = f"{m.group('wd')}, {mon} {d}, {year}"
                        start_date = datetime.strptime(full, "%A, %B %d, %Y").date().isoformat()
                    except ValueError:
                        start_date = None

        end_date = start_date
        end_time = None
        return start_date, start_time, end_date, end_time

    @staticmethod
    def _hero_image_url(soup: BeautifulSoup, base_url: str) -> str:
        """
        Event hero lives in div.img-container > img (often under main/article).
        Prefer main/article so we skip header/footer logo .img-container blocks.
        """
        img_el = None
        for sel in ("main .img-container img[src]", "article .img-container img[src]"):
            img_el = soup.select_one(sel)
            if img_el:
                break
        if not img_el:
            img_el = soup.select_one("div.img-container img[src]")
        if not img_el:
            return ""
        raw = clean_text(img_el.get("src") or "")
        if not raw:
            return ""
        if raw.startswith("//"):
            return "https:" + raw
        if raw.startswith("/"):
            return urljoin(base_url, raw)
        return raw

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        title_el = self.soup.select_one("h2.font-bold.no-margin")
        title = (
            clean_text(title_el.get_text(" ", strip=True)) if title_el else ""
        )

        scraped_at = datetime.now(timezone.utc).isoformat()
        event_link = self.url.split("?", 1)[0].rstrip("/")

        main_el = self.soup.select_one("div.main-content")
        description = (
            clean_text(main_el.get_text("\n", strip=True)) if main_el else ""
        )
        address = "215 East Main Street Charlottesville, VA 22902"
        phone = "434.979.1922"
        organizer = "The Paramount"
        image_url = self._hero_image_url(self.soup, self.BASE_URL)
        start_date, start_time, end_date, end_time = self._schedule_from_soup(self.soup)

        return [
            {
                "title": title,
                "event_link": event_link,
                "description": description,
                "address": address,
                "phone": phone,
                "organizer": organizer,
                "website": self.BASE_URL,
                "image_url": image_url,
                "start_date": start_date,
                "end_date": end_date,
                "start_time": start_time,
                "end_time": end_time,
                "scraped_at": scraped_at,
            }
        ]

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"TheParamountEventWebsite w/ URL: {self.url}"
