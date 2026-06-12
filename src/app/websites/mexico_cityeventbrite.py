"""
Eventbrite Discover listing for Mexico City — same DOM/pagination behavior as
:class:`CharlottesvilleEventbriteWebsite`, different discover path:

``https://www.eventbrite.com/d/mexico--mexico-city/all-events/``

Event detail pages continue to use :class:`CharlottesvilleEventbriteEventWebsite`
(``/e/...`` on eventbrite.com or regional hosts).
"""

from typing import Optional

from bs4 import BeautifulSoup

from .charlottesville_eventbrite import CharlottesvilleEventbriteWebsite


class MexicoCityEventbriteWebsite(CharlottesvilleEventbriteWebsite):
    """Listing: ``/d/mexico--mexico-city/all-events/`` (see Eventbrite Discover)."""

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        super().__init__(url, soup)
        self.BASE_EVENTS_URL = self.BASE_URL + "/d/mexico--mexico-city/all-events/"
