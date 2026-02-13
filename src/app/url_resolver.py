from __future__ import annotations
import re

from src.app.websites import VisitCharlottesvilleEventWebsite
from src.app.websites import DiscoverDurhamWebsite
from src.app.websites import VisitCharlottesvilleWebsite
from src.app.websites import EventsWebsite


class UnknownWebsiteError(ValueError):
    pass

class URLResolver:

    def __init__(self):
        self.regex_map = [
            (re.compile(r"^https:\/\/www\.discoverdurham\.com\/events\/?(?:\?page=\d+)?&?$"), DiscoverDurhamWebsite),
            (re.compile(r"^https:\/\/www\.visitcharlottesville\.org\/events\/?(?:\?page=\d+)?&?$"), VisitCharlottesvilleWebsite),
            (re.compile(r"^https:\/\/www\.visitcharlottesville\.org\/events\/[A-Za-z0-9\u00C0-\u017F\-]+\/?&?$"), VisitCharlottesvilleEventWebsite)
        ]

    def resolve(self, url) -> EventsWebsite:
        for regex, website_cls in self.regex_map:
            if regex.fullmatch(url):
                return website_cls(url)
        raise UnknownWebsiteError(f"No resolver found for URL: {url}")