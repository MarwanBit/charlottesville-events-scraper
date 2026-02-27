from src.app.websites import VisitCharlottesvilleWebsite

import pytest

def test_visit_charlottesville_extract_links(client):
    home_page = VisitCharlottesvilleWebsite('https://www.visitcharlottesville.org/events/')
    assert 'https://www.visitcharlottesville.org/events/?page=2&' in home_page.extract_links(client)
    assert home_page.extract_links(client) == [
        'https://www.visitcharlottesville.org/events/?page=2&'
    ]

def test_visit_charlottesville_get_events(client):
    home_page = VisitCharlottesvilleWebsite('https://www.visitcharlottesville.org/events/')
    events = home_page.get_events()
    print(events)
    assert len(events) >= 12