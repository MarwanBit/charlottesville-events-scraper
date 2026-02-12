from bs4 import BeautifulSoup
from urllib.parse import urljoin

def extract_event_links(listing_html: str, base_url: str = "https://www.visitcharlottesville.org/"):
    soup = BeautifulSoup(listing_html, "html.parser")

    links = []
    for a in soup.select("a"):  # we'll refine selector later if you want
        href = a.get("href") or ""
        if "/event/" in href or "/events/" in href:
            links.append(urljoin(base_url, href))

    # Deduplicate
    return sorted(set(links))
