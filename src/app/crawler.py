from bs4 import BeautifulSoup
from app.config import BASE_URL, MAX_PAGES

def iter_listing_pages(session):
    page = 1
    last_first_link = None

    while True:
        url = BASE_URL if page == 1 else f"{BASE_URL}?page={page}"
        resp = session.get(url, timeout=20)
        resp.raise_for_status()

        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".card")

        if not cards:
            break

        # detect "pagination doesn't change anymore"
        first_link_el = soup.select_one(".card__heading a")
        first_link = first_link_el.get("href") if first_link_el else None

        if first_link and first_link == last_first_link:
            # we're stuck seeing the same page again and again
            break

        last_first_link = first_link

        yield page, html, len(cards)

        if page >= MAX_PAGES:
            break

        page += 1
