from .base import EventsWebsite
from typing import Optional
from bs4 import Tag, BeautifulSoup
import requests
from datetime import datetime, timezone, timedelta
import re
from ..utils import clean_text
from typing import Optional, TYPE_CHECKING



class IndieShortFilmFestivalWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = 'https://isff2026.eventive.org'
        self.BASE_EVENTS_URL  = self.BASE_URL + "/films"

    def generate_soup(self, client: Optional[requests.session] = None) -> None:
        """
        Override to use browser client wait_for_selector so JS-rendered listing cards are present.
        Falls back to plain requests if no browser client is provided.
        """
        if self.soup:
            return

        from ..http_client import NoDriverClient, HybridClient

        session = client.session if client else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"})

        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                response = client.get(
                    self.url,
                    timeout=120,
                    wait_for_selector="a[href^='/films/'], a[href*='/films/'], a.rmq-73be53a5",
                    wait_for_timeout=45,
                )
            else:
                response = session.get(self.url, timeout=10)

            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
            print(
                f"[IndieShortFilmFestivalWebsite] generated soup for listing: {len(response.text)} chars",
                flush=True,
            )
        except requests.RequestException as e:
            print(f"[IndieShortFilmFestivalWebsite] Error fetching {self.url}: {e}", flush=True)
            self.soup = None

    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        cards_href = self.soup.select("a[href^='/films/'], a[href*='/films/']")
        cards_class = self.soup.select('a.rmq-73be53a5')

        print(
            "[IndieShortFilmFestivalWebsite] listing card counts:",
            f"a[href^='/films/']={len(cards_href)}",
            f"a.rmq-73be53a5={len(cards_class)}",
            flush=True,
        )

        cards = cards_href if cards_href else cards_class

        # Debug sample
        for c in cards[:5]:
            print("  sample listing card href:", c.get("href"), flush=True)

        return cards

    def extract_event_from_card(self, card: Tag) -> list[dict]:
        event_link = self.BASE_URL + card.get("href") if card and card.get('href') else ""
        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat()
        }

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        return []

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        res = set[str]()
        # now next page so need to get the next link!
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)['event_link']
            if event_link not in res:
                res.add(event_link)
        return list[str](res)

    def __str__(self):
        return f"IndieShortFilmFestivalWebsite w/ URL: {self.url}"

class IndieShortFilmFestivalEventWebsite(EventsWebsite):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_URL = 'https://isff2026.eventive.org'
        self.address_map = {
            "Vinegar Hill Theatre": "220 W Market St, Charlottesville, VA 22902",
            "Violet Crown": "Violet Crown Charlottesville, 200 W Main St, Charlottesville, VA 22902",   
        }

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        """
        Override to use browser client wait_for_selector so JS-rendered date list is present.
        Falls back to plain requests if no browser client is provided.
        """
        if self.soup:
            return
        from ..http_client import NoDriverClient, HybridClient
        session = client.session if client else requests.Session()
        if "User-Agent" not in session.headers:
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"}
            )
        try:
            if isinstance(client, (NoDriverClient, HybridClient)):
                # Wait until the JS-populated date list appears before capturing HTML.
                # The schedule rows are rendered as elements with the 'date-list-item' class.
                response = client.get(
                    self.url,
                    timeout=120,
                    # Wait for the schedule links we actually parse later.
                    # This avoids paying the full timeout on pages where the broader
                    # ".month-group .date-list-item" selector appears slowly/late.
                    wait_for_selector="a[href^='/schedule/'][data-radium='true'], a[href^='/schedule/']",
                    wait_for_timeout=15,
                )
            else:
                response = session.get(self.url, timeout=10)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.text, "html.parser")
        except requests.RequestException as e:
            print(f"Error fetching {self.url}: {e}")
            self.soup = None

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            print("[IndieShortFilmFestivalEventWebsite] no soup loaded for event page; returning 0 events", flush=True)
            return []


        description_el = self.soup.select_one("div.tenant-injected-html")
        def _pick_best_image_src() -> str:
            """
            Pick the film poster image, avoiding loading placeholders/spinners.
            """
            candidates: list[str] = []
            blocked_substrings = {
                # Eventive banner/hero image to explicitly exclude.
                "13c25c6dac0e33aef510341ea2fa6dcc.png",
            }

            # Eventive often exposes the canonical poster URL via OpenGraph.
            og_image = self.soup.select_one("meta[property='og:image']")
            if og_image and og_image.get("content"):
                candidates.append(clean_text(og_image.get("content")))

            # Collect all IMG src values for scoring.
            for img in self.soup.select("img[src]"):
                src = clean_text(img.get("src") or "")
                if src:
                    candidates.append(src)

            def _score(src: str) -> int:
                s = src.lower()
                s_no_query = s.split("?", 1)[0]

                for blocked in blocked_substrings:
                    if blocked in s_no_query:
                        return -10_000

                score = 0
                if "static-a.eventive.org" in s:
                    score += 8
                if "poster" in s:
                    score += 6
                if "cloudfront.net" in s:
                    score += 4
                if "loading" in s or "spinner" in s or "placeholder" in s:
                    score -= 10
                return score

            if not candidates:
                return ""

            return max(candidates, key=_score)

        # Sometimes the movie title is rendered as a standalone styled div (e.g. <div style="font-size: 2em; ...; font-weight: bold;">909</div>)
        title_el = (
            self.soup.select_one(
                "div[style*='font-size: 2em'][style*='font-weight: bold']"
            )
            or self.soup.select_one('div.group-data-node-intro h1')
        )

        description = clean_text(description_el.get_text()) if description_el else ""
        # Fallback address if venue->address_map doesn't match.
        # Some pages might not include a structured address block consistently.
        address = ""
        phone = ""
        website = self.url
        image_src = _pick_best_image_src()
        if image_src.startswith("http://") or image_src.startswith("https://"):
            image_url = image_src
        elif image_src:
            image_url = self.BASE_URL + image_src
        else:
            image_url = ""
        title = clean_text(title_el.get_text(strip=True)) if title_el else ""

        events: list[dict] = []
        scraped_at = datetime.now(timezone.utc).isoformat()

        slot_anchors = self.soup.select("a[href^='/schedule/'][data-radium='true']")
        if not slot_anchors:
            # Fallback in case the data-radium attribute isn't present/consistent.
            slot_anchors = self.soup.select("a[href^='/schedule/']")
        # Eventive pages sometimes render showing rows in non-anchor wrappers.
        # Include date-list-item nodes so each visible showing line can map to an event.
        slot_rows = self.soup.select(".date-list-item")

        year_match = re.search(r"(\d{4})", self.BASE_URL or "")
        year = int(year_match.group(1)) if year_match else datetime.now().year

        month_map = {
            "JAN": 1,
            "FEB": 2,
            "MAR": 3,
            "APR": 4,
            "MAY": 5,
            "JUN": 6,
            "JUL": 7,
            "AUG": 8,
            "SEP": 9,
            "OCT": 10,
            "NOV": 11,
            "DEC": 12,
        }

        # Runtime is listed once per film page (example shown by you):
        #   Runtime ... 6:30
        # Interpret this as MM:SS and use it to compute end_time.
        runtime_delta: timedelta | None = None
        runtime_candidates = self.soup.select("li.rmq-f32d0bf4")
        runtime_el = None
        for cand in runtime_candidates:
            cand_text = clean_text(cand.get_text(" ", strip=True))
            if re.search(r"\bruntime\b", cand_text, flags=re.I):
                runtime_el = cand
                break
        if runtime_el:
            runtime_text = clean_text(runtime_el.get_text(" ", strip=True))
            m_rt = re.search(
                r"runtime\s*:?\s*(\d+)\s*:\s*(\d{1,2})",
                runtime_text,
                flags=re.I,
            )
            if m_rt:
                minutes = int(m_rt.group(1))
                seconds = int(m_rt.group(2))
                runtime_delta = timedelta(minutes=minutes, seconds=seconds)
            else:
                # Fallback for natural language durations, e.g. "Runtime: 10 minutes".
                m_minutes = re.search(
                    r"runtime\s*:?\s*(\d+)\s*(?:minutes?|mins?|min)\b",
                    runtime_text,
                    flags=re.I,
                )
                if m_minutes:
                    runtime_delta = timedelta(minutes=int(m_minutes.group(1)))

        def _parse_time(t: str):
            """
            Parse strings like:
              - '9:00 AM'
              - '10 AM'
            Return a `datetime.time` or None.
            """
            t = (t or "").strip()
            if not t:
                return None
            t = re.sub(r"\s+", " ", t).upper()
            m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*([AP]M)$", t)
            if not m:
                return None
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) is not None else 0
            ampm = m.group(3)
            return datetime.strptime(f"{hour}:{minute:02d} {ampm}", "%I:%M %p").time()

        slot_texts_seen: set[str] = set()
        slot_texts: list[str] = []

        # Preferred path: one schedule anchor == one showing line == one event.
        for slot_el in slot_anchors:
            slot_text = clean_text(slot_el.get_text(" ", strip=True))
            if not slot_text:
                continue
            key = re.sub(r"\s+", " ", slot_text).strip()
            if key in slot_texts_seen:
                continue
            slot_texts_seen.add(key)
            slot_texts.append(slot_text)

        # Fallback: some pages only expose combined rows.
        if not slot_texts:
            for slot_el in slot_rows:
                slot_text = clean_text(slot_el.get_text(" ", strip=True))
                if not slot_text:
                    continue
                key = re.sub(r"\s+", " ", slot_text).strip()
                if key in slot_texts_seen:
                    continue
                slot_texts_seen.add(key)
                slot_texts.append(slot_text)

        print(
            f"[IndieShortFilmFestivalEventWebsite] found {len(slot_texts)} schedule slot text block(s) for {self.url}",
            flush=True,
        )

        for slot_text in slot_texts:
            if not slot_text or "@" not in slot_text:
                continue

            # Split schedule slot into:
            #   - datetime string to parse start/end
            #   - venue string to map -> address
            # Use the LAST "@" as the boundary so date/time tokens that also use "@"
            # (e.g. "SAT MAR 22 @ 7:00 PM @ Venue") stay in date_time_text.
            date_time_text, venue_text = [p.strip() for p in slot_text.rsplit("@", 1)]

            md_matches = list(
                re.finditer(
                    r"\b([A-Za-z]{3})\s+(\d{1,2})(?:st|nd|rd|th)?\b",
                    date_time_text,
                    flags=re.I,
                )
            )
            if not md_matches:
                continue

            # Map venue -> address using `self.address_map`
            address_for_slot = ""
            venue_norm = clean_text(venue_text).strip()
            for k in self.address_map.keys():
                if k.lower() == venue_norm.lower() or k.lower() in venue_norm.lower():
                    address_for_slot = self.address_map[k]
                    break
            if not address_for_slot:
                # Fallback: use the address block extracted from the page.
                address_for_slot = address

            # A single rendered node can contain multiple showtimes. Emit one event
            # per date/time segment bounded by successive month/day tokens.
            for idx, md in enumerate(md_matches):
                month_str = md.group(1).upper()
                day = int(md.group(2))
                if month_str not in month_map:
                    continue

                start_date = datetime(year, month_map[month_str], day).date()
                end_date = start_date

                seg_start = md.start()
                seg_end = md_matches[idx + 1].start() if idx + 1 < len(md_matches) else len(date_time_text)
                date_time_slice = date_time_text[seg_start:seg_end]

                time_tokens = re.findall(
                    r"\b\d{1,2}(?::\d{2})?\s*[AP]M\b",
                    date_time_slice,
                    flags=re.I,
                )
                if not time_tokens:
                    continue

                start_time = _parse_time(time_tokens[0]) if len(time_tokens) >= 1 else None
                end_time = _parse_time(time_tokens[1]) if len(time_tokens) >= 2 else None

                # If runtime is available, compute end_time from start_time + runtime.
                # This is more reliable than relying on slot text to include an explicit end.
                if start_time is not None and runtime_delta is not None:
                    dt_start = datetime.combine(start_date, start_time)
                    dt_end = dt_start + runtime_delta
                    end_time = dt_end.time()
                    end_date = dt_end.date()

                events.append(
                    {
                        "title": title,
                        "event_link": self.url,
                        "description": description,
                        "image_url": image_url,
                        "organizer": "Indie Short Film Festival",
                        "address": address_for_slot,
                        "scraped_at": scraped_at,
                        "website": website,
                        "phone": phone,
                        "start_date": start_date,
                        "end_date": end_date,
                        "start_time": start_time,
                        "end_time": end_time,
                    }
                )

        print(
            f"[IndieShortFilmFestivalEventWebsite] emitting {len(events)} events for {self.url}",
            flush=True,
        )
        return events

    def extract_links(self, client: Optional[requests.Session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"IndieShortFilmFestivalEventWebsite w/ URL: {self.url}"
