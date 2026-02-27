from .base import EventsWebsite
from typing import Optional
import requests
from bs4 import Tag, BeautifulSoup
from ..utils import clean_text
from datetime import datetime, timezone, date, time, timedelta
import dateparser
import re


def extract_datetime_range(
    text: str,
    reference_date: Optional[datetime] = None,
) -> list[tuple[date | None, date | None, time | None, time | None]]:
    """
    Extract VisitMA-style date/time strings into a list of
    (start_date, end_date, start_time, end_time) tuples.

    Each tuple represents one calendar day; start_date == end_date for that
    tuple. For a multi-day range we expand into one tuple per day; for a
    single date we return a one-element list. On parse failure we return
    [(None, None, None, None)].
    """
    if reference_date is None:
        reference_date = datetime.now()

    s = (text or "").strip()
    if not s:
        return [(None, None, None, None)]

    # Normalize AM/PM variants.
    norm = re.sub(r"(?i)a\.m\.", "AM", s)
    norm = re.sub(r"(?i)p\.m\.", "PM", norm)

    # -------- Time parsing --------
    time_pattern = re.compile(r"\b\d{1,2}(:\d{2})?\s*[AP]M\b", re.IGNORECASE)
    time_matches = [m.group(0) for m in time_pattern.finditer(norm)]

    start_time = end_time = None
    if time_matches:
        first = dateparser.parse(
            time_matches[0], settings={"RELATIVE_BASE": reference_date}
        )
        start_time = first.time() if first else None
        # If there is an explicit range ("to" / "-" / "–" / "—"), use the second time as end_time.
        if len(time_matches) >= 2 and re.search(r"\b(to|-|–|—)\b", norm, re.IGNORECASE):
            second = dateparser.parse(
                time_matches[1], settings={"RELATIVE_BASE": reference_date}
            )
            end_time = second.time() if second else None

    # -------- Date parsing --------
    start_date = end_date = None

    # Pattern A: full dates on both sides, e.g. "Nov 21, 2025 - Fri, May 22, 2026"
    pat_full_range = re.compile(
        r"([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})\s*-\s*(?:[A-Za-z]{3},\s*)?([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})"
    )
    m = pat_full_range.search(norm)
    if m:
        left, right = m.group(1), m.group(2)
        left_dt = dateparser.parse(left, settings={"RELATIVE_BASE": reference_date})
        right_dt = dateparser.parse(right, settings={"RELATIVE_BASE": reference_date})
        start_date = left_dt.date() if left_dt else None
        end_date = right_dt.date() if right_dt else None
    else:
        # Pattern B: month/day without year on left, full date with year on right.
        # e.g. "Fri, Jun 19 - Sun, Jun 28, 2026"
        pat_partial_left = re.compile(
            r"([A-Za-z]{3,9}\s+\d{1,2})\s*-\s*(?:[A-Za-z]{3},\s*)?([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})"
        )
        m = pat_partial_left.search(norm)
        if m:
            left, right = m.group(1), m.group(2)
            right_dt = dateparser.parse(right, settings={"RELATIVE_BASE": reference_date})
            if right_dt:
                end_date = right_dt.date()
                # Assume same year for left side.
                left_full = f"{left} {end_date.year}"
                left_dt = dateparser.parse(
                    left_full, settings={"RELATIVE_BASE": reference_date}
                )
                start_date = left_dt.date() if left_dt else None
        else:
            # Single full date somewhere in the string, e.g. "Mar 15, 2026" or "Aug 31, 2026"
            m = re.search(r"[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}", norm)
            if m:
                d = dateparser.parse(m.group(0), settings={"RELATIVE_BASE": reference_date})
                if d:
                    start_date = end_date = d.date()
    # -------- Convert to list-of-tuples --------
    if start_date is None and end_date is None:
        return [(None, None, start_time, end_time)]

    if start_date is None:
        start_date = end_date
    if end_date is None:
        end_date = start_date

    result: list[tuple[date, date, time | None, time | None]] = []
    current = start_date
    while current <= end_date:
        result.append((current, current, start_time, end_time))
        current = current + timedelta(days=1)
    return result


class VisitMAWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.visitma.com"
        self.BASE_EVENTS_URL = self.BASE_URL + "/events"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """
        Override to use HybridClient/NoDriverClient wait_for_selector so the
        JS-rendered event cards are present before we parse.
        """
        if self.soup:
            return

        from ..http_client import NoDriverClient, HybridClient  # lazy import

        session = client.session if client and hasattr(client, "session") else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; VisitMAEventsBot/1.0)"}
            )

        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                # Wait for event cards or event links to appear.
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector=".grid-block.grid-api, a[href^=\"/event/\"]",
                    wait_for_timeout=45,
                )
            else:
                response = session.get(self.url, timeout=20)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            print(f"[VisitMAWebsite] Error fetching {self.url}: {e}", flush=True)
            self.soup = None

    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.soup.select(".grid-block.grid-api")
        return cards

    def extract_event_from_card(self, card: Tag) -> list[dict]:
        event_link_el = card.select_one("h3.location-name a.grid-block-link-wrapper")
        event_link = self.BASE_URL + event_link_el.get("href") if event_link_el and event_link_el.get("href") else ""
        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat()
        }

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        '''
        cards = self.parse_listing_cards(client)
        res = []
        for card in cards:
            res.append(self.extract_event_from_card(card))
        return res
        '''
        return []

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        res = set[str]()
        # This gets the next page
        next_el = self.soup.find("a", class_="next page-numbers")
        if next_el and next_el.get("href"):
            link = next_el["href"]
            if link not in res:
                res.add(self.BASE_EVENTS_URL + link)
        # Now we need to get the links for each of the cards
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            if event_link not in res:
                res.add(event_link)
        return list[str](res)

    def __str__(self):
        return f"VisitMAWebsite w/ URL: {self.url}"





class VisitMAEventWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://www.visitma.com"

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        description_el = self.soup.select_one("div.description")
        address_el = self.soup.select_one("div.venue-address")
        phone_el = self.soup.select_one("a.call-number")
        website_el = self.soup.select_one("a.website.event-url")
        date_el = self.soup.select_one("div.when")
        img_el = self.soup.select_one("img.img")
        title_el = self.soup.select_one("div.mott-single-contact h3")

        description = clean_text(description_el.get_text()) if description_el else ""
        address = clean_text(address_el.get_text()) if address_el else ""
        phone = clean_text(phone_el.get_text(strip=True)) if phone_el else ""
        website = clean_text(website_el.get("href")) if website_el and website_el.get("href") else ""
        image_url = clean_text(img_el.get("src")) if img_el else ""
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""
        organizer = None

        date_text = date_el.get_text(strip=True) if date_el else ""
        ranges = extract_datetime_range(date_text)

        events: list[dict] = []
        scraped_at = datetime.now(timezone.utc).isoformat()
        for start_date, end_date, start_time, end_time in ranges:
            events.append(
                {
                    "title": title,
                    "event_link": self.url,
                    "description": description,
                    "image_url": image_url,
                    "organizer": organizer,
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_time": start_time,
                    "end_time": end_time,
                    "address": address,
                    "scraped_at": scraped_at,
                    "website": website,
                    "phone": phone,
                }
            )

        return events

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    def __str__(self) -> str:
        return f"VisitMAEventWebsite w/ URL: {self.url}"