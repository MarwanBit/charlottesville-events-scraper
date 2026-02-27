import re
import requests
from bs4 import BeautifulSoup, Tag
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from .base import EventsWebsite
from ..utils import clean_text

from datetime import datetime
import re

def parse_time_range(time_str: Optional[str], date=None) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Converts a time range string like '10:00 AM – 5:00 PM'
    into two datetime objects (start, end). Returns (None, None) for empty or unparseable input.

    Args:
        time_str (str): time range string
        date (datetime.date, optional): date to attach (defaults to today)

    Returns:
        (datetime, datetime) or (None, None): start_time, end_time
    """
    if not time_str or not time_str.strip():
        return None, None
    if date is None:
        date = datetime.today().date()

    # Split on en dash or hyphen
    parts = [t.strip() for t in re.split(r"\s*[–-]\s*", time_str)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None, None
    start_str, end_str = parts[0], parts[1]

    try:
        start_time = datetime.strptime(start_str, "%I:%M %p").time()
        end_time = datetime.strptime(end_str, "%I:%M %p").time()
    except ValueError:
        return None, None

    # Combine with date
    start_dt = datetime.combine(date, start_time)
    end_dt = datetime.combine(date, end_time)

    return start_dt, end_dt

# aria-label format: "From Feb 22, 2026 to Mar 13, 2026"
_DATE_LABEL_PATTERN = re.compile(r"From\s+(.+?)\s+to\s+(.+)", re.IGNORECASE)
_DATE_FMT = "%b %d, %Y"  # e.g. Feb 22, 2026


def _parse_date_range_from_aria_label(aria_label: str | None) -> tuple[Optional[str], Optional[str]]:
    if not aria_label or not aria_label.strip():
        return None, None
    m = _DATE_LABEL_PATTERN.match(aria_label.strip())
    if not m:
        return None, None
    start_str, end_str = m.group(1).strip(), m.group(2).strip()
    try:
        start_dt = datetime.strptime(start_str, _DATE_FMT)
        end_dt = datetime.strptime(end_str, _DATE_FMT)
        return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
    except ValueError:
        return None, None


class TexasTimeTravelWebsite(EventsWebsite):

    def __init__(self, url, soup: [BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = 'https://texastimetravel.com'
        self.BASE_EVENTS_URL = self.BASE_URL + '/events'

    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.soup.select("article.card.card--listing")
        return cards

    def extract_event_from_card(self, card: Tag) -> list[dict]:

        event_link_el = card.select_one('a.card__link')
        title_el = card.select_one('h1.card__heading.heading a')
        phone_el = card.select_one('span.card__phone a')
        website_el = card.select_one('span.card__website a')
        address_spans = card.select("span.card__address")
        address_el = address_spans[1] if len(address_spans) > 1 else (address_spans[0] if address_spans else None)
        image_el = card.select_one('img')
        date_el = card.select_one(".cal-date")

        event_link = clean_text(event_link_el.get('href')) if event_link_el and event_link_el.get('href') else ""
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""
        start_date, end_date = _parse_date_range_from_aria_label(
            date_el.get("aria-label") if date_el else None
        )
        start_time = None
        end_time = None
        address = " ".join(span.get_text(strip=True) for span in address_el.find_all("span")) if address_el else ""
        phone = clean_text(phone_el.get_text(strip=True)) if phone_el else ""
        website = clean_text(website_el.get('href')) if website_el and website_el.get('href') else ""
        image_url = ""
        if image_el:
            candidates = []
            for attr in ("data-src", "data-srcset", "srcset"):
                val = image_el.get(attr)
                if val and val.strip():
                    for part in val.split(","):
                        url = part.strip().split(None, 1)[0].strip()
                        if url:
                            candidates.append(url)
            for source in card.select("picture source[srcset], picture source[data-srcset]"):
                for attr in ("srcset", "data-srcset"):
                    val = source.get(attr)
                    if val and val.strip():
                        for part in val.split(","):
                            url = part.strip().split(None, 1)[0].strip()
                            if url:
                                candidates.append(url)
            src_fallback = image_el.get("src")
            if src_fallback and src_fallback.strip():
                candidates.append(src_fallback.strip())
            for raw in candidates:
                if raw.lower().startswith("data:"):
                    continue
                image_url = raw if raw.startswith("http") else (self.BASE_URL.rstrip("/") + "/" + raw.lstrip("/"))
                image_url = clean_text(image_url)
                break

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
        link_el = self.soup.select_one("li.pagination__item.pagination__item--next a")
        if link_el and link_el.get('href'):
            res.add(link_el.get('href'))
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            if event_link not in res:
                res.add(event_link) 
        return list[str](res)

    def __str__(self):
        return f"TexasTimeTravelWebsite w/ URL: {self.url}"


class TexasTimeTravelEventWebsite(EventsWebsite):

    def __init__(self, url, soup: [BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = 'https://texastimetravel.com'
        self.BASE_EVENTS_URL = self.BASE_URL + '/events'

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        # Get the address
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        description_el = self.soup.select_one('.detail__summary')
        time_el = self.soup.select_one('.detail__time')

        description = clean_text(description_el.get_text(" ", strip=True)) if description_el else ""
        time = clean_text(time_el.get_text(strip=True)) if time_el else ""
        start_time, end_time = parse_time_range(time)
        
        return [{
            "event_link": self.url,
            "description": description,
            'start_time': start_time,
            'end_time': end_time,
            "scraped_at":  datetime.now(timezone.utc).isoformat(),
        }]

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"TexasTimeTravelEventWebsite w/ URL: {self.url}"