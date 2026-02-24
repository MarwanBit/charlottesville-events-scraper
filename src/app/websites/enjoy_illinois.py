from .base import EventsWebsite
from typing import Optional, TYPE_CHECKING
import requests
from bs4 import Tag, BeautifulSoup
from datetime import datetime, timezone
from ..utils import clean_text
import dateparser
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from datetime import datetime
import re

from datetime import date

def parse_date_range(s, year=None):
    if year is None:
        year = date.today().year

    if not s or not str(s).strip():
        return None, None

    month_map = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
        "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
        "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
    }

    # Support "to", " - ", and en-dash " – " as range separators
    s = str(s).strip()
    parts = re.split(r"\s+to\s+|\s+-\s+|\s+–\s+", s, maxsplit=1)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) == 1:
        # Single date: use as both start and end
        try:
            left = parts[0]
            m_str, d = left.split(maxsplit=1)
            m = month_map.get(m_str)
            if m is None:
                return None, None
            d = int(d)
            single = date(year, m, d)
            return single, single
        except (ValueError, KeyError):
            return None, None

    if len(parts) != 2:
        return None, None

    left, right = parts[0], parts[1]
    try:
        m1_str, d1 = left.split()
        m2_str, d2 = right.split()
    except ValueError:
        return None, None

    m1 = month_map.get(m1_str)
    m2 = month_map.get(m2_str)
    if m1 is None or m2 is None:
        return None, None
    try:
        d1, d2 = int(d1), int(d2)
    except ValueError:
        return None, None

    start = date(year, m1, d1)
    # Handle year rollover (e.g., Sep → Feb)
    end_year = year if m2 >= m1 else year + 1
    end = date(end_year, m2, d2)
    return start, end

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

    def extract_event_from_card(self, card: Tag) -> list[dict]:
        # Link must be inside the card (event detail URL), not the first <a> on the page
        event_link_el = card.select_one('a[href]')
        title_el = card.select_one('h3.text-base')
        date_el = card.select_one('div.listing-image.relative')
        address_el = None
        image_el = card.select_one('img')

        # if date_el remove the favorites
        if date_el:
            for el in date_el.select('.favourites, .sr-only'):
                el.decompose()

        href = event_link_el.get("href", "").strip() if event_link_el else ""
        if href and not href.startswith("http"):
            href = (self.BASE_URL + href) if href.startswith("/") else (self.BASE_URL + "/" + href)
        event_link = clean_text(href) if href else ""
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""
        date = clean_text(date_el.get_text(" ", strip=True)) if date_el else ""
        address = None
        image_url = clean_text(image_el.get('src')) if image_el and image_el.get('src') else ""
        phone = None 
        website = None

        print(date)
        start_date, end_date = parse_date_range(date)
        start_time, end_time = None, None

        return {
            "event_link": event_link,
            "title": title,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "address": address,
            "phone": phone,
            "website": website,
            "image_url": image_url,
            "scraped_at": datetime.now(timezone.utc).isoformat()
        }


    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.parse_listing_cards(client)
        res = []
        for card in cards:
            res.append(self.extract_event_from_card(card))
        return res

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
        # Get the address
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        address_el = None
        phone_el = None
        description_el = self.soup.select_one('#synopsis')
        website_el = self.soup.find("a", string="Visit Website")
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
        image_url = None
        organizer = None
        
        return [{
            "event_link": self.url,
            "description": description,
            "image_url": image_url,
            "organizer": organizer,
            "address": address,
            "scraped_at":  datetime.now(timezone.utc).isoformat(),
            "website": website,
            "phone": phone
        }]

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"EnjoyIllinoisEventWebsite w/ URL: {self.url}" 

