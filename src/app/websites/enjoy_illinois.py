from .base import EventsWebsite
from typing import Optional, TYPE_CHECKING
import requests
from bs4 import Tag, BeautifulSoup
from datetime import datetime, timezone, date, time, timedelta
from ..utils import clean_text
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_simple_time(hh_mm: str, ampm: str) -> time:
    parts = hh_mm.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    if ampm.lower() == "pm" and h != 12:
        h += 12
    elif ampm.lower() == "am" and h == 12:
        h = 0
    return time(h, m)


def _parse_month_day_from_tokens(tokens: list[str]) -> Optional[tuple[int, int]]:
    for i, t in enumerate(tokens):
        m = MONTH_MAP.get(t)
        if m is not None and i + 1 < len(tokens):
            d_str = tokens[i + 1].rstrip(",")
            try:
                d = int(d_str)
                return (m, d)
            except ValueError:
                pass
    return None


def parse_date_range(
    s: Optional[str],
    year: Optional[int] = None,
) -> list[tuple[Optional[date], Optional[date], Optional[time], Optional[time]]]:
    """
    Parse Enjoy Illinois "When" strings like:
      "Saturday, Jun 6 , 2026 • 8:00am - 3:00pm"
      "Wednesday, Jun 10 to Sunday, Jun 14, 2026 • 9:00am - 8:00pm"
    Returns a list of (start_date, end_date, start_time, end_time), one tuple per day.
    """
    if year is None:
        year = date.today().year
    s = (s or "").strip()
    if not s:
        return [(None, None, None, None)]

    # Split optional time part: " • 8:00am - 3:00pm"
    date_part = s
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    if " • " in s:
        date_part, time_part = s.split(" • ", 1)
        date_part = date_part.strip()
        time_part = time_part.strip()
        # Range: "8:00am - 3:00pm"
        time_match = re.match(
            r"(\d{1,2}:\d{2})\s*(am|pm)\s*-\s*(\d{1,2}:\d{2})\s*(am|pm)",
            time_part,
            re.IGNORECASE,
        )
        if time_match:
            start_time = _parse_simple_time(time_match.group(1), time_match.group(2))
            end_time = _parse_simple_time(time_match.group(3), time_match.group(4))
        else:
            # Single time only: "7:00pm"
            single_match = re.match(r"(\d{1,2}:\d{2})\s*(am|pm)\s*$", time_part, re.IGNORECASE)
            if single_match:
                start_time = _parse_simple_time(single_match.group(1), single_match.group(2))
                end_time = None

    # Extract year from end of date_part: ", 2026"
    year_match = re.search(r",\s*(\d{4})\s*$", date_part)
    if year_match:
        year = int(year_match.group(1))

    if " to " in date_part:
        left, right = date_part.split(" to ", 1)
        left_tokens = left.strip().split()
        right_tokens = right.strip().split()
        start_md = _parse_month_day_from_tokens(left_tokens)
        end_md = _parse_month_day_from_tokens(right_tokens)
        if not start_md or not end_md:
            return [(None, None, start_time, end_time)]
        m1, d1 = start_md
        m2, d2 = end_md
        start_date = date(year, m1, d1)
        end_year = year if m2 >= m1 else year + 1
        end_date = date(end_year, m2, d2)
    else:
        tokens = date_part.split()
        start_md = _parse_month_day_from_tokens(tokens)
        if not start_md:
            return [(None, None, start_time, end_time)]
        m, d = start_md
        start_date = end_date = date(year, m, d)

    result: list[tuple[date, date, Optional[time], Optional[time]]] = []
    current = start_date
    while current <= end_date:
        result.append((current, current, start_time, end_time))
        current = current + timedelta(days=1)
    return result

if TYPE_CHECKING:
    from ..http_client import NoDriverClient, HybridClient

# Selector for event listing cards (JS-rendered); used to wait before capturing HTML
ENJOY_ILLINOIS_LISTING_SELECTOR = ".group.listing-item.relative"


class EnjoyIllinoisWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = 'https://www.enjoyillinois.com'
        self.BASE_EVENTS_URL = self.BASE_URL + '/things-to-do/festivals-and-events'

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """Override to use browser client wait_for_selector so JS-rendered event list is present."""
        if self.soup:
            return
        from ..http_client import NoDriverClient, HybridClient
        session = client.session if client else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"
            })
        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector=ENJOY_ILLINOIS_LISTING_SELECTOR,
                    wait_for_timeout=45,
                )
            else:
                response = session.get(self.url, timeout=10)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            print(f"Error fetching {self.url}: {e}")
            self.soup = None

    def get_offset(self) -> int:
        parsed = urlparse(self.url)
        query = parse_qs(parsed.query)
        raw = query.get("offset", ["0"])
        try:
            return int(raw[0]) if raw and str(raw[0]).strip() else 0
        except (ValueError, TypeError, IndexError):
            return 0

    def increment_offset(self, step: int = 12) -> str:
        parsed = urlparse(self.url)
        query = parse_qs(parsed.query)
        raw = query.get("offset", ["0"])
        try:
            current_offset = int(raw[0]) if raw and str(raw[0]).strip() else 0
        except (ValueError, TypeError, IndexError):
            current_offset = 0
        new_offset = current_offset + step
        query["offset"] = [str(new_offset)]
        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.soup.select(".group.listing-item.relative")
        return cards

    def extract_event_from_card(self, card: Tag) -> dict:
        # Prefer the link that goes to the event listing detail (contains /listing/); else first <a>
        event_link_el = card.select_one('a');
        event_link = self.BASE_URL + event_link_el.get('href') if event_link_el and event_link_el.get('href') else ""

        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
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
        '''
        return []

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        res = set[str]()
        cards = self.parse_listing_cards(client)
        if not cards:
            return []
        # Now we need to get the links for each of the cards
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            if event_link not in res:
                res.add(event_link)
        res.add(self.increment_offset())
        # Now we add the new link
        return list[str](res)


    def __str__(self):
        return f"EnjoyIllinoisWebsite w/ URL: {self.url}"


class EnjoyIllinoisEventWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = 'https://www.enjoyillinois.com'
        self.BASE_EVENTS_URL = self.BASE_URL + '/things-to-do/festivals-and-events'

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        # Get the address and date/time ("When") block.
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        address_el = None
        phone_el = None
        description_el = self.soup.select_one('#synopsis')
        website_el = self.soup.find("a", string="Visit Website")
        title_el = self.soup.select_one('h1.h2')

        for dt in self.soup.select("dl dt"):
            if dt.get_text(strip=True) == "Address":
                address_el = dt.find_next_sibling("dd")
                for a in address_el.select("a"):
                    a.decompose()
            if dt.get_text(strip=True) == "Phone":
                phone_el = dt.find_next_sibling("dd")
                phone_el = phone_el.select_one("a") if phone_el else None

        address = clean_text(address_el.get_text(" ", strip=True)) if address_el else ""
        description = clean_text(description_el.get_text(" ", strip=True)) if description_el else ""
        phone = clean_text(phone_el.get_text(strip=True)) if phone_el else ""
        website = clean_text(website_el.get('href')) if website_el and website_el.get('href') else ""

        # Select the date/time line under the "When" label.
        when_text = ""
        for p in self.soup.select("aside p"):
            if p.get_text(strip=True).lower() == "when":
                when_label_el = p
                when_p = when_label_el.find_next_sibling("p")
                strong_el = when_p.find("strong") if when_p else None
                raw = strong_el.get_text(" ", strip=True) if strong_el else (
                    when_p.get_text(" ", strip=True) if when_p else ""
                )
                when_text = clean_text(raw)
                break

        # Keep simple image selection for now (can be upgraded with srcset if needed).
        image_el = self.soup.select_one('img')
        image_url = self.BASE_URL + clean_text(image_el.get('src')) if image_el and image_el.get('src') else ""

        title = clean_text(title_el.get_text(strip=True)) if title_el else ""
        organizer = None
        ranges = parse_date_range(when_text)
        scraped_at = datetime.now(timezone.utc).isoformat()

        events: list[dict] = []
        for start_date, end_date, start_time, end_time in ranges:
            events.append({
                "title": title,
                "event_link": self.url,
                "description": description,
                "image_url": image_url,
                "organizer": organizer,
                "address": address,
                "scraped_at": scraped_at,
                "website": website,
                "phone": phone,
                "start_date": start_date,
                "end_date": end_date,
                "start_time": start_time,
                "end_time": end_time,
            })
        return events

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"EnjoyIllinoisEventWebsite w/ URL: {self.url}" 

