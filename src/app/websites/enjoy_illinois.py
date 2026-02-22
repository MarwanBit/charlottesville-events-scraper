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
        return int(query.get("offset", [0])[0])

    def increment_offset(self, step: int = 12) -> str:
        parsed = urlparse(self.url)
        query = parse_qs(parsed.query)
        current_offset = int(query.get("offset", [0])[0])
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
        title_el = None
        date_el = None
        address_el = None
        image_el = None

        href = event_link_el.get("href", "").strip() if event_link_el else ""
        if href and not href.startswith("http"):
            href = (self.BASE_URL + href) if href.startswith("/") else (self.BASE_URL + "/" + href)
        event_link = clean_text(href) if href else ""
        title = None
        date = None
        address = None
        image_url = None
        phone = None 
        website = None

        start_date, end_date = None, None
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
        raise NotImplementedError("function not implemented")

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"EnjoyIllinoisEventWebsite w/ URL: {self.url}" 

