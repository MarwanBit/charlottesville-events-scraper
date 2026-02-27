from __future__ import annotations
import re

# Lazy: only import the getter so "from src.app.url_resolver import URLResolver" doesn't load all websites
from src.app.websites import EventsWebsite, get_resolver_map


class UnknownWebsiteError(ValueError):
    pass


class URLResolver:
    """Resolve a URL to a website handler. Website modules load on first resolve(), not at import time."""

    def __init__(self):
        self._regex_map = None

    def _get_regex_map(self):
        if self._regex_map is None:
            self._regex_map = get_resolver_map()
        return self._regex_map

    def resolve(self, url: str) -> EventsWebsite:
        for regex, website_cls in self._get_regex_map():
            if regex.fullmatch(url):
                return website_cls(url)
        raise UnknownWebsiteError(f"No resolver found for URL: {url}")
