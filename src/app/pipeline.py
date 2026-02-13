from datetime import datetime, timezone
from listing_parser import parse_listing_cards, extract_event_from_card
from detail_scraper import scrape_event_detail
from transformer import categorize_event, add_date_time_features
from repository import Repository
from excel_exporter import export_to_excel
from crawler import iter_listing_pages
from config import EXCEL_OUTPUT

def run_pipeline(session):
    repo = Repository()
    all_events = []
    total_new = 0

    try:
        for page, html, cards_count in iter_listing_pages(session):
            _, cards = parse_listing_cards(html)
            new_count = 0

            for card in cards:
                base = extract_event_from_card(card)
                event_link = base.get("event_link", "")
                title = base.get("title", "")

                if not title or not event_link:
                    continue

                if repo.is_processed(event_link):
                    continue

                event = {
                    **base,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                }

                try:
                    details = scrape_event_detail(session, event_link)
                    event.update(details)

                    event.update(categorize_event(
                        title=event.get("title", ""),
                        description=event.get("description", ""),
                        address=event.get("address", ""),
                        organizer=event.get("organizer", ""),
                    ))

                    event.update(add_date_time_features(
                        start_date=event.get("start_date", ""),
                        start_time=event.get("start_time", ""),
                    ))

                    all_events.append(event)
                    repo.upsert_event(event)
                    repo.mark_processed(event_link)
                    repo.commit()

                    new_count += 1
                    total_new += 1

                    print(f"\n📄 Scraping LISTING page {page} ...")
                    print(f"  ▶ Event: {title}")

                except Exception as e:
                    repo.rollback()
                    print("Detail scrape failed:", event_link, e)

            # optional log
            if cards_count:
                print(f"Page {page}: cards={cards_count}, new={new_count}")

        export_to_excel(all_events, EXCEL_OUTPUT)
        print("\nDone ✅")
        print(f"Excel saved ✅ {EXCEL_OUTPUT}")
        return total_new

    finally:
        repo.close()
