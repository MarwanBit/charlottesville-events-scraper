from abc import ABC, abstractmethod
from .constants import EVENT_TYPE_RULES, LOCATION_TYPE_RULES, normalize_primary_category
from datetime import datetime, date, time
import re

class BaseTransformer(ABC):

    @abstractmethod
    def transform_event(self, event: dict) -> dict:
        pass

class Transformer(BaseTransformer):

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        """
        Word-boundary aware matching to reduce false positives.

        The previous implementation used substring matching, which caused
        issues like keyword "pub" matching "Public".
        """
        t = (text or "").lower()
        for k in keywords:
            kw = (k or "").strip().lower()
            if not kw:
                continue
            # Apply word boundaries only when the keyword starts/ends with an alphanumeric char.
            start_b = r"\b" if (kw[0].isalnum()) else ""
            end_b = r"\b" if (kw[-1].isalnum()) else ""
            pattern = f"{start_b}{re.escape(kw)}{end_b}"
            if re.search(pattern, t, flags=re.IGNORECASE):
                return True
        return False

    def categorize_event(self, title: str, description: str, address: str, organizer: str) -> dict:
        blob = " ".join([title or "", description or "", address or "", organizer or ""]).lower()

        event_category = "Other"
        for cat, kws in EVENT_TYPE_RULES:
            if self._contains_any(blob, kws):
                event_category = cat
                break

        if self._contains_any(blob, ["kids", "children", "toddler", "family"]):
            audience = "Families"
        elif self._contains_any(blob, ["21+", "adults only", "cocktail", "wine", "beer"]):
            audience = "Adults"
        else:
            audience = "All Ages"

        location_type = "Other"
        for loc, kws in LOCATION_TYPE_RULES:
            if self._contains_any(blob, kws):
                location_type = loc
                break

        return {
            "event_category": normalize_primary_category(event_category),
            "audience": audience,
            "location_type": location_type,
        }

    def add_date_time_features(self, start_date: str, start_time: str):
        day_of_week = ""
        is_weekend = ""
        time_of_day = ""

        try:
            if start_date:
                if isinstance(start_date, (date, datetime)):
                    d = start_date if isinstance(start_date, datetime) else datetime.combine(start_date, datetime.min.time())
                else:
                    d = datetime.strptime(str(start_date), "%Y-%m-%d")
                day_of_week = d.strftime("%A")
                is_weekend = "TRUE" if day_of_week in ("Saturday", "Sunday") else "FALSE"
        except Exception:
            pass

        try:
            if start_time:
                if isinstance(start_time, (time, datetime)):
                    hour = start_time.hour
                elif isinstance(start_time, str) and re.match(r"^\d{2}:\d{2}", start_time):
                    hour = int(start_time.split(":")[0])
                else:
                    hour = None
                if hour is not None:
                    if 5 <= hour < 12:
                        time_of_day = "Morning"
                    elif 12 <= hour < 17:
                        time_of_day = "Afternoon"
                    elif 17 <= hour < 21:
                        time_of_day = "Evening"
                    else:
                        time_of_day = "Night"
        except Exception:
            pass

        return {"day_of_week": day_of_week, "is_weekend": is_weekend, "time_of_day": time_of_day}

    def transform_event(self, event: dict) -> dict:
        cat = self.categorize_event(
            event.get("title"),
            event.get("description"),
            event.get("address"),
            event.get("organizer"),
        )
        dt = self.add_date_time_features(event.get("start_date"), event.get("start_time"))
        event.update(cat)
        event.update(dt)
        return event