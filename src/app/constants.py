DB_FIELDS = {
    "event_link", "title",
    "start_date", "end_date", "start_time", "end_time",
    "day_of_week", "is_weekend", "time_of_day",
    "event_category", "audience", "location_type",
    "address", "organizer", "phone", "website", "image_url", "description",
    "scraped_at"
}

EVENT_TYPE_RULES = [
    ("Music", ["live music", "concert", "jazz", "rock", "band", "dj", "open mic", "karaoke"]),
    (
    "Food & Drink", ["wine", "beer", "brewery", "tasting", "cocktail", "dinner", "brunch", "restaurant", "food truck"]),
    ("Art", ["gallery", "exhibit", "exhibition", "art show", "museum", "artist talk"]),
    ("Theater", ["theatre", "theater", "play", "performance", "stage"]),
    ("Workshop/Class", ["workshop", "class", "lesson", "training", "bootcamp", "hands-on"]),
    ("Family/Kids", ["kids", "children", "family", "storytime", "toddler"]),
    ("Sports/Outdoor", ["run", "race", "hike", "yoga", "fitness", "outdoor", "park", "trail"]),
    ("Community/Networking", ["networking", "meetup", "community", "fundraiser", "volunteer", "charity"]),
    ("Education/Lecture", ["lecture", "talk", "seminar", "panel", "discussion", "university"]),
    ("Holiday/Seasonal", ["holiday", "christmas", "new year", "valentine", "halloween", "thanksgiving"]),
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
    'https://www.visitcharlottesville.org/events/'
]
