from .base import EventsWebsite
from typing import Optional
import requests
from bs4 import Tag, BeautifulSoup
from datetime import datetime, timezone
from ..utils import clean_text
import re
from urllib.parse import urljoin, unquote

class MiddleburyWebsite(EventsWebsite):
    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        # Middlebury's event pages redirect to the home page on the non-`www` domain.
        # Normalize to `www.` so extracted links are stable.
        self.BASE_URL = "https://www.middlebury.edu"
        self.BASE_EVENTS_URL = self.BASE_URL + "/events"

    def parse_listing_cards(self, client: Optional[requests.session] = None) -> list[Tag]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        cards = self.soup.select("li.list__item")
        return cards

    def extract_event_from_card(self, card: Tag) -> dict:
        """
        Extract the event detail link from a listing card.

        Middlebury cards can contain multiple links; prefer the one whose href is of the form
        `/events/event/...` (and then fall back to `a.event-link` for older markup).
        """
        event_link_el = (
            card.select_one('a[href^="/events/event/"]')
            or card.select_one('a[href*="/events/event/"]')
            or card.select_one("a.event-link")
        )
        href = (event_link_el.get("href") or "").strip() if event_link_el else ""

        if href.startswith("http"):
            event_link = href
        elif href.startswith("/"):
            event_link = self.BASE_URL + href
        elif href:
            event_link = self.BASE_URL.rstrip("/") + "/" + href.lstrip("/")
        else:
            event_link = ""

        return {
            "event_link": event_link,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []
        return []

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        """
        Discover event detail links on the listing page, and also enqueue the next
        listing page link (if present).

        Pagination example:
          <a href="?page=2" title="Go to next page" rel="next" class="pagination__link">
        """
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        res = set[str]()
        # Old behavior: enqueue event detail links from each listing card.
        for card in self.parse_listing_cards(client):
            event_link = self.extract_event_from_card(card)["event_link"]
            if event_link:
                res.add(event_link)

        # New behavior: also enqueue the pagination next page.
        next_el = self.soup.select_one('a.pagination__link[rel="next"]') or self.soup.select_one(
            'a[rel="next"]'
        )
        href = (next_el.get("href") or "").strip() if next_el else ""
        if href and href != "#":
            res.add(urljoin(self.BASE_EVENTS_URL, href))

        return list[str](res)

    def __str__(self):
        return f"MiddleburyWebsite w/ URL: {self.url}"

class MiddleburyEventWebsite(EventsWebsite):
    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        # Normalize URL to the `www.` domain to avoid redirects to the home page.
        if self.url.startswith("https://middlebury.edu/"):
            self.url = self.url.replace("https://middlebury.edu", "https://www.middlebury.edu", 1)
        self.BASE_URL = "https://www.middlebury.edu"
        self.BASE_EVENTS_URL = self.BASE_URL + "/events"

    @staticmethod
    def _looks_like_logo_url(url: str) -> bool:
        u = (url or "").strip().lower()
        if not u:
            return True
        # Heuristics: logos/icons/favicons tend to match these patterns.
        return any(
            k in u
            for k in (
                "logo",
                "brand",
                "favicon",
                "icon",
                "sprite",
                "site-icon",
                "apple-touch-icon",
            )
        ) or u.endswith(".svg")

    @staticmethod
    def _normalize_phone_from_tel_href(href: str) -> str:
        """
        Normalize `tel:` href into "(AAA)BBB-CCCC".
        Returns empty string if we can't find a plausible 10-digit number.
        """
        if not href:
            return ""
        raw = unquote(href.strip())
        # Some pages can contain double-prefixed values like "tel:tel:%28..."
        while raw.lower().startswith("tel:"):
            raw = raw[4:]
        digits = re.sub(r"\D+", "", raw)
        if not digits:
            return ""
        # Handle optional leading country code.
        if len(digits) >= 11 and digits.startswith("1"):
            digits = digits[1:]
        # If there are extra digits (extensions), keep the last 10.
        if len(digits) >= 10:
            digits = digits[-10:]
        if len(digits) != 10:
            return ""
        a, b, c = digits[:3], digits[3:6], digits[6:]
        return f"({a}){b}-{c}"

    @staticmethod
    def _normalize_address_for_geocoding(address: str) -> str:
        """
        Middlebury locations often look like:
          "Adirondack Circle"
          "The Bunker (FIC 121) 203 Freeman Way Middlebury, VT 05753"
          "Davis Family Library 145 110 Storrs Road Middlebury, VT 05753"

        For geocoding we want to keep the *actual* street address (when present)
        plus "Middlebury, VT 05753", and drop room/building fluff.
        """
        raw = clean_text(address or "")
        if not raw:
            return raw

        # Extract the trailing city/state/zip chunk if present.
        # Middlebury events typically end with:
        #   "Middlebury, VT 05753"
        m_tail = re.search(r"(Middlebury\s*,\s*VT\s*\d{5})\s*$", raw, flags=re.IGNORECASE)
        if not m_tail:
            # If the page didn't include city/zip, append the Middlebury default
            # unless we detect another state/zip already.
            if re.search(r"\b\d{5}\b", raw):
                return raw
            if re.search(r"\b[A-Z]{2}\b", raw):
                return raw
            prefix_no_parens = re.sub(r"\([^)]*\)", " ", raw)
            prefix_no_tokens = re.sub(
                r"\b(Room|Section|Suite|Unit|Basement|FIC)\b\s*[A-Za-z0-9]+",
                " ",
                prefix_no_parens,
                flags=re.IGNORECASE,
            )
            prefix_no_digits = re.sub(r"\b\d{1,5}\b", " ", prefix_no_tokens)
            cleaned = clean_text(prefix_no_digits).strip(", ")
            if cleaned:
                return f"{cleaned}, Middlebury, VT 05753"
            return f"Middlebury, VT 05753"
        tail = clean_text(m_tail.group(1))
        prefix = clean_text(raw[: m_tail.start()].strip(" ,"))

        # Street address match: last occurrence wins.
        # We specifically capture "<number> <street-name> <suffix>".
        suffixes = (
            r"St\.?|Street|Rd\.?|Road|Ave\.?|Avenue|Way|Ln\.?|Lane|Dr\.?|Drive|"
            r"Ct\.?|Court|Blvd\.?|Boulevard|Pl\.?|Place|Cir\.?|Circle|Ter\.?|Terrace|"
            r"Hwy\.?|Highway|Pkwy\.?|Parkway|Ext\.?|Extension"
        )
        street_re = re.compile(
            rf"\b(?P<num>\d{{1,6}})\s+"
            # Disallow digits in street name to avoid swallowing "100 120 Freeman Way"
            # as a match starting at 100.
            rf"(?P<name>[A-Za-z][A-Za-z\.\- ]*?)\s+"
            rf"(?P<suffix>{suffixes})\b",
            re.IGNORECASE,
        )
        street_matches = list(street_re.finditer(prefix))
        if street_matches:
            last = street_matches[-1]
            num = last.group("num")
            name = clean_text(last.group("name"))
            suffix = clean_text(last.group("suffix"))
            street = f"{num} {name} {suffix}".replace("  ", " ").strip()
            # Normalize suffix casing a bit.
            street = re.sub(r"\bSt\.\b", "St", street)
            street = re.sub(r"\bRd\.\b", "Rd", street)
            street = re.sub(r"\bAve\.\b", "Ave", street)
            street = re.sub(r"\bLn\.\b", "Ln", street)
            street = re.sub(r"\bDr\.\b", "Dr", street)
            street = re.sub(r"\bCt\.\b", "Ct", street)
            return f"{street}, {tail}"

        # No explicit street address: remove room/section/basement fluff but keep the place name.
        prefix_no_parens = re.sub(r"\([^)]*\)", " ", prefix)
        prefix_no_tokens = re.sub(
            r"\b(Room|Section|Suite|Unit|Basement|FIC)\b\s*[A-Za-z0-9]+",
            " ",
            prefix_no_parens,
            flags=re.IGNORECASE,
        )
        prefix_no_digits = re.sub(r"\b\d{1,5}\b", " ", prefix_no_tokens)
        cleaned = clean_text(prefix_no_digits)
        cleaned = cleaned.strip(", ")
        # Some Middlebury pages include the city twice:
        #   "... Middlebury, VT 05753"
        # In that case we want a single "..., Middlebury, VT 05753".
        if cleaned.lower().endswith("middlebury"):
            cleaned = cleaned[: -len("middlebury")].strip(" ,")
        if cleaned:
            return f"{cleaned}, {tail}"
        return tail

    @staticmethod
    def _parse_time_12h_to_24h(t: str) -> Optional[str]:
        """
        Parse times like '8:00 AM ET' / '8 PM ET' into 'HH:MM' (24h).
        Returns None if parsing fails.
        """
        if not t:
            return None
        raw = clean_text(t).upper()
        raw = raw.replace("ET", "").strip()
        m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", raw)
        if not m:
            return None
        hour = int(m.group(1))
        minute = int(m.group(2) or "0")
        ampm = m.group(3)
        if ampm == "PM" and hour != 12:
            hour += 12
        if ampm == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    @classmethod
    def _parse_date_time_range_from_text(
        cls, full_text: str
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Parse a range from strings like:
          'Sunday, March 29, 2026 8:00 AM ET–8:00 PM ET'

        Returns (start_date, end_date, start_time, end_time) with:
          - dates: 'YYYY-MM-DD'
          - times: 'HH:MM' (24h)
        """
        text = clean_text(full_text)
        months = {
            "JANUARY": 1,
            "FEBRUARY": 2,
            "MARCH": 3,
            "APRIL": 4,
            "MAY": 5,
            "JUNE": 6,
            "JULY": 7,
            "AUGUST": 8,
            "SEPTEMBER": 9,
            "OCTOBER": 10,
            "NOVEMBER": 11,
            "DECEMBER": 12,
        }

        # Allow missing space between year and time (some markup collapses it).
        date_time_re = re.compile(
            r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,\s*"
            r"([A-Za-z]+)\s+(\d{1,2})\s*,\s*(\d{4})\s*"
            r"(\d{1,2}(?::\d{2})?\s*[AP]M)\s*(?:ET)?\s*[-–]\s*"
            r"(\d{1,2}(?::\d{2})?\s*[AP]M)\s*(?:ET)?",
            re.IGNORECASE,
        )
        m = date_time_re.search(text)
        if not m:
            return None, None, None, None

        month_raw = m.group(2).strip().upper()
        month = months.get(month_raw)
        if not month:
            return None, None, None, None

        day = int(m.group(3))
        year = int(m.group(4))
        start_time = cls._parse_time_12h_to_24h(m.group(5))
        end_time = cls._parse_time_12h_to_24h(m.group(6))
        start_date = f"{year:04d}-{month:02d}-{day:02d}"
        # Assume the time range is on the same calendar date unless proven otherwise.
        end_date = start_date
        return start_date, end_date, start_time, end_time

    @staticmethod
    def _extract_description(soup: BeautifulSoup) -> str:
        """
        Middlebury pages have a fairly consistent text template:
        - Title + date/time line
        - Address line + "Open to the Public"
        - Then the event narrative/location-details
        - Then "Sponsored by" / "Contact Organizer"

        Extract the narrative block using those textual markers; fall back to the
        largest `.typography` container if markers fail.
        """
        page_text = clean_text(soup.get_text(" ", strip=True))
        # Prefer marker-based extraction to avoid grabbing unrelated typography blocks.
        m = re.search(
            r"Open to the Public\s*(.*?)\s*Sponsored by",
            page_text,
            flags=re.IGNORECASE,
        )
        if m:
            return clean_text(m.group(1))

        m = re.search(
            r"Open to the Public\s*(.*?)\s*Contact Organizer",
            page_text,
            flags=re.IGNORECASE,
        )
        if m:
            return clean_text(m.group(1))

        # Fallback: pick the largest typography-like block.
        candidates = soup.select(".typography, div.typography")
        best = ""
        for el in candidates:
            txt = clean_text(el.get_text(" ", strip=True))
            if not txt:
                continue
            # Avoid blocks that are mostly "boilerplate".
            if re.search(r"\bContact Organizer\b", txt, flags=re.I):
                continue
            if len(txt) > len(best):
                best = txt
        return best

    def get_events(self, client: Optional[requests.session] = None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        title_el = self.soup.select_one(".page-header__title") or self.soup.select_one(
            "h1"
        )
        title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""

        address_el = self.soup.select_one("address.f4") or self.soup.select_one("address")
        address = clean_text(address_el.get_text(" ", strip=True)) if address_el else ""
        address = self._normalize_address_for_geocoding(address)

        # Phone: we'll re-resolve from the "Contact Organizer" block below.
        # As a minimal fallback, parse the first tel: href (but never rely on link text).
        phone = ""
        first_tel_el = self.soup.select_one('a[href^="tel:"]')
        if first_tel_el:
            phone = self._normalize_phone_from_tel_href(first_tel_el.get("href") or "")

        # Times/dates:
        start_date = end_date = start_time = end_time = None
        time_tags = self.soup.select("time")
        dt_values = []
        if time_tags:
            for t in time_tags:
                dt = t.get("datetime")
                if not dt:
                    continue
                # datetime.fromisoformat doesn't like trailing Z.
                dt_norm = dt.replace("Z", "+00:00")
                try:
                    parsed = datetime.fromisoformat(dt_norm)
                except ValueError:
                    continue
                dt_values.append(parsed)

        if len(dt_values) >= 2:
            dt_values.sort()
            start_dt = dt_values[0]
            end_dt = dt_values[-1]
            start_date = start_dt.date().isoformat()
            end_date = end_dt.date().isoformat()
            start_time = start_dt.strftime("%H:%M")
            end_time = end_dt.strftime("%H:%M")
        else:
            full_text = self.soup.get_text(" ", strip=True)
            start_date, end_date, start_time, end_time = self._parse_date_time_range_from_text(
                full_text
            )

        scraped_at = datetime.now(timezone.utc).isoformat()
        event_link = self.url.split("?", 1)[0].rstrip("/")

        description = self._extract_description(self.soup)

        # Organizer:
        # Anchor on the "Contact Organizer" section by using the organizer phone
        # (the `tel:` link) and then extracting the first "Last, First ..." name
        # pattern from that block.
        organizer = ""
        label_re = re.compile(r"Contact\s+Organizer", re.I)
        contact_container = None
        tel_el_contact = None

        tel_links = self.soup.select('a[href^="tel:"]')
        for cand_tel in tel_links:
            try:
                for parent in [cand_tel] + list(getattr(cand_tel, "parents", []))[:40]:
                    txt = parent.get_text(" ", strip=True) if hasattr(parent, "get_text") else ""
                    if txt and label_re.search(txt):
                        contact_container = parent
                        tel_el_contact = cand_tel
                        break
                if contact_container is not None:
                    break
            except Exception:
                continue

        if contact_container is None and tel_links:
            tel_el_contact = tel_links[0]
            contact_container = tel_el_contact.find_parent() or tel_el_contact.parent

        if contact_container is not None:
            container_text = clean_text(contact_container.get_text(" ", strip=True))
            container_text = re.sub(r"\bContact\s+Organizer\b", " ", container_text, flags=re.I)
            # Remove email + phone-like fragments.
            no_email = re.sub(r"\S+@\S+", " ", container_text)
            no_phone = re.sub(
                r"tel:\s*", " ", no_email, flags=re.I
            )
            no_phone = re.sub(
                r"\b(\+?1[\s.-]?)?(\(?\d{3}\)?)[\s.-]*(\d{3})[\s.-]*(\d{4})\b",
                " ",
                no_phone,
            )
            cleaned = clean_text(no_phone)

            name_re = re.compile(
                # Capture "Last, First ..." and include a trailing middle initial like "C."
                # even when followed by punctuation like "(".
                r"([A-Z][A-Za-z\.\-']+(?:\s+[A-Z][A-Za-z\.\-']+)*,\s*[A-Z][A-Za-z\.\-']+(?:\s+[A-Z][A-Za-z\.\-']+)*(?:\.)?)(?=[^A-Za-z0-9]|$)"
            )
            m_name = name_re.search(cleaned)
            if m_name:
                organizer = m_name.group(1).strip()
            else:
                # Fallback: if comma-name regex fails, take the first non-empty token sequence
                # that contains letters and at least 2 alphabetic words.
                parts = [p.strip() for p in re.split(r"[|/]+", cleaned) if p.strip()]
                for p in parts:
                    if len([w for w in p.split() if re.search(r"[A-Za-z]", w)]) >= 2 and "," in p:
                        organizer = p.strip()
                        break

            # Phone: prefer tel: href inside the contact container.
            if tel_el_contact is not None:
                phone_norm = self._normalize_phone_from_tel_href(
                    tel_el_contact.get("href") or ""
                )
                if phone_norm:
                    phone = phone_norm

        # Image URL:
        image_url = ""

        # Prefer the visible event image. This is usually the actual poster/feature image.
        img_el = self.soup.select_one("div.page-image img")
        if img_el:
            candidate = clean_text(img_el.get("src") or img_el.get("data-src") or "")
            if not self._looks_like_logo_url(candidate):
                image_url = candidate

        # Fallback: meta tags (but ignore logo-like images).
        if not image_url:
            candidates = [
                self.soup.select_one('meta[property="og:image"]'),
                self.soup.select_one('meta[name="twitter:image"]'),
            ]
            for meta in candidates:
                if not meta:
                    continue
                candidate = clean_text(meta.get("content") or "")
                if candidate and not self._looks_like_logo_url(candidate):
                    image_url = candidate
                    break

        if image_url and image_url.startswith("//"):
            image_url = "https:" + image_url
        if image_url and image_url.startswith("/"):
            image_url = urljoin(self.BASE_URL, image_url)

        return [
            {
                "title": title,
                "event_link": event_link,
                "description": description,
                "address": address,
                "phone": phone,
                "organizer": organizer,
                "website": self.BASE_URL,
                "image_url": image_url,
                "start_date": start_date,
                "end_date": end_date,
                "start_time": start_time,
                "end_time": end_time,
                "scraped_at": scraped_at,
            }
        ]

    def extract_links(self, client: Optional[requests.session] = None) -> list[str]:
        return []

    def __str__(self):
        return f"MiddleburyEventWebsite w/ URL: {self.url}"