import requests
import json
import pprint
import datetime
from datetime import timezone
from src.app.dumper import PostgreSQLDumper
from src.app.models import connection_scope
from src.app.transformer import Transformer
from src.app.repository import Repository
from collections import deque
from src.app.http_client import HTTPClient
from bs4 import BeautifulSoup


def extract_useful_links(soup_or_html):
    """Extract phone, website, and email from a 'Useful Links' block (BeautifulSoup or HTML string).
    Returns dict with keys: phone, website, email (value None if not found)."""
    soup = soup_or_html if isinstance(soup_or_html, BeautifulSoup) else BeautifulSoup(soup_or_html, "html.parser")
    phone = website = email = None
    wrapper = soup.find("div", class_="events_useful-links-wrapper")
    if not wrapper:
        return {"phone": None, "website": None, "email": None}
    for a in wrapper.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if href.startswith("tel:"):
            phone = href.removeprefix("tel:").strip()
        elif href.startswith("mailto:"):
            email = href.removeprefix("mailto:").strip()
        elif href.startswith("http"):
            website = href
    return {"phone": phone, "website": website, "email": email}


def _dedupe_events_by_link(events: list[dict]) -> list[dict]:
    """Merge duplicate events that share the same event_link (e.g. recurring listings).
    Keeps one record per event_link with the earliest start_date and latest end_date."""
    by_link: dict[str, list[dict]] = {}
    for e in events:
        link = e.get("event_link") or ""
        by_link.setdefault(link, []).append(e)
    out = []
    for link, group in by_link.items():
        if not group:
            continue
        base = dict(group[0])
        if len(group) == 1:
            out.append(base)
            continue
        start_dates = [e.get("start_date") for e in group if e.get("start_date")]
        end_dates = [e.get("end_date") for e in group if e.get("end_date")]
        if start_dates:
            base["start_date"] = min(start_dates)
        if end_dates:
            base["end_date"] = max(end_dates)
        out.append(base)
    return out



URL = "https://lf0ccfqrh3-dsn.algolia.net/1/indexes/*/queries"

HEADERS = {
    "x-algolia-application-id": "LF0CCFQRH3",
    "x-algolia-api-key": "9ff98e053974ef9b01af86dfe17897f7",
    "content-type": "application/json",
    "x-algolia-agent": "Algolia for JavaScript (4.24.0); Browser; instantsearch.js (4.88.0); JS Helper (3.27.1)",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Referer": "https://www.visitarizona.com/",
}

def fetch_page(page):
    payload = {
        "requests": [
            {
                "indexName": "events_cms_items",
                "params": f"query=&page={page}&hitsPerPage=9"
            }
        ]
    }
    res = requests.post(URL, headers=HEADERS, json=payload)
    return res.json()


def extract_events(data):
    hits = data["results"][0]["hits"]
    return [
        {
            "title": h["Name"],
            "location": h.get("locationName"),
            "event_link": "https://www.visitarizona.com" + h["webflowLink"],
            "description": h["description"],
            "image_url": h['thumbnailImage'],
            "start_date": datetime.date(h["startYear"], h["startMonth"], h["startDay"]),
            "end_date": datetime.date(h["endYear"], h["endMonth"], h["endDay"]),
            "start_time": datetime.datetime.fromtimestamp(h["startTimestamp"], tz=datetime.timezone.utc),
            "end_time": datetime.datetime.fromtimestamp(h["endTimestamp"], tz=datetime.timezone.utc),
            'address': h['locationName'],
            'scraped_at': datetime.datetime.now(timezone.utc).isoformat(),
        }
        for h in hits
    ]


# --- Run ---
print("Starting Arizona events script...")
print("[1/6] Fetching first page (to get total page count)...")
first = fetch_page(0)
nb_pages = first["results"][0]["nbPages"]
print(f"[1/6] Done. Total pages: {nb_pages}")

print(f"[2/6] Fetching all pages (0 to {nb_pages - 1})...")
all_events = []
for page in range(nb_pages):
    print(f"  Fetching page {page + 1}/{nb_pages}...", flush=True)
    data = fetch_page(page)
    all_events.extend(extract_events(data))
print(f"[2/6] Done. Total events before filter: {len(all_events)}")

print("[3/6] Filtering to current events (now <= end_time)...")
now = datetime.datetime.now(datetime.timezone.utc)
all_events = [e for e in all_events if now <= e["end_time"]]
print(f"[3/6] Done. Current events: {len(all_events)}")
print("[4/6] Importing PostgreSQLDumper...")
dumper = None
repository = None
client = None
try:
    print("[4/6] Import done.")
    print("[5/6] Connecting to database...")
    with connection_scope() as session:
        dumper = PostgreSQLDumper(session=session)
        repository = Repository(session=session)
        print("[5/6] Connected.")
        print("[6/6] Dumping events to database...")
        dumper.dump_events(all_events)
        print("[6/6] Dump complete.")

        client = HTTPClient()
        transformer = Transformer()
        q = deque([e['event_link'] for e in all_events])
        while q:
            url = q.pop()
            page = client.get(url)
            soup = BeautifulSoup(page.text, 'html.parser')
            event = extract_useful_links(soup)
            events = [{
                **event,
                'event_link': url,
            }]
            print(events)
            dumper.dump_events(events)
            for event in events:
                event_link = event["event_link"]
                existing = repository.get_event_by_link(event_link)
                merged = {**(existing or {}), **event}
                transformed_event = transformer.transform_event(merged)
                dumper.upsert_event(transformed_event)
            dumper.commit()
    print("[6/6] Done.")
except Exception as e:
    print("Could not dump to database (is Postgres running on 127.0.0.1:5432?):", e)
finally:
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    if dumper is not None:
        dumper.close()
    if repository is not None:
        repository.close()
