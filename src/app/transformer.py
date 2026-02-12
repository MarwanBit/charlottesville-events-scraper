import re
from datetime import datetime
from app.constants import EVENT_TYPE_RULES, LOCATION_TYPE_RULES


def _contains_any(text: str, keywords: list[str]) -> bool:
    t = (text or "").lower()
    return any(k in t for k in keywords)


def categorize_event(title: str, description: str, address: str, organizer: str) -> dict:
    blob = " ".join([title or "", description or "", address or "", organizer or ""]).lower()

    event_category = "Other"
    for cat, kws in EVENT_TYPE_RULES:
        if _contains_any(blob, kws):
            event_category = cat
            break

    if _contains_any(blob, ["kids", "children", "toddler", "family"]):
        audience = "Families"
    elif _contains_any(blob, ["21+", "adults only", "cocktail", "wine", "beer"]):
        audience = "Adults"
    else:
        audience = "All Ages"

    location_type = "Other"
    for loc, kws in LOCATION_TYPE_RULES:
        if _contains_any(blob, kws):
            location_type = loc
            break

    return {"event_category": event_category, "audience": audience, "location_type": location_type}


def add_date_time_features(start_date: str, start_time: str) -> dict:
    day_of_week = ""
    is_weekend = ""
    time_of_day = ""

    try:
        if start_date:
            d = datetime.strptime(start_date, "%Y-%m-%d")
            day_of_week = d.strftime("%A")
            is_weekend = "TRUE" if day_of_week in ("Saturday", "Sunday") else "FALSE"
    except Exception:
        pass

    try:
        if start_time and re.match(r"^\d{2}:\d{2}$", start_time):
            hour = int(start_time.split(":")[0])
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
