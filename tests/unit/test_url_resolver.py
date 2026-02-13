from src.app.websites import VisitCharlottesvilleWebsite
from src.app.websites import DiscoverDurhamWebsite
from src.app.websites import VisitCharlottesvilleEventWebsite
from src.app.url_resolver import UnknownWebsiteError

import pytest

def test_visit_charlottesville(resolver):
    event1_url = 'https://www.discoverdurham.com/events/?page=2'
    event2_url =  'https://www.discoverdurham.com/events/'
    website_1 = resolver.resolve(event1_url)
    website_2 = resolver.resolve(event2_url)
    assert isinstance(website_1, DiscoverDurhamWebsite)
    assert isinstance(website_2, DiscoverDurhamWebsite)
    assert str(website_1) == f"DiscoverDurhamWebsite w/ URL: {event1_url}"
    assert str(website_2) == f"DiscoverDurhamWebsite w/ URL: {event2_url}"

def test_visit_charlottesville_event_page(resolver):
    event1_url = 'https://www.visitcharlottesville.org/events/the-world-between-egypt-and-nubia-in-africa/'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, VisitCharlottesvilleEventWebsite)
    assert str(website_1) == f"VisitCharlottesvilleEventWebsite w/ URL: {event1_url}"

def test_discover_durham(resolver):
    event1_url = 'https://www.visitcharlottesville.org/events/'
    event2_url =  'https://www.visitcharlottesville.org/events/?page=2'
    website_1 = resolver.resolve(event1_url)
    website_2 = resolver.resolve(event2_url)
    assert isinstance(website_1, VisitCharlottesvilleWebsite)
    assert isinstance(website_2, VisitCharlottesvilleWebsite)
    assert str(website_1) == f"VisitCharlottesvilleWebsite w/ URL: {event1_url}"
    assert str(website_2) == f"VisitCharlottesvilleWebsite w/ URL: {event2_url}"

def test_matching_error(resolver):
    with pytest.raises(UnknownWebsiteError):
        resolver.resolve('https://www.google.com')
