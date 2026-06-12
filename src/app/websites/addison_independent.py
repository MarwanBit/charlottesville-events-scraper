from __future__ import annotations

from .base import EventsWebsite
from typing import Optional

from bs4 import BeautifulSoup, Tag
from datetime import datetime, timezone
import re
import os

from ..utils import clean_text
from ..llm_event_extractor import extract_addison_independent_events_from_page, ensure_env_loaded


class AddisonIndependentWebsite(EventsWebsite):
    """
    Scraper for https://www.addisonindependent.com/calendar/

    The calendar page contains event details inline: day headings and event titles
    appear as <strong>/<b> tags, typically inside a <p> element that also contains
    the date/time + location text.
    """

    BASE_URL = "https://www.addisonindependent.com"

    def _default_year(self, soup: BeautifulSoup) -> int:
        years = re.findall(r"\b(20\d{2})\b", soup.get_text(" ", strip=True))
        if not years:
            return datetime.now().year
        return max(int(y) for y in years)

    def _parse_date(self, text: str, default_year: int) -> tuple[Optional[str], Optional[str]]:
        """
        Parse "(Mon|Tue|... ), Month D" (optionally with a year) into YYYY-MM-DD.
        Returns (start_date, end_date). End date defaults to start date.
        """
        text = clean_text(text)
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
        m = re.search(
            r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,?\s*"
            r"([A-Za-z]+)\s+(\d{1,2})\s*(?:,\s*(\d{4}))?",
            text,
            flags=re.IGNORECASE,
        )
        if not m:
            return None, None
        month = months.get(m.group(2).strip().upper())
        if not month:
            return None, None
        day = int(m.group(3))
        year = int(m.group(4) or default_year)
        start_date = f"{year:04d}-{month:02d}-{day:02d}"
        return start_date, start_date

    def _parse_time_token(self, h: str, m: str | None, ampm: str) -> Optional[str]:
        try:
            hour = int(h)
            minute = int(m or "0")
        except ValueError:
            return None
        ampm_norm = ampm.strip().lower().replace(".", "")
        if ampm_norm.startswith("p") and hour != 12:
            hour += 12
        if ampm_norm.startswith("a") and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    def _extract_time_range(
        self, text: str
    ) -> tuple[Optional[str], Optional[str], Optional[int]]:
        """
        Extract (start_time, end_time, match_end_index) from the first time/range
        occurrence in the input text.
        """
        if not text:
            return None, None, None

        norm = clean_text(text)
        norm = norm.replace("–", "-").replace("—", "-")

        # Range with shared AM/PM, e.g. "7-9 p.m."
        range_shared_ampm_re = re.compile(
            r"(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*-\s*"
            r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*"
            r"(?P<ampm>[AaPp]\.?M\.?)",
            flags=re.IGNORECASE,
        )
        m = range_shared_ampm_re.search(norm)
        if m:
            start_time = self._parse_time_token(
                m.group("h1"), m.group("m1"), m.group("ampm")
            )
            end_time = self._parse_time_token(
                m.group("h2"), m.group("m2"), m.group("ampm")
            )
            return start_time, end_time, m.end()

        # Explicit tokens, e.g. "8:30 a.m.-2 p.m." or "3 p.m."
        time_token_re = re.compile(
            r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>[AaPp]\.?M\.?)",
            flags=re.IGNORECASE,
        )
        tokens = list(time_token_re.finditer(norm))
        if not tokens:
            # Also support explicit "time TBD" entries (no concrete time).
            m_tbd = re.search(r"\btime\s*tbd\b|\btbd\b", norm, flags=re.IGNORECASE)
            if m_tbd:
                return None, None, m_tbd.end()
            return None, None, None

        first = tokens[0]
        start_time = self._parse_time_token(first.group("h"), first.group("m"), first.group("ampm"))

        if len(tokens) >= 2:
            second = tokens[1]
            between = norm[first.end() : second.start()]
            if "-" in between or "to" in between.lower():
                end_time = self._parse_time_token(second.group("h"), second.group("m"), second.group("ampm"))
                return start_time, end_time, second.end()

        return start_time, None, first.end()

    def _parse_phone(self, text: str) -> str:
        if not text:
            return ""
        m = re.search(r"\b(\d{3})[-.\s]*(\d{3})[-.\s]*(\d{4})\b", text)
        if not m:
            return ""
        return f"({m.group(1)}){m.group(2)}-{m.group(3)}"

    def _extract_address(self, segment_text: str, title: str) -> str:
        """
        Extract a geocoding-friendly address from the part of the <p> that
        starts right after the time clause and ends before contact/boilerplate.

        The address is usually the first sentence/fragment, while the rest is
        description (e.g. "Meal includes ...", "Menu includes ...", etc).
        We therefore:
        1) cut the segment at common "description start" keywords
        2) extract the town from the trailing ", <Town>, VT" (if present)
        3) if we can't find an explicit address/town, fall back to location
           encoded in the bold title (e.g. "at Shelburne Farms in Shelburne.").
        """
        if not segment_text:
            return ""

        segment_text = clean_text(segment_text)

        # Remove leading "time/noise" fragments that can leak into this segment.
        segment_text = re.sub(
            r"^[-–]\s*(noon|time tbd|tbd)\b\s*,?\s*",
            "",
            segment_text,
            flags=re.IGNORECASE,
        )
        segment_text = re.sub(r"^sharp\b\s*,?\s*", "", segment_text, flags=re.IGNORECASE)

        # 1) Address piece: first part of the segment (before description boilerplate).
        cut_re = re.compile(
            r"\b(Meal includes|Menu includes|Community blood drive|Sponsored by|Featuring|Tickets|To reserve|Appointments|Register)\b",
            flags=re.IGNORECASE,
        )
        m_cut = cut_re.search(segment_text)
        addr_piece = segment_text[: m_cut.start()].strip() if m_cut else segment_text
        # Prefer treating the first sentence as the address when that first
        # sentence clearly looks addressy (Route/number at least). This helps
        # when the next sentence is pure description (e.g. "4334 Route 7. The exhibits...").
        parts = re.split(r"(?<=[.!?])\s+", addr_piece, maxsplit=1)
        if len(parts) == 2:
            first_sentence = parts[0].strip()
            if re.search(r"\bRoute\s+\d{1,6}\b", first_sentence, flags=re.IGNORECASE) or re.search(
                r"^\s*\d{1,6}\b", first_sentence, flags=re.IGNORECASE
            ):
                addr_piece = first_sentence
        addr_piece = addr_piece.rstrip(" .;:-,")
        addr_piece = re.sub(r"\.\s*,", ",", addr_piece)
        addr_piece = re.sub(r"\s+,", ",", addr_piece)

        # 2) Town extraction: prefer the trailing ", <Town>, VT" in the segment.
        town = None
        m_city = re.search(
            r"\b(?P<town>[A-Za-z][A-Za-z\s'\.\-]*?)\s*,\s*(?:VT|Vermont)\b(?:\s+\d{5})?",
            segment_text,
            flags=re.IGNORECASE,
        )
        if m_city:
            town = clean_text(m_city.group("town"))

        # If we found explicit "..., Town, VT" somewhere, use the shortened address piece.
        if town:
            # Avoid duplicating "VT" if it already exists in addr_piece.
            addr = addr_piece
            addr = re.sub(r"\bVermont\b", "VT", addr, flags=re.IGNORECASE)
            if not re.search(r"\bVT\b", addr, flags=re.IGNORECASE):
                addr = f"{addr}, {town}, VT"
            return addr.rstrip(" .;:-,")

        # 3) No town found: try to infer the town from the title.
        title_place = None
        title_town = None

        m_at_in = re.search(
            r"\bat\s+(?P<place>.+?)\s+in\s+(?P<town>[A-Za-z][A-Za-z]+)\.?",
            title,
            flags=re.IGNORECASE,
        )
        if m_at_in:
            title_place = clean_text(m_at_in.group("place")).strip(" ,.")
            title_town = clean_text(m_at_in.group("town"))

        if not title_town:
            m_in = re.search(
                r"\bin\s+(?P<town>[A-Za-z][A-Za-z]+)\b",
                title,
                flags=re.IGNORECASE,
            )
            if m_in:
                title_town = clean_text(m_in.group("town"))

        # If we have a likely venue fragment from the segment, append the inferred town.
        address_like_re = re.compile(
            r"\b(\d{1,6}\s+.+?\s+(?:St\.?|Street|Rd\.?|Road|Ave\.?|Avenue|Dr\.?|Drive|Ln\.?|Lane|Ct\.?|Court)|"
            r"Route\s+\d+|Route\s+\d{1,2}|\b(?:Hall|Room|Theater|Theatre|Library|Church|Museum|Park|Center|Farms|Vineyard|Zoo|Inn|School|Auditorium)\b)\b",
            flags=re.IGNORECASE,
        )
        desc_start_re = re.compile(
            r"^\s*(Hike|Walk|Join|Bring|Explore|Experience|Enjoy|Discover|Learn|Register|Registration|Easy-to|Easy\s*to)\b",
            flags=re.IGNORECASE,
        )
        if title_town and addr_piece and address_like_re.search(addr_piece) and not desc_start_re.search(addr_piece):
            return f"{addr_piece}, {title_town}, VT".rstrip(" .;:-,")

        # Otherwise, fall back to location encoded in the title.
        if re.search(r"\b(?:VT|Vermont)\b", title, flags=re.IGNORECASE):
            if not re.search(r"\bTickets?\b", title, flags=re.IGNORECASE):
                addr = clean_text(title)
                addr = re.sub(r"\bVermont\b", "VT", addr, flags=re.IGNORECASE)
                addr = addr.rstrip(" .;:-,")
                return addr if len(addr) >= 6 else ""

        if title_place and title_town:
            return f"{title_place}, {title_town}, VT"

        if title_town:
            before = clean_text(title).split(f" in {title_town}", 1)[0].strip(" ,.")
            before = re.sub(r"\bat\s*$", "", before, flags=re.IGNORECASE).strip(" ,.")
            if before:
                return f"{before}, {title_town}, VT"
            return f"{title_town}, VT"

        return ""

    @staticmethod
    def _slugify(s: str) -> str:
        s = (s or "").lower()
        s = re.sub(r"[^a-z0-9]+", "-", s)
        return s.strip("-")

    def get_events(self, client=None) -> list[dict]:
        if not self.soup:
            self.generate_soup(client)
        if not self.soup:
            return []

        default_year = self._default_year(self.soup)
        events: list[dict] = []
        # Make sure OPENAI_API_KEY is available if you're using a root-level .env file.
        ensure_env_loaded()
        llm_mode = os.environ.get("ADDISON_INDEPENDENT_LLM_MODE", "auto").strip().lower()  # auto|always|never
        llm_max_events = int(os.environ.get("ADDISON_INDEPENDENT_LLM_MAX_EVENTS", "120"))
        llm_api_key_present = bool(os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
        llm_inputs: list[dict[str, object]] = []
        llm_overrides_applied = False

        # The structure is: day headings, then one <p> per event (usually).
        # Within each event paragraph, the event title is usually the first
        # <strong>/<b> text.
        # Day headings examples on the page:
        #   "Thursday, March 26"
        #   "Saturday, Sept. 26"
        #   "Saturday, Aug. 1"
        #   "Sunday April 19"   (sometimes missing the comma)
        #
        # We normalize by stripping dots/spaces from the month token.
        day_heading_re = re.compile(
            r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,?\s+"
            r"([A-Za-z]+)\.?\s+(\d{1,2})$",
            flags=re.IGNORECASE,
        )
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
            # Common abbreviations that appear with a trailing period.
            "SEPT": 9,
            "AUG": 8,
        }

        current_start_date: Optional[str] = None
        event_idx = 0

        # Iterate <p> blocks in document order (more stable than iterating all <strong> tags).
        for p in self.soup.find_all("p"):
            strong = p.select_one("strong, b")
            if strong is None:
                continue

            raw_title = clean_text(strong.get_text(" ", strip=True))
            if not raw_title:
                continue

            # Update day context if this paragraph is a day heading.
            m_day = day_heading_re.match(raw_title)
            if m_day:
                month_token = re.sub(r"[^A-Za-z]", "", m_day.group(2).strip()).upper()
                month = months.get(month_token)
                if month:
                    current_start_date = f"{default_year:04d}-{month:02d}-{int(m_day.group(3)):02d}"
                else:
                    current_start_date = None
                continue

            # Skip obvious non-event navigation/footer headings (e.g. "CONTACT", "NAVIGATION").
            # These are typically all-caps with short length and no date/time.
            if (
                len(raw_title) <= 30
                and raw_title.upper() == raw_title
                and re.search(r"[A-Z]", raw_title)
            ):
                continue

            # Some titles include a leading weekday/date prefix, e.g.:
            #   "Monday, April 20 Industrial History of Monkton."
            # Strip the prefix if there are additional words after the date.
            title = raw_title
            m_prefix = re.match(
                r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,?\s+"
                r"([A-Za-z]+)\.?\s+(\d{1,2})\s+(.+)$",
                raw_title,
                flags=re.IGNORECASE,
            )
            if m_prefix:
                title = clean_text(m_prefix.group(4))

            # Most event paragraphs should have date/time in the same <p>;
            # if not, fall back to current day context.
            p_text = clean_text(p.get_text(" ", strip=True))
            if not p_text:
                continue

            start_date, end_date = self._parse_date(p_text, default_year)
            if start_date is None:
                if current_start_date is None:
                    continue
                start_date = end_date = current_start_date

            # The bold <strong>/<b> is the title. The rest of the text after the title
            # starts with time info and then (optionally) address before description/contact.
            after_title = ""
            if raw_title in p_text:
                after_title = p_text.split(raw_title, 1)[1].lstrip(" .").strip()
            if not after_title:
                after_title = p_text

            start_time, end_time, match_end = self._extract_time_range(after_title)
            if start_time is None and end_time is None and match_end is None:
                # If no time tokens were found and the paragraph isn't a "time TBD" entry,
                # skip. This filters out footer/menu blocks that happen to contain location-ish text.
                if not re.search(r"\btime\s*tbd\b|\btbd\b", p_text, flags=re.IGNORECASE):
                    continue

            after_time = after_title
            if match_end is not None:
                after_time = after_title[match_end:].lstrip(" ,.;:-").strip()

            # Cut off before contact / registration / boilerplate "more info".
            phone_re = re.compile(r"\b\d{3}[-.\s]*\d{3}[-.\s]*\d{4}\b", flags=re.IGNORECASE)
            email_re = re.compile(
                r"\b[\w\.-]+@[\w\.-]+\.[A-Za-z]{2,}\b", flags=re.IGNORECASE
            )
            cutoff_candidates: list[int] = []
            m_contact = re.search(r"\bContact\b", after_time, flags=re.IGNORECASE)
            if m_contact:
                cutoff_candidates.append(m_contact.start())
            m_more = re.search(r"\bMore\s+(information|info)\b", after_time, flags=re.IGNORECASE)
            if m_more:
                cutoff_candidates.append(m_more.start())
            m_phone = phone_re.search(after_time)
            if m_phone:
                cutoff_candidates.append(m_phone.start())
            m_email = email_re.search(after_time)
            if m_email:
                cutoff_candidates.append(m_email.start())
            m_tickets = re.search(r"\bTickets?\b", after_time, flags=re.IGNORECASE)
            if m_tickets:
                cutoff_candidates.append(m_tickets.start())
            m_www = re.search(r"\bwww\.", after_time, flags=re.IGNORECASE)
            if m_www:
                cutoff_candidates.append(m_www.start())

            cut = min(cutoff_candidates) if cutoff_candidates else None
            before_contact = after_time[:cut].strip() if cut is not None else after_time

            det_address = self._extract_address(before_contact, title)
            det_phone = self._parse_phone(p_text)

            # Description: everything before contact/more-info, with a best-effort removal
            # of a leading address sentence if one is present.
            det_description = before_contact
            if det_address:
                addr_clean = clean_text(det_address)
                addr_core = re.sub(
                    r",\s*[A-Za-z][A-Za-z\s'\.\-]*\s*,\s*(?:VT|Vermont)\b$",
                    "",
                    addr_clean,
                    flags=re.IGNORECASE,
                ).rstrip(" .;:-,")
                if det_description.lower().startswith(addr_core.lower()):
                    det_description = det_description[len(addr_core) :].lstrip(" .,:;:-").strip()
                else:
                    parts = re.split(r"(?<=[.!?])\s+", det_description, maxsplit=1)
                    if len(parts) == 2:
                        first, rest = parts
                        if re.search(
                            r"\b(?:VT|Vermont)\b|\b\d{1,6}\b.*\b(?:St\.?|Street|Rd\.?|Road|Route|Router|Ln\.?|Lane|Ave\.?|Avenue|Dr\.?|Drive)\b",
                            first,
                            flags=re.IGNORECASE,
                        ):
                            det_description = rest

            det_description = clean_text(det_description)

            address = det_address
            phone = det_phone
            description = det_description

            # Normalize empty strings into "" (pipeline expects strings/nulls).
            address = address or ""
            phone = phone or ""
            description = description or ""

            # Prepare one bulk LLM input (title + full paragraph text).
            llm_idx = len(events)
            llm_inputs.append(
                {
                    "idx": llm_idx,
                    "title": title,
                    "paragraph_text": p_text,
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )

            event_link = f"{self.url.split('?', 1)[0].rstrip('/')}#event-{self._slugify(title)}-{event_idx}"
            event_idx += 1

            events.append(
                {
                    "event_link": event_link,
                    "title": title,
                    "start_date": start_date,
                    "end_date": end_date,
                    "start_time": start_time,
                    "end_time": end_time,
                    "address": address,
                    "phone": phone,
                    "organizer": "",
                    "website": self.BASE_URL,
                    "description": description,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Bulk LLM override: send the whole page's event paragraphs and ask
        # for an array of per-event extracted fields.
        llm_enabled = llm_api_key_present and llm_mode in ("auto", "always")
        if llm_enabled and llm_inputs:
            # Auto mode: call only if we see signs of bad deterministic output.
            det_bad_count = 0
            for e in events[: min(len(events), llm_max_events)]:
                addr = (e.get("address") or "").strip()
                desc = (e.get("description") or "").lower()
                addr_bad = (not addr) or ("VT" not in addr.upper()) or ("tickets" in desc) or ("www." in desc)
                if addr_bad:
                    det_bad_count += 1

            should_call = llm_mode == "always" or det_bad_count > 0
            if os.environ.get("ADDISON_INDEPENDENT_LLM_DEBUG", "").strip().lower() in ("1", "true", "yes", "y"):
                print(
                    f"[AddisonIndependent][LLM bulk decision] llm_enabled={llm_enabled} mode={llm_mode} "
                    f"should_call={should_call} det_bad_count={det_bad_count} events_total={len(events)}",
                    flush=True,
                )

            if should_call:
                chunk_size = int(os.environ.get("ADDISON_INDEPENDENT_LLM_CHUNK_SIZE", "25"))
                llm_inputs_to_send = llm_inputs[: min(len(llm_inputs), llm_max_events)]
                for start in range(0, len(llm_inputs_to_send), chunk_size):
                    chunk = llm_inputs_to_send[start : start + chunk_size]
                    try:
                        llm_page_result = extract_addison_independent_events_from_page(
                            url=self.url,
                            events_inputs=chunk,
                        )
                    except Exception as e:
                        print(f"[AddisonIndependent][LLM bulk failed] {e}", flush=True)
                        llm_overrides_applied = False
                        break
                    llm_override_map = {ev.get("idx"): ev for ev in llm_page_result if ev.get("idx") is not None}
                    for idx, ev_fields in llm_override_map.items():
                        if isinstance(idx, int) and 0 <= idx < len(events):
                            sd = ev_fields.get("start_date")
                            ed = ev_fields.get("end_date")
                            st = ev_fields.get("start_time")
                            et = ev_fields.get("end_time")
                            addr = ev_fields.get("address")
                            org = ev_fields.get("organizer")
                            desc = ev_fields.get("description")
                            ph = ev_fields.get("phone")
                            email = ev_fields.get("email")
                            cost = ev_fields.get("cost")
                            contact = ev_fields.get("contact")
                            image_url = ev_fields.get("image_url")
                            if sd is not None:
                                events[idx]["start_date"] = sd
                            if ed is not None:
                                events[idx]["end_date"] = ed
                            if st is not None:
                                events[idx]["start_time"] = st
                            if et is not None:
                                events[idx]["end_time"] = et
                            if addr is not None and addr != "":
                                events[idx]["address"] = addr
                            if org is not None and org != "":
                                events[idx]["organizer"] = org
                            if desc is not None and desc != "":
                                events[idx]["description"] = desc
                            if ph is not None:
                                events[idx]["phone"] = ph or ""
                            if email is not None and email != "":
                                events[idx]["email"] = email
                            if cost is not None:
                                events[idx]["cost"] = cost
                            if contact is not None and contact != "":
                                events[idx]["contact"] = contact
                            if image_url is not None and image_url != "":
                                events[idx]["image_url"] = image_url

                llm_overrides_applied = True

        return events

    def extract_links(self, client=None) -> list[str]:
        # No pagination / per-event links exposed via a consistent pattern.
        return []

    def __str__(self) -> str:
        return f"AddisonIndependentWebsite w/ URL: {self.url}"

