from __future__ import annotations
import re

from src.app.websites import VisitMAEventWebsite, VisitMAWebsite
from src.app.websites import VisitCharlottesvilleEventWebsite
from src.app.websites import DiscoverDurhamWebsite
from src.app.websites import VisitCharlottesvilleWebsite
from src.app.websites import EventsWebsite
from src.app.websites import WashingtonWebsite, WashingtonEventWebsite
from src.app.websites import ExploreGeorgiaWebsite, ExploreGeorgiaEventWebsite
from src.app.websites import EnjoyIllinoisWebsite, EnjoyIllinoisEventWebsite
from src.app.websites import TexasTimeTravelWebsite, TexasTimeTravelEventWebsite


class UnknownWebsiteError(ValueError):
    pass

class URLResolver:

    def __init__(self):
        self.regex_map = [
            (
                re.compile(r"^https:\/\/www\.discoverdurham\.com\/events\/?(?:\?page=\d+)?&?$"), 
                DiscoverDurhamWebsite
            ),
            (
                re.compile(r"^https:\/\/www\.visitcharlottesville\.org\/events\/?(?:\?page=\d+)?&?$"), 
                VisitCharlottesvilleWebsite
            ),
            (
                re.compile(r"^https:\/\/www\.visitcharlottesville\.org\/events\/[A-Za-z0-9\u00C0-\u017F\-]+\/?&?$"), 
                VisitCharlottesvilleEventWebsite
            ),
            (
                re.compile(r"^https:\/\/washington\.org\/find-dc-listings\/events(?:\?page=\d+)?$"), 
                WashingtonWebsite
            ),
            (
                re.compile(r"^https://washington\.org/event/[a-z0-9-]+$"), 
                WashingtonEventWebsite
            ),
            (
                re.compile(r"^https://www\.visitma\.com/events/?(\?.*)?$"), 
                VisitMAWebsite
            ),
            (
                re.compile(r"^https://www\.visitma\.com/event/[0-9]+/?$"), 
                VisitMAEventWebsite
            ),
            (
                re.compile(r"^https:\/\/exploregeorgia\.org\/calendar-of-events(?:\?page=\d+)?$"), 
                ExploreGeorgiaWebsite
            ),
            (
                re.compile(r"^https:\/\/exploregeorgia\.org\/[^\/]+\/events\/[^\/]+(?:\/[^\/]+)?$"), 
                ExploreGeorgiaEventWebsite
            ),
            (
                re.compile(r"^https:\/\/www\.enjoyillinois\.com\/things-to-do\/festivals-and-events\/?(?:\?.*)?$"), 
                EnjoyIllinoisWebsite
            ),
            (
                re.compile(r"^https://www\.enjoyillinois\.com/things-to-do/festivals-and-events/listing/([a-z0-9-]+)/?$"), 
                EnjoyIllinoisEventWebsite
            ),
            (
                re.compile(r"^https://texastimetravel\.com/events/?(?:\?page=\d+)?&?$"),
                TexasTimeTravelWebsite
            ),
            (
                re.compile(r"^https://texastimetravel\.com/events/[a-z0-9-]+/?$"), 
                TexasTimeTravelEventWebsite
            ),
        ]

    def resolve(self, url) -> EventsWebsite:
        for regex, website_cls in self.regex_map:
            if regex.fullmatch(url):
                return website_cls(url)
        raise UnknownWebsiteError(f"No resolver found for URL: {url}")