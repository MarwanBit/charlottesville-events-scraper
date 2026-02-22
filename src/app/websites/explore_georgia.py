from .base import EventsWebsite
from typing import Optional
import requests
from bs4 import Tag, BeautifulSoup
from datetime import datetime, timezone
from ..utils import clean_text
import dateparser
import re

from datetime import datetime
import re

def parse_date_range(text):
    match = re.match(r"(.+?)\s*-\s*(.+)", text)
    if not match:
        return None, None
    
    start_str, end_str = match.groups()
    
    fmt = "%B %d, %Y"  # e.g. February 21, 2026
    
    start_date = datetime.strptime(start_str.strip(), fmt)
    end_date = datetime.strptime(end_str.strip(), fmt)
    
    return start_date, end_date


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
        title_el = card.select_one("div.title-venue a")
        date_el = card.select_one("div.event-dates-summary")
        address_el = card.select_one("div.address-venue")
        image_el = card.find("img")

        event_link = self.BASE_URL + event_link_el.get("href") if event_link_el and event_link_el.get("href") else ""
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""
        date = clean_text(date_el.get_text(strip=True)) if date_el else ""
        address = clean_text(address_el.get_text(strip=True)) if address_el else ""
        image_url = clean_text(image_el.get("src")) if image_el and image_el.get("src") else ""
        phone = None 
        website = None

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

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        description_el = self.soup.select_one("div.mmg8_listing_fields_description")
        phone_el = self.soup.select_one("a.phone-link")
        website_el = self.soup.select_one("a.website-link")
        date_el = None
        img_el = None

        # Address block: div.mmg8_listing_fields_address (or mmg8-listing-fields) contains venue, div.address, city-state-zip
        address_block = self.soup.select_one("div.mmg8_listing_fields_address")
        if not address_block:
            address_block = self.soup.select_one("div.mmg8-listing-fields.mmg8_listing_fields_address")
        street_el = address_block.select_one("div.address") if address_block else None
        city_el = address_block.select_one("span.city") if address_block else None
        state_el = address_block.select_one("span.state") if address_block else None
        zip_code_el = address_block.select_one("span.zip") if address_block else None

        street = clean_text(street_el.get_text(strip=True)) if street_el else ""
        city = clean_text(city_el.get_text(strip=True)) if city_el else ""
        state = clean_text(state_el.get_text(strip=True)) if state_el else ""
        zip_code = clean_text(zip_code_el.get_text(strip=True)) if zip_code_el else ""
        # Combine into full address (skip overwriting with street-only below)
        parts = [p for p in [street, city, f"{state} {zip_code}".strip()] if p]
        address = ", ".join(parts) if parts else ""

        description = clean_text(description_el.get_text()) if description_el else ""
        phone = clean_text(phone_el.get_text(strip=True)) if phone_el else ""
        website = clean_text(website_el.get("href")) if website_el and website_el.get("href") else ""
        image_url = clean_text(img_el.get("src")) if img_el and img_el.get("src") else ""
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
        return f"ExploreGeorgiaEventWebsite w/ URL: {self.url}"