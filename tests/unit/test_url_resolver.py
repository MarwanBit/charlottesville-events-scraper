from src.app.http_client import NoDriverClient

from src.app.websites import WashingtonWebsite, WashingtonEventWebsite
from src.app.websites import VisitCharlottesvilleWebsite
from src.app.websites import DiscoverDurhamWebsite
from src.app.websites import VisitCharlottesvilleEventWebsite
from src.app.websites import VisitMAWebsite, VisitMAEventWebsite
from src.app.websites import ExploreGeorgiaWebsite, ExploreGeorgiaEventWebsite
from src.app.websites import EnjoyIllinoisWebsite, EnjoyIllinoisEventWebsite
from src.app.websites import TexasTimeTravelWebsite, TexasTimeTravelEventWebsite

from src.app.url_resolver import UnknownWebsiteError

import pytest
import pprint

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

def test_washington(resolver, client):
    event1_url = 'https://washington.org/find-dc-listings/events'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, WashingtonWebsite)
    assert str(website_1) == f"WashingtonWebsite w/ URL: {event1_url}"
    assert 'https://washington.org/find-dc-listings/events?page=1' in website_1.extract_links(client)

def test_washington_event(resolver, client):
    event1_url = 'https://washington.org/event/rik-freeman-wade-waters'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, WashingtonEventWebsite)
    assert str(website_1) == f"WashingtonEventWebsite w/ URL: {event1_url}"
    assert website_1.extract_links(client) == []
    pprint.pprint(website_1.get_events(client))

@pytest.fixture(scope="module")
def visit_ma_client():
    """One NoDriverClient for all VisitMA tests in this module; skip if browser cannot start.
    Client is closed once after all Visit MA tests finish (do not close it inside each test)."""
    try:
        client = NoDriverClient.create_sync()
        yield client
    except RuntimeError as e:
        if "browser failed to start" in str(e):
            pytest.skip(
                "NoDriverClient could not start browser (Chrome/CDP unavailable). "
                "Run with a display or in an environment where Chrome can connect."
            )
        raise
    else:
        client.close()


def test_visit_ma(resolver, visit_ma_client):
    """VisitMA requires NoDriverClient; the site returns 403 for plain HTTP/requests."""
    client = visit_ma_client
    event1_url = 'https://www.visitma.com/events'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, VisitMAWebsite)
    assert str(website_1) == f"VisitMAWebsite w/ URL: {event1_url}"
    links = website_1.extract_links(client)
    assert len(links) >= 20, f"expected >= 20 links, got {len(links)}"
    pprint.pprint(links)


def test_visit_ma_events(resolver, visit_ma_client):
    client = visit_ma_client
    event1_url = 'https://www.visitma.com/events'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, VisitMAWebsite)
    assert str(website_1) == f"VisitMAWebsite w/ URL: {event1_url}"
    events = website_1.get_events(client)
    assert len(events) >= 20
    pprint.pprint(events)

def test_visit_ma_event_page(resolver, visit_ma_client):
    client = visit_ma_client
    event1_url = 'https://www.visitma.com/event/32011/'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, VisitMAEventWebsite)
    assert str(website_1) == f"VisitMAEventWebsite w/ URL: {event1_url}"
    events = website_1.get_events(client)
    pprint.pprint(events)

def test_explore_georgia_page(resolver, visit_ma_client):
    client = visit_ma_client
    event1_url = 'https://exploregeorgia.org/calendar-of-events'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, ExploreGeorgiaWebsite)
    assert str(website_1) == f"ExploreGeorgiaWebsite w/ URL: {event1_url}"
    links = website_1.extract_links(client)
    pprint.pprint(links)
    assert len(links) >= 10

def test_explore_georgia_events(resolver, visit_ma_client):
    client = visit_ma_client
    event1_url = 'https://exploregeorgia.org/calendar-of-events'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, ExploreGeorgiaWebsite)
    assert str(website_1) == f"ExploreGeorgiaWebsite w/ URL: {event1_url}"
    pprint.pprint(website_1.get_events(client))

def test_explore_georgia_event_page(resolver, visit_ma_client):
    client = visit_ma_client
    # 4-segment path: region/events/category/event-slug
    event1_url = 'https://exploregeorgia.org/atlanta/events/family-friendly/the-burning-the-bound-grievous-ghost-tour-of-atlanta'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, ExploreGeorgiaEventWebsite)
    assert str(website_1) == f"ExploreGeorgiaEventWebsite w/ URL: {event1_url}"
    # 3-segment path: region/events/event-slug
    event2_url = 'https://exploregeorgia.org/millen/events/friends-of-magnolia-springs-volunteer-work-day'
    website_2 = resolver.resolve(event2_url)
    assert isinstance(website_2, ExploreGeorgiaEventWebsite)
    assert str(website_2) == f"ExploreGeorgiaEventWebsite w/ URL: {event2_url}"
    pprint.pprint(website_1.get_events(client))

def test_enjoy_illinois(resolver, visit_ma_client):
    """VisitMA requires NoDriverClient; the site returns 403 for plain HTTP/requests."""
    client = visit_ma_client
    event1_url = 'https://www.enjoyillinois.com/things-to-do/festivals-and-events'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, EnjoyIllinoisWebsite)
    assert str(website_1) == f"EnjoyIllinoisWebsite w/ URL: {event1_url}"
    links = website_1.extract_links(client)
    pprint.pprint(links)
    assert len(links) >= 13, f"expected >= 13 links, got {len(links)}"

def test_enjoy_illinois_events(resolver, visit_ma_client):
    client = visit_ma_client
    event1_url = 'https://www.enjoyillinois.com/things-to-do/festivals-and-events'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, EnjoyIllinoisWebsite)
    assert str(website_1) == f"EnjoyIllinoisWebsite w/ URL: {event1_url}"
    events = website_1.get_events(client)
    pprint.pprint(events)

def test_enjoy_illinois_events_page(resolver, visit_ma_client):
    client = visit_ma_client
    event1_url = 'https://www.enjoyillinois.com/things-to-do/festivals-and-events/listing/northwestern-university-mens-and-womens-big-ten-basketball/'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, EnjoyIllinoisEventWebsite)
    assert str(website_1) == f"EnjoyIllinoisEventWebsite w/ URL: {event1_url}"
    events = website_1.get_events(client)
    pprint.pprint(events)

def test_texas_time_travel(resolver, client):
    """Uses HTTP client only; Texas Time Travel does not require a browser."""
    event1_url = 'https://texastimetravel.com/events'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, TexasTimeTravelWebsite)
    assert str(website_1) == f"TexasTimeTravelWebsite w/ URL: {event1_url}"
    links = website_1.extract_links(client)
    pprint.pprint(links)

def test_texas_time_travel_events(resolver, client):
    """Uses HTTP client only; Texas Time Travel does not require a browser."""
    event1_url = 'https://texastimetravel.com/events'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, TexasTimeTravelWebsite)
    assert str(website_1) == f"TexasTimeTravelWebsite w/ URL: {event1_url}"
    events = website_1.get_events(client)
    pprint.pprint(events)

def test_texas_time_travel_events_page(resolver, client):
    """Uses HTTP client only; Texas Time Travel does not require a browser."""
    event1_url = 'https://texastimetravel.com/events/cliff-cavin-journeys-of-a-lifetime/'
    website_1 = resolver.resolve(event1_url)
    assert isinstance(website_1, TexasTimeTravelEventWebsite)
    assert str(website_1) == f"TexasTimeTravelEventWebsite w/ URL: {event1_url}"
    events = website_1.get_events(client)
    pprint.pprint(events)

def test_matching_error(resolver):
    with pytest.raises(UnknownWebsiteError):
        resolver.resolve('https://www.google.com')
