from pathlib import Path
from app.parsers import extract_event_links

def test_extract_event_links_from_fixture():
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "events_listing.html"
    html = fixture_path.read_text(encoding="utf-8")
    links = extract_event_links(html)

    assert isinstance(links, list)
    assert len(links) > 0

