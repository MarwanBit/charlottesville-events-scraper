from .base import EventsWebsite
from typing import Optional
import requests
from bs4 import Tag, BeautifulSoup
from datetime import datetime, timezone
from ..utils import clean_text
import dateparser

import re

def extract_datetime_range(text, reference_date=None):
    """
    Extract start_date, end_date, start_time, end_time from messy strings like:
    - "Sep 13, 2026. 8 p.m." (single date, single time)
    - "Sundays, Mondays, ... , Now - Mar 09, 2026. 11 AM - 4 PM"
    - "3rd Thursdays, Now - Dec 17, 2026. 6 p.m. to 7 p.m."

    Ignores recurrence info and returns a dict with datetime.date/datetime and datetime.time objects.
    """
    if reference_date is None:
        reference_date = datetime.now()
    ref_date = reference_date.date() if hasattr(reference_date, 'date') else reference_date

    # Step 1: Separate date part from time part. Time part is at the end and looks like "8 p.m." or "6 p.m. to 7 p.m."
    # When there's no numeric time (e.g. "Jul 11, 2026. Evening" or "Jun 26, 2026. TBA"), split on last ". " and parse the date part only.
    time_suffix = re.search(
        r'\d{1,2}(:\d{2})?\s*(?:a\.m\.|p\.m\.|AM|PM)(?:\s*(?:to|-)\s*\d{1,2}(:\d{2})?\s*(?:a\.m\.|p\.m\.|AM|PM))?\s*$',
        text,
        re.IGNORECASE
    )
    if time_suffix:
        date_text = text[:time_suffix.start()].strip().rstrip('.').strip()
        # Strip trailing non-date words (e.g. "Starting" in "May 10, 2026. Starting")
        date_text = re.sub(r'\.\s*(?:Starting|Through|Until)\s*$', '', date_text, flags=re.IGNORECASE).strip().rstrip('.').strip()
        time_text = time_suffix.group(0).strip()
    else:
        # No numeric time suffix (e.g. "Jul 11, 2026. Evening" or "Jun 26, 2026. TBA") — take text before last ". " as date part
        if '. ' in text:
            date_text = text.rsplit('. ', 1)[0].strip()
        else:
            date_text = text.strip()
        time_text = ''

    # Step 2: Parse time part (range "X to Y" / "X - Y" or single "8 p.m.")
    time_range_match = re.search(
        r'(\d{1,2}(:\d{2})?\s*(a\.m\.|p\.m\.|AM|PM))\s*(?:to|-)\s*(\d{1,2}(:\d{2})?\s*(a\.m\.|p\.m\.|AM|PM))',
        time_text,
        re.IGNORECASE
    )
    single_time_match = re.search(
        r'(\d{1,2}(:\d{2})?\s*(a\.m\.|p\.m\.|AM|PM))',
        time_text,
        re.IGNORECASE
    )

    start_time = end_time = None
    if time_range_match:
        start_time = dateparser.parse(time_range_match.group(1), settings={'RELATIVE_BASE': reference_date}).time()
        end_time = dateparser.parse(time_range_match.group(4), settings={'RELATIVE_BASE': reference_date}).time()
    elif single_time_match:
        start_time = dateparser.parse(single_time_match.group(1), settings={'RELATIVE_BASE': reference_date}).time()

    # Step 3: Parse date part. If it contains a range (" - "), take segment after last comma for left side.
    date_seps = [' - ', '–', '—']
    date_parts = None
    for sep in date_seps:
        if sep in date_text:
            date_parts = date_text.split(sep, 1)
            break
    if date_parts is None:
        date_parts = [date_text]

    # When we have "Recurrence, Now - Mar 09, 2026", left is "Recurrence, Now", right is "Mar 09, 2026"
    # When we have "Sep 13, 2026" (no range), date_parts[0] is the full string
    start_str = date_parts[0].strip()
    if len(date_parts) > 1 and ',' in start_str:
        start_str = start_str.split(',')[-1].strip()
    if start_str.lower() == 'now':
        start_date = ref_date
    else:
        start_parsed = dateparser.parse(start_str, settings={'RELATIVE_BASE': reference_date})
        start_date = start_parsed.date() if start_parsed else None

    if len(date_parts) > 1:
        end_str = date_parts[1].strip()
        end_parsed = dateparser.parse(end_str, settings={'RELATIVE_BASE': reference_date})
        end_date = end_parsed.date() if end_parsed else None
    else:
        end_date = None

    return {
        'start_date': start_date,
        'end_date': end_date,
        'start_time': start_time,
        'end_time': end_time
    }



class WashingtonWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://washington.org"
        self.BASE_EVENTS_URL = self.BASE_URL + "/find-dc-listings/events"


    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        cards = self.soup.select(".dcevent-wrapper")
        return cards
        
    def extract_event_from_card(self, card: Tag) -> list[dict]:
        event_link_el = card.select_one("a.btn.btn--primary")
        title_el = card.select_one("h6.label")
        date_el = card.select_one("p.date")

        event_link = self.BASE_URL + event_link_el["href"] if event_link_el and event_link_el.get("href") else ""
        title = clean_text(title_el.get_text()) if title_el else ""
        date = clean_text(date_el.get_text()) if date_el else ""

        address = None
        phone = None
        website = None

        return {
            "event_link": event_link,
            "title": title,
            "date": date,
            "address": None,
            "phone": None,
            "website": None,
            "scraped_at": datetime.now(timezone.utc).isoformat()

        }

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        cards = self.parse_listing_cards(client)
        res = []
        for card in cards:
            res.append(self.extract_event_from_card(card))
        return res

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        res = set[str]()
        # This gets the next page
        link = self.soup.find("a", class_="pager__link--next")
        next_el = self.soup.find("a", class_="pager__link--next")
        if next_el and next_el.get("href"):
            link = next_el["href"]
            if link not in res:
                res.add(self.BASE_EVENTS_URL + link)
        # Now we need to get the links for each of the cards
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            res.add(event_link)
        return list[str](res)

    def __str__(self) -> str:
        return f"WashingtonWebsite w/ URL: {self.url}"


class WashingtonEventWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://washington.org"

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            raise RuntimeError(f"Failed to load page: {self.url}")

        description_el = self.soup.select_one("div.businessdetail--body")
        address_el = self.soup.select_one("p.address")
        img_el = self.soup.select_one("img.image")
        date_el = self.soup.select_one("div.deal-validity")
        organizer_el = self.soup.select_one("h5.label a")
        website_el = self.soup.select_one("div.connectblock-visit a")
        phone_el = self.soup.find("div", class_="contactblock-phone")
        phone_el = phone_el.find("h6") if phone_el else None

        description = clean_text(description_el.get_text()) if description_el else ""
        image_url = self.BASE_URL + img_el["src"] if img_el and img_el.has_attr("src") else ""
        organizer = clean_text(organizer_el.get_text(strip=True)) if organizer_el else ""
        website = clean_text(website_el.get("href")) if website_el.get("href") else ""
        phone = clean_text(phone_el.get_text(strip=True)) if phone_el else ""

        start_date = None
        end_date = None
        start_time = None
        end_time = None

        date_text = date_el.get_text(strip=True) if date_el else ""
        dt = extract_datetime_range(date_text)
        start_date = dt.get("start_date")
        end_date = dt.get("end_date")
        start_time = dt.get("start_time")
        end_time = dt.get("end_time")

        address = clean_text(address_el.get_text()) if address_el else ""

        return [{
            "event_link": self.url,
            "description": description,
            "image_url": image_url,
            "organizer": organizer,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "address": address,
            "scraped_at":  datetime.now(timezone.utc).isoformat(),
            "website": website,
            "phone": phone
        }]

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    def __str__(self) -> str:
        return f"WashingtonEventWebsite w/ URL: {self.url}"