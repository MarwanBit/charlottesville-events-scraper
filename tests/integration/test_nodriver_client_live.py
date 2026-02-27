from src.app.http_client import NoDriverClient
import pprint


def test_client_can_fetch_events_page():
    client = NoDriverClient().create_sync()
    url = 'https://www.visitma.com/events/'
    r = client.get(url)
    assert r.status_code == 200
    assert "<html" in r.text.lower()
