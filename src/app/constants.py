from typing import Optional

# events_processed.tags: comma-separated; each tag 1–30 chars; max 10 tags.
TAG_MAX_LEN = 30
TAG_MAX_COUNT = 10

DB_FIELDS = {
    "event_link", "title",
    "start_date", "end_date", "start_time", "end_time",
    "day_of_week", "is_weekend", "time_of_day",
    "event_category", "secondary_category", "audience", "location_type",
    "address", "location_name", "organizer", "phone", "website", "image_url", "description",
    "latitude", "longitude", "email", "cost", "contact",
    "scraped_at"
}

# Canonical `primary_category` / `event_category` values (events_processed + transformer).
PRIMARY_CATEGORIES: tuple[str, ...] = (
    "Food & Drink",
    "Music",
    "Sports & Fitness",
    "Art & Culture",
    "Photography",
    "Entertainment",
    "Game",
    "Educational",
    "Social / Community",
    "Business / Corporate",
    "Technology",
    "Family / Kids",
    "Holiday / Seasonal",
    "Charity / Fundraising",
    "Other",
)

_PRIMARY_BY_LOWER = {c.lower(): c for c in PRIMARY_CATEGORIES}

# Map legacy or alternate labels to canonical names.
_LEGACY_PRIMARY_CATEGORY_MAP = {
    "food": "Food & Drink",
    "food & drink": "Food & Drink",
    "arts": "Art & Culture",
    "art": "Art & Culture",
    "culture": "Art & Culture",
    "sports": "Sports & Fitness",
    "fitness": "Sports & Fitness",
    "charity": "Charity / Fundraising",
    "fundraising": "Charity / Fundraising",
    "business": "Business / Corporate",
    "corporate": "Business / Corporate",
    "tech": "Technology",
    "education": "Educational",
    "family": "Family / Kids",
    "kids": "Family / Kids",
    "holiday": "Holiday / Seasonal",
    "seasonal": "Holiday / Seasonal",
    "misc": "Other",
    "miscellaneous": "Other",
    "unknown": "Other",
}


def normalize_primary_category(value: Optional[str]) -> str:
    """Map stored or inferred categories onto PRIMARY_CATEGORIES; default Other."""
    if value is None:
        return "Other"
    s = str(value).strip()
    if not s:
        return "Other"
    if s in PRIMARY_CATEGORIES:
        return s
    low = s.lower()
    if low in _PRIMARY_BY_LOWER:
        return _PRIMARY_BY_LOWER[low]
    if low in _LEGACY_PRIMARY_CATEGORY_MAP:
        return _LEGACY_PRIMARY_CATEGORY_MAP[low]
    return "Other"


def _normalize_tag_token(raw: Optional[str]) -> Optional[str]:
    """Single tag: strip, turn internal commas into spaces, collapse space, length 1–TAG_MAX_LEN."""
    if raw is None:
        return None
    s = " ".join(str(raw).replace(",", " ").split())
    if not s:
        return None
    s = s[:TAG_MAX_LEN]
    return s if s else None


def build_tags_csv(
    audience: Optional[str],
    location_type: Optional[str],
    *extra: Optional[str],
) -> Optional[str]:
    """Comma + space separated tags for events_processed; each tag 1–TAG_MAX_LEN chars; max TAG_MAX_COUNT."""
    out: list[str] = []
    seen: set[str] = set()
    for x in (audience, location_type, *extra):
        t = _normalize_tag_token(x)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= TAG_MAX_COUNT:
            break
    if not out:
        return None
    return ", ".join(out)


EVENT_TYPE_RULES = [
    # Order matters: the first matching rule wins.
    ("Food & Drink", ["wine", "beer", "brewery", "tasting", "cocktail", "dinner", "brunch", "restaurant", "food truck", "cafe", "coffee", "dining", "snack", "pub"]),
    ("Music", ["live music", "concert", "jazz", "rock", "band", "dj", "open mic", "karaoke", "singer", "song", "musical"]),
    ("Sports & Fitness", ["run", "race", "hike", "yoga", "fitness", "workout", "outdoor", "park", "trail", "gym", "basketball", "soccer", "football", "baseball", "swim", "tennis", "martial arts"]),
    ("Art & Culture", ["gallery", "exhibit", "exhibition", "art show", "museum", "artist talk", "culture", "cultural", "heritage", "history", "arts"]),
    ("Photography", ["photo", "photography", "photographer", "camera", "photoshoot", "photo walk", "photowalk"]),
    ("Entertainment", ["film", "movie", "screening", "screenplay", "performance", "stage", "show", "live show", "comedy", "cabaret", "variety show", "magic", "illusion", "theater", "theatre", "play"]),
    ("Game", ["game night", "board game", "chess", "video game", "gaming", "esports", "trivia", "jeopardy", "poker tournament", "tabletop"]),
    ("Educational", ["lecture", "talk", "seminar", "panel", "discussion", "university", "class", "lesson", "training", "course", "education", "study", "workshop"]),
    ("Social / Community", ["meetup", "community", "volunteer", "neighborhood", "social", "friend", "mixer", "support group", "charity walk"]),
    ("Business / Corporate", ["business", "corporate", "startup", "entrepreneur", "entrepreneurship", "conference", "leadership", "company", "ceo", "cfo", "investor", "b2b", "networking", "sponsor", "trade show"]),
    ("Technology", ["technology", "tech", "software", "programming", "developer", "developers", "coding", "code", "ai", "artificial intelligence", "machine learning", "cybersecurity", "blockchain", "data", "cloud", "devops", "hackathon", "robotics"]),
    ("Family / Kids", ["kids", "children", "family", "storytime", "toddler", "youth", "family-friendly", "kid-friendly"]),
    ("Holiday / Seasonal", ["holiday", "christmas", "new year", "valentine", "halloween", "thanksgiving", "easter", "spring festival", "winter festival"]),
    ("Charity / Fundraising", ["charity", "fundraiser", "fund-raiser", "donate", "donation", "benefit", "gala", "walkathon", "race for", "raise funds", "auction"]),
    ("Other", []),
]

LOCATION_TYPE_RULES = [
    ("Winery/Brewery", ["winery", "vineyard", "brewery", "taproom"]),
    ("Restaurant/Bar", ["restaurant", "bar", "cafe", "coffee", "bistro", "pub"]),
    ("Theater/Venue", ["theatre", "theater", "auditorium", "venue"]),
    ("Museum/Gallery", ["museum", "gallery"]),
    ("University/School", ["university", "college", "school"]),
    ("Park/Outdoor", ["park", "garden", "trail", "outdoor"]),
    ("Hotel", ["hotel", "inn"]),
    ("Community Center", ["community center", "center", "library"]),
]

INITIAL_URLS = [
    'https://www.visitcharlottesville.org/events/',
    'https://washington.org/find-dc-listings/events',
    'https://www.visitma.com/events',
    'https://exploregeorgia.org/calendar-of-events',
    'https://www.enjoyillinois.com/things-to-do/festivals-and-events/',
    'https://texastimetravel.com/events/',
    'https://isff2026.eventive.org/films',
    'https://tomtomfestival2026.sched.com/list/simple',
    'https://www.middlebury.edu/events',
    'https://www.addisonindependent.com/calendar/',
    'https://theparamount.net/events/',
    'https://www.charlottesvillefamily.com/top-family-events/',
    'https://frontporchcville.org/concerts/',
    'https://cvillerightnow.com/events/#/show?start=2026-04-05',
    'https://www.eventbrite.com/d/va--charlottesville/all-events/?page=0&start_date=2026-03-28&end_date=2026-05-31',
    'https://www.eventbrite.com/d/mexico--mexico-city/all-events/?page=0&start_date=2026-04-14&end_date=2026-05-31',
]
