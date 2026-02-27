from .base import EventsWebsite
from typing import Optional
import requests
from bs4 import Tag, BeautifulSoup
from datetime import datetime, timezone, timedelta, date, time
from ..utils import clean_text
import re

def extract_datetime_range(
    text: str,
    reference_date: Optional[datetime] = None,
) -> list[tuple[date | None, date | None, time | None, time | None]]:
    """
    Extract start_date, end_date, start_time, end_time from messy strings like:
    - "Sep 13, 2026. 8 p.m." (single date, single time)
    - "Sundays, Mondays, ... , Now - Mar 09, 2026. 11 AM - 4 PM"
    - "3rd Thursdays, Now - Dec 17, 2026. 6 p.m. to 7 p.m."

    Ignores recurrence info and returns a list of tuples:
    [(start_date, end_date, start_time, end_time), ...]
    where each tuple represents one day, and start_date == end_date for that day.
    """
    if reference_date is None:
        reference_date = datetime.now()
    ref_date = reference_date.date() if hasattr(reference_date, "date") else reference_date

    import dateparser  # Lazy import: dateparser/regex are slow to load

    # Step 1: Separate date part from time part. Time part is at the end and looks like "8 p.m." or "6 p.m. to 7 p.m."
    # When there's no numeric time (e.g. "Jul 11, 2026. Evening" or "Jun 26, 2026. TBA"), split on last ". " and parse the date part only.
    time_suffix = re.search(
        r'\d{1,2}(:\d{2})?\s*(?:a\.m\.|p\.m\.|AM|PM)(?:\s*(?:to|-)\s*\d{1,2}(:\d{2})?\s*(?:a\.m\.|p\.m\.|AM|PM))?\s*$',
        text,
        re.IGNORECASE
    )
    if time_suffix:
        date_text = text[:time_suffix.start()].strip().rstrip(".").strip()
        # Strip trailing non-date words after a period, e.g.:
        # "May 10, 2026. Starting", "Apr 19, 2026. From:", "Now - Feb 27, 2026. Starting:"
        date_text = re.sub(
            r"\.\s*(?:Starting|Through|Until|From|Step[- ]off Time)\s*:?\s*$",
            "",
            date_text,
            flags=re.IGNORECASE,
        ).strip().rstrip(".").strip()
        time_text = time_suffix.group(0).strip()
    else:
        # No numeric time suffix (e.g. "Jul 11, 2026. Evening" or "Jun 26, 2026. TBA") — take text before last ". " as date part
        if '. ' in text:
            date_text = text.rsplit('. ', 1)[0].strip()
        else:
            date_text = text.strip()
        time_text = ''

    # Step 2: Parse time part (range "X to Y" / "X - Y" / "X & Y" or single "8 p.m.")
    time_range_match = re.search(
        r'(\d{1,2}(:\d{2})?\s*(a\.m\.|p\.m\.|AM|PM))\s*(?:to|-|&)\s*(\d{1,2}(:\d{2})?\s*(a\.m\.|p\.m\.|AM|PM))',
        time_text,
        re.IGNORECASE,
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
    # When we have "Daily, Jun 12, 2026 - Jun 14, 2026", left is "Daily, Jun 12, 2026"
    # When we have "Sundays, Fridays, Saturdays, Now - Oct 08, 2027", left is "Sundays, Fridays, Saturdays, Now"
    # When we have "Sep 13, 2026" (no range), date_parts[0] is the full string.
    start_str_raw = date_parts[0].strip()

    # Detect specific weekdays mentioned in any recurrence prefix so we can filter
    # the expanded range down to those days only.
    weekday_names = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    recurrence_days: set[int] = set()
    tokens = [part.strip() for part in start_str_raw.split(",") if part.strip()]
    for tok in tokens:
        base = tok.lower().rstrip("s")  # handle "Sundays" -> "sunday"
        if base in weekday_names:
            recurrence_days.add(weekday_names[base])

    start_str = start_str_raw
    lower_tokens = {t.lower() for t in tokens}
    if "now" in lower_tokens:
        # For any pattern ending with "Now" (e.g. "Recurrence, Now")
        start_str = "Now"
    else:
        # Prefer an explicit "Month DD, YYYY" anywhere in the left-hand side.
        date_match = re.search(r"[A-Za-z]+\s+\d{1,2},\s*\d{4}", start_str_raw)
        if date_match:
            start_str = date_match.group(0).strip()
        elif len(date_parts) > 1 and start_str.count(",") >= 2:
            # Fallback: drop the first comma-separated segment, keeping the date portion.
            # E.g. "Daily, Jun 12, 2026" -> "Jun 12, 2026"
            start_str = start_str.split(",", 1)[1].strip()
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

    # Convert to list-of-tuples form. Ensure we always have some date
    # value equality (possibly None) and expand ranges into per-day tuples.
    if start_date is None and end_date is None:
        return [(None, None, start_time, end_time)]

    if start_date is None:
        start_date = end_date
    if end_date is None:
        end_date = start_date

    result: list[tuple[date, date, time | None, time | None]] = []
    current = start_date
    count = 0
    while current <= end_date:
        # If specific weekdays were mentioned (e.g. Sundays, Fridays, Saturdays),
        # only include those days; otherwise, include every day in the range.
        if not recurrence_days or current.weekday() in recurrence_days:
            result.append((current, current, start_time, end_time))
            count += 1
        current = current + timedelta(days=1)
    # Lightweight debug to catch very large expansions.
    if count > 200:
        print(
            f"[Washington extract_datetime_range] expanded '{text[:80]}...' "
            f"into {count} day-level entries "
            f"(start_date={start_date}, end_date={end_date}, recurrence_days={sorted(recurrence_days)})",
            flush=True,
        )
    return result



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
        event_link = self.BASE_URL + event_link_el["href"] if event_link_el and event_link_el.get("href") else ""

        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat()

        }

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
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
        title_el = self.soup.select_one('[aria-label="Heading"]')
        address_el = self.soup.select_one("p.address")
        img_el = self.soup.select_one("img.image")
        date_el = self.soup.select_one("div.deal-validity")
        organizer_el = self.soup.select_one("h5.label a")
        website_el = self.soup.select_one("div.connectblock-visit a")
        phone_el = self.soup.find("div", class_="contactblock-phone")
        phone_el = phone_el.find("h6") if phone_el else None

        description = clean_text(description_el.get_text()) if description_el else ""
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""
        image_url = self.BASE_URL + img_el["src"] if img_el and img_el.has_attr("src") else ""
        organizer = clean_text(organizer_el.get_text(strip=True)) if organizer_el else ""
        website = clean_text(website_el.get("href")) if website_el and website_el.get("href") else ""
        phone = clean_text(phone_el.get_text(strip=True)) if phone_el else ""

        date_text = date_el.get_text(strip=True) if date_el else ""
        print(f"[WashingtonEventWebsite] parsing date_text='{date_text}' for {self.url}", flush=True)
        address = clean_text(address_el.get_text()) if address_el else ""
        ranges = extract_datetime_range(date_text)
        print(
            f"[WashingtonEventWebsite] extracted {len(ranges)} date/time ranges for {self.url}",
            flush=True,
        )

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
        return f"WashingtonEventWebsite w/ URL: {self.url}"