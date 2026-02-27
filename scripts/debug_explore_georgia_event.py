import pprint
import sys
from pathlib import Path

# Make src/ importable as a top-level package when running this script directly.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app.websites.explore_georgia import ExploreGeorgiaEventWebsite
from app.http_client import HybridClient


URL = "https://exploregeorgia.org/atlanta/events/family-friendly/the-burning-the-bound-grievous-ghost-tour-of-atlanta"


def main() -> None:
    client = HybridClient()
    try:
        website = ExploreGeorgiaEventWebsite(URL)
        # Force soup generation first so we can inspect exactly what HTML we got.
        website.generate_soup(client)
        if getattr(website, "soup", None) is not None:
            soup_str = str(website.soup)
            print(f"[DEBUG] soup length: {len(soup_str)}")
            print("[DEBUG] soup head (first 2000 chars):")
            print(soup_str)
        else:
            print("[DEBUG] website.soup is None")

        events = website.get_events(client)
        print(f"[DEBUG] URL: {URL}")
        print(f"[DEBUG] scraped {len(events)} events")
        for i, ev in enumerate(events[:10], start=1):
            print(f"[DEBUG] event #{i}:")
            pprint.pprint(ev)
    finally:
        client.close()


if __name__ == "__main__":
    main()

