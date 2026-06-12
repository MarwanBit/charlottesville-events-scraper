"""
The Front Porch — concerts listing at https://frontporchcville.org/concerts/

The public page embeds the Afton listing in a **cross-origin** iframe
(``embed-list.aftontickets.com``), so scraping the WordPress URL cannot see event nodes.
The scraper loads the embed app directly: ``/events/{apiKey}?v=…`` in a browser-capable client,
then parses ``.event-listing__card`` tiles. Optional env ``FRONTPORCH_AFTON_API_KEY`` overrides
the default key if the site rotates it.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from .base import EventsWebsite
from ..utils import clean_text

# Listing tiles (Afton embedded widget hydrates after ``widget.js``).
_CARD = "div.event-listing__card"
# ``querySelector`` uses the first match; commas = any of these signals the widget has mounted.
_WAIT_FOR_LISTING = (
    "div.event-listing__card, .event-listing__card, "
    "button.event-listing__button[data-event-id], .event-listing__button[data-event-id]"
)

# outerHTML omits shadow-root trees; Afton embed often paints cards inside shadow DOM.
# Evaluate in-browser: gather ``.event-listing__card`` from light DOM + shadow + same-origin iframes.
_SNAPSHOT_HTML_EVAL = """
(() => {
    const sel = '.event-listing__card';
    const parts = [];
    function collectFromRoot(root) {
        if (!root || !root.querySelectorAll) return;
        root.querySelectorAll(sel).forEach((el) => parts.push(el.outerHTML));
        root.querySelectorAll('*').forEach((el) => {
            if (el.shadowRoot) collectFromRoot(el.shadowRoot);
        });
    }
    function collectAnywhere(doc) {
        collectFromRoot(doc);
        const ifr = doc.querySelectorAll('iframe');
        for (let i = 0; i < ifr.length; i++) {
            try {
                const d = ifr[i].contentDocument;
                if (d) collectAnywhere(d);
            } catch (e) {}
        }
    }
    collectAnywhere(document);
    if (parts.length === 0) {
        return document.documentElement.outerHTML;
    }
    return '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
        + '<div id="fp-scraped-root">' + parts.join('') + '</div></body></html>';
})()
"""

# WordPress page embeds this URL in an iframe; parent DOM cannot read cross-origin iframe content.
# Bundle ``widget.js`` builds: https://embed-list.aftontickets.com/events/{apiKey}?v={version}&…
AFTON_EMBED_LIST_HOST = "https://embed-list.aftontickets.com"
# Version string shipped in widget.js (``?v=``); update if Afton changes the bundle.
AFTON_EMBED_LIST_VERSION = "18043271724-f9176"
# Default apiKey from ``_aft('init', { apiKey: '…' })`` on the concerts page (override with FRONTPORCH_AFTON_API_KEY).
_FRONTPORCH_AFTON_API_KEY_DEFAULT = "74c19ab0d055fb26fc24ee69336e5a1f"


def _afton_api_key_from_html(html: str) -> Optional[str]:
    m = re.search(r"apiKey\s*:\s*['\"]([a-f0-9]{32})['\"]", html, re.I)
    return m.group(1) if m else None


def _embed_list_events_url(api_key: str) -> str:
    return f"{AFTON_EMBED_LIST_HOST}/events/{api_key}?v={AFTON_EMBED_LIST_VERSION}"


def _parse_card_date_range(date_text: str) -> tuple[str | None, str | None]:
    """
    ``Tue Mar 31  - Sat Oct 17 2026`` → ISO start_date, end_date (same year as end when start omits year).
    """
    raw = clean_text(date_text)
    if not raw:
        return None, None
    parts = [p.strip() for p in re.split(r"\s*-\s*", raw, maxsplit=1)]
    if len(parts) != 2:
        return None, None
    left, right = parts
    try:
        end_dt = datetime.strptime(right, "%a %b %d %Y")
    except ValueError:
        return None, None
    year = end_dt.year
    try:
        start_dt = datetime.strptime(f"{left} {year}", "%a %b %d %Y")
    except ValueError:
        return None, None
    if start_dt.date() > end_dt.date():
        try:
            start_dt = datetime.strptime(f"{left} {year - 1}", "%a %b %d %Y")
        except ValueError:
            return None, None
    return start_dt.date().isoformat(), end_dt.date().isoformat()


class FrontPorchvilleWebsite(EventsWebsite):
    """Listing: ``/concerts/`` — cards ``.event-listing__card``."""

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = "https://frontporchcville.org"
        self.BASE_EVENTS_URL = self.BASE_URL + "/concerts/"

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        if self.soup:
            return
        from ..http_client import HybridClient, NoDriverClient

        session = getattr(client, "session", client) if client else requests.Session()
        if "User-Agent" not in getattr(session, "headers", {}):
            session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    )
                }
            )
        try:
            api_key = (os.environ.get("FRONTPORCH_AFTON_API_KEY") or "").strip()
            if not api_key:
                api_key = _FRONTPORCH_AFTON_API_KEY_DEFAULT
            try:
                probe = session.get(self.BASE_EVENTS_URL, timeout=25)
                if probe.ok:
                    k = _afton_api_key_from_html(probe.text)
                    if k:
                        api_key = k
            except requests.RequestException:
                pass
            listing_fetch_url = _embed_list_events_url(api_key)
            if isinstance(client, (HybridClient, NoDriverClient)):
                response = client.get(
                    listing_fetch_url,
                    timeout=120,
                    wait_for_selector=_WAIT_FOR_LISTING,
                    wait_for_timeout=60,
                    scroll_load_max_rounds=12,
                    scroll_load_pause_sec=0.75,
                    scroll_load_growth_selector=_CARD,
                    snapshot_html_eval=_SNAPSHOT_HTML_EVAL.strip(),
                )
            else:
                response = session.get(listing_fetch_url, timeout=25)
            print(
                f"[{type(self).__name__}] GET {listing_fetch_url} -> {response.status_code}",
                flush=True,
            )
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "unknown"
            print(
                f"[{type(self).__name__}] HTTP ERROR GET {self.url} -> {code}: {e}",
                flush=True,
            )
            self.soup = None
        except requests.RequestException as e:
            print(f"[{type(self).__name__}] GET {self.url} -> {e}", flush=True)
            self.soup = None

    def parse_listing_cards(self, client: Optional[requests.Session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        return self.soup.select(_CARD)

    def extract_event_from_card(self, card: Tag) -> dict:
        """Minimal row for compatibility; full fields built in ``get_events``."""
        return {
            "event_link": self._event_link_from_card(card),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def _event_link_from_card(self, card: Tag) -> str:
        for a in card.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#"):
                continue
            abs_url = urljoin(self.BASE_URL + "/", href)
            p = urlparse(abs_url)
            if "frontporchcville.org" not in (p.netloc or ""):
                continue
            path = (p.path or "").rstrip("/")
            if path.startswith("/concerts") and path not in ("/concerts", ""):
                return abs_url.split("#")[0]
        for el in card.select("[data-event-id]"):
            eid = (el.get("data-event-id") or "").strip()
            if eid:
                return f"{self.BASE_URL.rstrip('/')}/concerts/#evt-{eid}"
        # Ticket/checkout links are often the only stable per-event URL in the tile.
        for a in card.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#"):
                continue
            abs_url = urljoin(self.BASE_URL + "/", href)
            if urlparse(abs_url).netloc:
                return abs_url.split("#")[0]
        return ""

    def _card_to_event(self, card: Tag, scraped_at: str) -> dict | None:
        title_el = (
            card.select_one(".event-listing__card-head .description_wrapper")
            or card.select_one(".event-listing__card-head .description-wrapper")
            or card.select_one(".description_wrapper")
            or card.select_one(".description-wrapper")
            or card.select_one(".event-listing__card-head")
            or card.select_one("h2.event-listing__card-head")
        )
        title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""

        img_el = card.select_one(".event-listing__card-image img")
        image_url = ""
        if img_el:
            image_url = (img_el.get("src") or img_el.get("data-src") or "").strip()
            if image_url:
                image_url = urljoin(self.BASE_URL + "/", image_url)

        ps = [clean_text(p.get_text(" ", strip=True)) for p in card.select(".event-listing__card-item p")]
        ps = [x for x in ps if x]
        date_text = ps[0] if ps else ""
        venue = ps[1] if len(ps) > 1 else ""
        location_line = ps[2] if len(ps) > 2 else ""

        start_date, end_date = _parse_card_date_range(date_text)
        event_link = self._event_link_from_card(card)
        if not event_link or not title:
            return None

        desc_parts = [title]
        if date_text:
            desc_parts.append(date_text)
        if venue:
            desc_parts.append(venue)
        if location_line:
            desc_parts.append(location_line)
        description = ". ".join(desc_parts)

        return {
            "event_link": event_link,
            "scraped_at": scraped_at,
            "title": title,
            "description": description,
            "image_url": image_url,
            "start_date": start_date or "",
            "end_date": end_date or "",
            "start_time": "",
            "end_time": "",
            "address": location_line,
            "organizer": venue,
            "contact": venue,
            "phone": "",
            "website": self.BASE_URL,
            "email": "",
            "latitude": None,
            "longitude": None,
            "cost": None,
        }

    def get_events(self, client: Optional[requests.Session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        scraped_at = datetime.now(timezone.utc).isoformat()
        out: list[dict] = []
        for card in self.parse_listing_cards(client):
            row = self._card_to_event(card, scraped_at)
            if row:
                out.append(row)
        return out

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        """Enqueue additional listing pages only (event rows come from ``get_events``)."""
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        res: set[str] = set()

        link = self.soup.select_one('link[rel="next"][href]')
        if link and link.get("href"):
            res.add(urljoin(self.BASE_URL + "/", link["href"].strip()))

        for a in self.soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            abs_url = urljoin(self.BASE_URL + "/", href)
            p = urlparse(abs_url)
            if "frontporchcville.org" not in (p.netloc or ""):
                continue
            path = (p.path or "").rstrip("/")
            if not path.startswith("/concerts"):
                continue
            if path.rstrip("/") == "/concerts" and not (p.query or ""):
                continue
            if "/concerts/page/" in path or "paged=" in (p.query or "") or "page=" in (p.query or ""):
                res.add(abs_url.split("#")[0])
            if a.get("rel") and "next" in a.get("rel", []):
                res.add(abs_url.split("#")[0])

        res.discard(self.url.split("#")[0])
        return list(res)

    def __str__(self) -> str:
        return f"{type(self).__name__} w/ URL: {self.url}"
