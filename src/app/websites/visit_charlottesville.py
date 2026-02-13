from .base import EventsWebsite
from ..utils import clean_text
from typing import Optional
import requests
from bs4 import Tag
from urllib.parse import urljoin
from datetime import datetime, timezone

import json
import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from src.app.utils import clean_text


def get_image_url(soup: BeautifulSoup, base_url):
    div = soup.select_one(".background-image")
    if not div:
        return ""

    style = div.get("style", "")
    if "url(" in style:
        url = style.split("url(")[1].split(")")[0].strip("\"'")
        return urljoin(base_url, url)

    bgset = div.get("data-bgset", "")
    if bgset:
        return urljoin(base_url, bgset.split(",")[-1].split()[0])

    return ""


def extract_contact_info(soup):
    organizer = ""
    for li in soup.select("ul.detail__info li"):
        text = li.get_text(" ", strip=True)
        if text.lower().startswith("contact:"):
            organizer = text.split(":", 1)[1].strip()
    return organizer


def parse_jsonld_event(soup: BeautifulSoup):
    el = soup.select_one("script[type='application/ld+json']")
    if not el or not el.string:
        return {}
    try:
        data = json.loads(el.string)
        if isinstance(data, list):
            data = data[0] if data else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_subheading_to_dates_times(soup: BeautifulSoup):
    el = soup.select_one("p.page-title__subheading")
    if not el:
        return "", "", "", ""

    text = clean_text(el.get_text(" ", strip=True))
    time_match = re.search(r"(\d{1,2}:\d{2}\s*[AP]M)\s+to\s+(\d{1,2}:\d{2}\s*[AP]M)", text, re.IGNORECASE)

    start_time_24 = ""
    end_time_24 = ""
    if time_match:
        t1, t2 = time_match.groups()
        start_time_24 = datetime.strptime(t1.replace(" ", ""), "%I:%M%p").strftime("%H:%M")
        end_time_24 = datetime.strptime(t2.replace(" ", ""), "%I:%M%p").strftime("%H:%M")

    range_match = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s+to\s+([A-Za-z]+)\s+(\d{1,2})", text, re.IGNORECASE)
    single_match = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?!\s+to\s+[A-Za-z]+)", text, re.IGNORECASE)

    year = datetime.now().year

    if range_match:
        sm, sd, em, ed = range_match.groups()
        start_date_dt = datetime.strptime(f"{sm} {sd} {year}", "%B %d %Y")
        end_date_dt = datetime.strptime(f"{em} {ed} {year}", "%B %d %Y")
        if end_date_dt < start_date_dt:
            end_date_dt = end_date_dt.replace(year=year + 1)
        return start_date_dt.strftime("%Y-%m-%d"), end_date_dt.strftime("%Y-%m-%d"), start_time_24, end_time_24

    if single_match:
        m, d = single_match.groups()
        start_date_dt = datetime.strptime(f"{m} {d} {year}", "%B %d %Y")
        sd = start_date_dt.strftime("%Y-%m-%d")
        return sd, sd, start_time_24, end_time_24

    return "", "", "", ""


def scrape_event_detail(session, event_url: str) -> dict:
    resp = session.get(event_url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    def pick_text(selectors):
        for sel in selectors:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return clean_text(el.get_text(" ", strip=True))
        return ""

    description = pick_text([".text__text"])
    image_url = get_image_url(soup, event_url)
    organizer = extract_contact_info(soup)

    start_date = end_date = start_time = end_time = ""
    ld = parse_jsonld_event(soup)

    if ld:
        sd = ld.get("startDate", "") or ""
        ed = ld.get("endDate", "") or ""

        if sd:
            start_date = sd[:10] if len(sd) >= 10 else ""
            if "T" in sd:
                start_time = sd.split("T", 1)[1][:5]
        if ed:
            end_date = ed[:10] if len(ed) >= 10 else ""
            if "T" in ed:
                end_time = ed.split("T", 1)[1][:5]

        if not description and isinstance(ld.get("description"), str):
            description = clean_text(ld["description"])

        if not image_url:
            img = ld.get("image")
            if isinstance(img, str):
                image_url = urljoin(event_url, img)
            elif isinstance(img, list) and img and isinstance(img[0], str):
                image_url = urljoin(event_url, img[0])

    if not start_date or not end_date:
        sd2, ed2, st2, et2 = parse_subheading_to_dates_times(soup)
        start_date = start_date or sd2
        end_date = end_date or ed2
        start_time = start_time or st2
        end_time = end_time or et2

    return {
        "description": description,
        "image_url": image_url,
        "organizer": organizer,
        "start_date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
    }




class VisitCharlottesvilleWebsite(EventsWebsite):

    def parse_listing_cards(self, client: Optional[requests.Session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        cards = self.soup.select(".card")
        return cards

    def extract_event_from_card(self, card: Tag) -> list[dict]:
        title_el = card.select_one(".card__heading a")
        date_el = card.select_one(".card__date-heading")
        address_el = card.select_one(".card__address")
        phone_el = card.select_one(".card__phone a")
        website_el = card.select_one(".card__website a")

        event_link = ""
        if title_el and title_el.get("href"):
            event_link = urljoin("https://www.visitcharlottesville.org/events/", title_el["href"])

        title = clean_text(title_el.get_text()) if title_el else ""
        date = clean_text(date_el.get_text()) if date_el else ""
        address = clean_text(address_el.get_text()) if address_el else ""
        phone = clean_text(phone_el.get_text()) if phone_el else ""
        website = urljoin(event_link, website_el.get("href", "")) if website_el else ""

        return {
            "event_link": event_link,
            "title": title,
            "date": date,
            "address": address,
            "phone": phone,
            "website": website,
            "scraped_at": datetime.now(timezone.utc).isoformat()
        }
    
    def get_events(self, client: Optional[requests.Session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        cards = self.parse_listing_cards(client)
        res = []
        for card in cards:
            res.append(self.extract_event_from_card(card))
        return res

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            raise RuntimeError(f"Failed to load page: {self.url}")

        # get link to next page
        res = set[str]()
        next_link = self.soup.find('a', attrs={'aria-label': 'Next Page'})
        if next_link and 'href' in next_link.attrs:
            next_url = next_link['href']
            if next_url not in res:
                res.add(next_url)

        # now get links to details page
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            res.add(event_link)
        return list[str](res)

    def __str__(self) -> str:
        return f"VisitCharlottesvilleWebsite w/ URL: {self.url}"


class VisitCharlottesvilleEventWebsite(EventsWebsite):

    def get_events(self, client: Optional[requests.Session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)

        def pick_text(selectors):
            for sel in selectors:
                el = self.soup.select_one(sel)
                if el and el.get_text(strip=True):
                    return clean_text(el.get_text(" ", strip=True))
            return ""

        description = pick_text([".text__text"])
        image_url = get_image_url(self.soup, self.url)
        organizer = extract_contact_info(self.soup)

        start_date = end_date = start_time = end_time = ""
        ld = parse_jsonld_event(self.soup)

        if ld:
            sd = ld.get("startDate", "") or ""
            ed = ld.get("endDate", "") or ""

            if sd:
                start_date = sd[:10] if len(sd) >= 10 else ""
                if "T" in sd:
                    start_time = sd.split("T", 1)[1][:5]
            if ed:
                end_date = ed[:10] if len(ed) >= 10 else ""
                if "T" in ed:
                    end_time = ed.split("T", 1)[1][:5]

            if not description and isinstance(ld.get("description"), str):
                description = clean_text(ld["description"])

            if not image_url:
                img = ld.get("image")
                if isinstance(img, str):
                    image_url = urljoin(self.url, img)
                elif isinstance(img, list) and img and isinstance(img[0], str):
                    image_url = urljoin(self.url, img[0])

        if not start_date or not end_date:
            sd2, ed2, st2, et2 = parse_subheading_to_dates_times(self.soup)
            start_date = start_date or sd2
            end_date = end_date or ed2
            start_time = start_time or st2
            end_time = end_time or et2

        return [{
            "event_link": self.url,
            "description": description,
            "image_url": image_url,
            "organizer": organizer,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
        }]

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return [] 

    def __str__(self) -> str:
        return f"VisitCharlottesvilleEventWebsite w/ URL: {self.url}"