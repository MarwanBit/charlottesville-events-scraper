from .base import EventsWebsite
from ..detail_scraper import get_image_url, extract_contact_info, parse_jsonld_event, parse_subheading_to_dates_times
from ..utils import clean_text
from typing import Optional, List, Dict
import requests
from bs4 import Tag
from urllib.parse import urljoin
from datetime import datetime, timezone



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

if __name__ == "__main__":
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    home_page = VisitCharlottesvilleWebsite('https://www.visitcharlottesville.org/events/')
    print(home_page.get_events(s))