"""
Integration tests that hit the real website.
These can fail if the site is down or blocks requests, so keep them minimal.
"""

def test_client_can_fetch_events_page(client):
    url = "https://www.visitcharlottesville.org/events/"
    r = client.get(url, timeout=20)

    assert r.status_code == 200
    assert "<html" in r.text.lower()
    # Keep the text check flexible (site content can change)
    assert "events" in r.text.lower()


