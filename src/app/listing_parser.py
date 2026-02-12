from bs4 import BeautifulSoup
from urllib.parse import urljoin
from app.utils import clean_text
from app.config import BASE_URL

def parse_listing_cards(html: str):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".card")
    return soup, cards

def extract_event_from_card(card):
    title_el = card.select_one(".card__heading a")
    date_el = card.select_one(".card__date-heading")
    address_el = card.select_one(".card__address")
    phone_el = card.select_one(".card__phone a")
    website_el = card.select_one(".card__website a")

    event_link = ""
    if title_el and title_el.get("href"):
        event_link = urljoin(BASE_URL, title_el["href"])

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
    }
