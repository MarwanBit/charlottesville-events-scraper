from .base import EventsWebsite
from typing import Optional, TYPE_CHECKING
import requests
from bs4 import Tag, BeautifulSoup
from datetime import datetime, timezone
from ..utils import clean_text
import dateparser
import re

from ..explore_georgia_parsing import (
    ALL_DAY_END,
    ALL_DAY_START,
    _normalize_datetime_str,
    _normalize_for_date_parse,
    parse_date_range,
    parse_event_datetime_range,
)

if TYPE_CHECKING:
    from ..http_client import NoDriverClient, HybridClient


class ExploreGeorgiaWebsite(EventsWebsite):
    
    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://exploregeorgia.org"
        self.BASE_EVENTS_URL = self.BASE_URL + "/calendar-of-events"

    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.soup.select("div.views-row")
        return cards

    def extract_event_from_card(self, card: Tag) -> list[dict]:
        event_link_el = card.select_one("div.title-venue a")
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
        # this gets the next page
        next_el = self.soup.select_one("li.pager__item.pager__item--next a")
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
        return f"ExploreGeorgiaWebsite w/ URL: {self.url}"


class ExploreGeorgiaEventWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://exploregeorgia.org"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """
        Override to use browser client wait_for_selector so JS-rendered date list is present.
        Falls back to plain requests if no browser client is provided.
        """
        if self.soup:
            return
        from ..http_client import NoDriverClient, HybridClient
        session = client.session if client else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )
        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                # Wait until the JS-populated date list appears before capturing HTML.
                # The schedule rows are rendered as elements with the 'date-list-item' class.
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector=".month-group .date-list-item",
                    wait_for_timeout=45,
                )
            else:
                response = session.get(self.url, timeout=10)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            print(f"Error fetching {self.url}: {e}")
            self.soup = None

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            print("[ExploreGeorgiaEventWebsite] no soup loaded for event page; returning 0 events", flush=True)
            return []

        description_el = self.soup.select_one("div.mmg8_listing_fields_description")
        phone_el = self.soup.select_one("a.phone-link")
        website_el = self.soup.select_one("a.website-link")
        img_el = self.soup.select_one('img')
        title_el = self.soup.select_one('div.group-data-node-intro h1')

        # Address block: div.mmg8_listing_fields_address (or mmg8-listing-fields) contains venue, div.address, city-state-zip
        address_block = self.soup.select_one("div.mmg8_listing_fields_address")
        if not address_block:
            address_block = self.soup.select_one("div.mmg8-listing-fields.mmg8_listing_fields_address")
        address_venue_el = address_block.select_one("div.address-venue") if address_block else None
        street_el = address_block.select_one("div.address") if address_block else None
        city_el = address_block.select_one("span.city") if address_block else None
        state_el = address_block.select_one("span.state") if address_block else None
        zip_code_el = address_block.select_one("span.zip") if address_block else None

        address_venue = clean_text(address_venue_el.get_text(strip=True)) if address_venue_el else ""
        street = clean_text(street_el.get_text(strip=True)) if street_el else ""
        city = clean_text(city_el.get_text(strip=True)) if city_el else ""
        state = clean_text(state_el.get_text(strip=True)) if state_el else ""
        zip_code = clean_text(zip_code_el.get_text(strip=True)) if zip_code_el else ""
        # Combine into full address (skip overwriting with street-only below)
        parts = [p for p in [address_venue, street, city, f"{state} {zip_code}".strip()] if p]
        address = ", ".join(parts) if parts else ""

        description = clean_text(description_el.get_text()) if description_el else ""
        phone = clean_text(phone_el.get_text(strip=True)) if phone_el else ""
        website = clean_text(website_el.get("href")) if website_el and website_el.get("href") else ""
        image_url = self.BASE_URL + clean_text(img_el.get("src")) if img_el and img_el.get("src") else ""
        organizer = None
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""

        events: list[dict] = []
        scraped_at = datetime.now(timezone.utc).isoformat()

        # Date rows: originally ".month-group .date-list-item" with a ".month-and-day-number" child.
        date_items = self.soup.select(".month-group .date-list-item")
        if not date_items:
            # Fallback: try a looser selector; refine this with the live HTML from VNC if needed.
            date_items = self.soup.select(".date-list-item")
        print(
            f"[ExploreGeorgiaEventWebsite] found {len(date_items)} date rows for {self.url}",
            flush=True,
        )

        for item in date_items:
            date_el = item.select_one(".month-and-day-number")
            if not date_el:
                print(
                    "[ExploreGeorgiaEventWebsite] date-list-item missing .month-and-day-number; skipping",
                    flush=True,
                )
                continue
            date_text = date_el.get_text(strip=True)
            for (
                start_date,
                end_date,
                start_time,
                end_time,
            ) in parse_event_datetime_range(date_text):
                events.append(
                    {
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
                    }
                )
        print(
            f"[ExploreGeorgiaEventWebsite] emitting {len(events)} events for {self.url}",
            flush=True,
        )
        return events

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"ExploreGeorgiaEventWebsite w/ URL: {self.url}"