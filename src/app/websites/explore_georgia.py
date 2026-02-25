from .base import EventsWebsite
from typing import Optional
import requests
from bs4 import Tag, BeautifulSoup
from datetime import date, datetime, time, timezone, timedelta
from ..utils import clean_text
import dateparser
import re

def _normalize_for_date_parse(s: str) -> str:
    """Reduce to 'Month DD, YYYY' for strptime with %B %d, %Y. Handles 'Sunday, March 8, 202612:00am' etc."""
    s = (s or "").strip()
    # Fix missing space between year and time: 202612:00am -> 2026 12:00am
    s = re.sub(r"(\d{4})(\d)(?=:\d)", r"\1 \2", s)
    # Strip optional leading weekday (e.g. "Sunday, ")
    s = re.sub(r"^[A-Za-z]+,\s*", "", s)
    # Strip trailing time (e.g. " 12:00am")
    s = re.sub(r"\s+\d{1,2}:\d{2}\s*(?:am|pm)\s*$", "", s, flags=re.I).strip()
    return s


def parse_date_range(text):
    """Parse e.g. 'February 25, 2026 - March 6, 2026' or 'Sunday, March 8, 202612:00am - Monday, March 9, 2026'."""
    match = re.match(r"(.+?)\s*-\s*(.+)", text)
    if not match:
        return None, None

    start_str = _normalize_for_date_parse(match.group(1))
    end_str = _normalize_for_date_parse(match.group(2))
    fmt = "%B %d, %Y"  # e.g. February 21, 2026

    try:
        start_dt = datetime.strptime(start_str, fmt)
        end_dt = datetime.strptime(end_str, fmt)
        return start_dt.date(), end_dt.date()
    except ValueError:
        return None, None


# All-day event: start at midnight, end at last second of the day
ALL_DAY_START = time(0, 0)
ALL_DAY_END = time(23, 59, 59)


def _normalize_datetime_str(s: str) -> str:
    """Prepare datetime string for strptime: fix year-time spacing and normalize am/pm."""
    s = (s or "").strip()
    # Fix missing space between year and time: 202612:00am -> 2026 12:00am, 20261:00pm -> 2026 1:00pm
    s = re.sub(r"(\d{4})(\d{1,2})(?=:\d{2})", r"\1 \2", s)
    # strptime %p is locale-dependent; normalize to uppercase AM/PM so it always matches
    s = re.sub(r"\b(am|pm)\b", lambda m: m.group(1).upper(), s, flags=re.I)
    return s


def parse_event_datetime_range(s: str) -> tuple[date | None, date | None, time | None, time | None]:
    """Parse e.g. 'Saturday, April 4, 2026 7:00pm - 9:00pm' or 'Sunday, March 8, 2026 12:00am - 1:00am'
    into start_date, end_date, start_time, end_time.
    Also supports multiple time ranges on one day (e.g. 'Wednesday, February 25, 2026 10:00am - 11:00am 3:00pm - 4:00pm'):
    we merge them into one event with earliest start and latest end.
    If there is no time component (e.g. 'Saturday, April 4, 2026'), returns all-day: start_time=00:00, end_time=23:59:59."""
    s_normalized = _normalize_datetime_str(s or "")
    if not s_normalized:
        return None, None, None, None
    if " - " in s_normalized:
        parts = s_normalized.split(" - ", 1)
        start_str = parts[0].strip()
        end_str = parts[1].strip()
        try:
            start_dt = datetime.strptime(start_str, "%A, %B %d, %Y %I:%M%p")
            end_time = datetime.strptime(end_str, "%I:%M%p").time()
            start_date = start_dt.date()
            start_time = start_dt.time()
            return start_date, start_date, start_time, end_time
        except ValueError:
            pass
    # One date + multiple time ranges (e.g. "Wednesday, February 25, 2026 10:00am - 11:00am 3:00pm - 4:00pm")
    # Merge into single event: earliest start_time, latest end_time
    time_range_pat = re.compile(
        r"(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)",
        re.IGNORECASE,
    )
    ranges = time_range_pat.findall(s_normalized)
    if ranges:
        date_prefix = time_range_pat.sub("", s_normalized).strip()
        # Trim trailing junk (e.g. extra spaces between ranges leave nothing; ranges may leave "Wednesday, February 25, 2026")
        try:
            start_date = datetime.strptime(date_prefix, "%A, %B %d, %Y").date()
        except ValueError:
            start_date = None
        if start_date is not None:
            times = []
            for start_t, end_t in ranges:
                try:
                    t0 = datetime.strptime(start_t.strip(), "%I:%M%p").time()
                    t1 = datetime.strptime(end_t.strip(), "%I:%M%p").time()
                    times.append((t0, t1))
                except ValueError:
                    continue
            if times:
                start_time = min(t[0] for t in times)
                end_time = max(t[1] for t in times)
                return start_date, start_date, start_time, end_time
    # Single date + time (e.g. "Sunday, March 8, 2026 12:00am") -> all-day that day from that time
    try:
        start_dt = datetime.strptime(s_normalized, "%A, %B %d, %Y %I:%M%p")
        return start_dt.date(), start_dt.date(), start_dt.time(), ALL_DAY_END
    except ValueError:
        pass
    # Date-only: strip trailing time if present, then parse as all-day
    s_date_only = re.sub(r"\s+\d{1,2}:\d{2}\s*(?:am|pm)\s*$", "", s_normalized, flags=re.I).strip()
    try:
        start_date = datetime.strptime(s_date_only, "%A, %B %d, %Y").date()
        return start_date, start_date, ALL_DAY_START, ALL_DAY_END
    except ValueError:
        return None, None, None, None



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
        address_el = card.select_one("div.address-venue")
        image_el = card.find("img")

        event_link = self.BASE_URL + event_link_el.get("href") if event_link_el and event_link_el.get("href") else ""
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""
        address = clean_text(address_el.get_text(strip=True)) if address_el else ""
        image_url = clean_text(image_el.get("src")) if image_el and image_el.get("src") else ""
        phone = None 
        website = None

        return {
            "event_link": event_link,
            "title": title,
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

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        description_el = self.soup.select_one("div.mmg8_listing_fields_description")
        phone_el = self.soup.select_one("a.phone-link")
        website_el = self.soup.select_one("a.website-link")
        img_el = None
        title_el = self.soup.select_one('div.group-data-node-intro h1')

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
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""

        events = []
        scraped_at = datetime.now(timezone.utc).isoformat()

        for item in self.soup.select(".month-group .date-list-item"):
            date_text = item.select_one(".month-and-day-number").get_text(strip=True)
            start_date, end_date, start_time, end_time = parse_event_datetime_range(date_text)

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
        return f"ExploreGeorgiaEventWebsite w/ URL: {self.url}"