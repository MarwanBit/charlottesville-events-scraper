import sys
from pathlib import Path

# Add project root to path so "src" resolves when this file is run directly
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import re
import requests
from datetime import date, datetime, time, timedelta
from bs4 import BeautifulSoup
import pprint


def parse_daily_date_range(
    s: str,
    *,
    from_date: date | None = None,
) -> list[dict]:
    """Parse a string like 'Daily, Now - Sep 07, 2026. 10 a.m. to 5 p.m.' into a list of dicts.

    Each dict has start_date, end_date, start_time, end_time. For a daily listing, start_date and
    end_date are the same (one entry per day from the range). 'Now' is interpreted as from_date
    (default: today).

    Returns:
        List of {"start_date": date, "end_date": date, "start_time": time, "end_time": time}.
    """
    s = (s or "").strip()
    if not s:
        return []
    from_date = from_date or date.today()

    # Split into date range part and time part: "Daily, Now - Sep 07, 2026. 10 a.m. to 5 p.m."
    parts = re.split(r"\.\s+", s, maxsplit=1)
    date_range_str = parts[0].strip()
    time_range_str = parts[1].strip() if len(parts) > 1 else ""

    # Parse end date: "Now - Sep 07, 2026" or "Sep 01, 2026 - Sep 07, 2026"
    end_date = None
    start_date_override = None
    # Match "Month DD, YYYY" at end of date range (after " - ")
    end_match = re.search(r"-\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})\s*$", date_range_str)
    if end_match:
        try:
            end_date = datetime.strptime(end_match.group(1).strip(), "%b %d, %Y").date()
        except ValueError:
            pass
    if end_date is None:
        return []

    # Start date: "Now" -> from_date; or parse first "Month DD, YYYY" if present
    if re.search(r"\bNow\b", date_range_str, re.IGNORECASE):
        start_date_override = from_date
    else:
        start_match = re.match(r"([A-Za-z]+\s+\d{1,2},\s*\d{4})", date_range_str)
        if start_match:
            try:
                start_date_override = datetime.strptime(
                    start_match.group(1).strip(), "%b %d, %Y"
                ).date()
            except ValueError:
                pass
    start_date_override = start_date_override or from_date
    if start_date_override > end_date:
        return []

    # Parse times: "10 a.m. to 5 p.m."
    start_time = time(0, 0)
    end_time = time(23, 59, 59)
    if time_range_str:
        time_norm = (
            time_range_str.replace(" a.m.", " AM").replace(" p.m.", " PM").strip()
        )
        toks = re.split(r"\s+to\s+", time_norm, flags=re.IGNORECASE)
        if len(toks) >= 2:
            try:
                start_time = datetime.strptime(toks[0].strip(), "%I %p").time()
                end_time = datetime.strptime(toks[1].strip(), "%I %p").time()
            except ValueError:
                try:
                    start_time = datetime.strptime(toks[0].strip(), "%I:%M %p").time()
                    end_time = datetime.strptime(toks[1].strip(), "%I:%M %p").time()
                except ValueError:
                    pass

    # One dict per day: start_date == end_date for each
    out = []
    d = start_date_override
    while d <= end_date:
        out.append({
            "start_date": d,
            "end_date": d,
            "start_time": start_time,
            "end_time": end_time,
        })
        d += timedelta(days=1)
    return out

url = "https://washington.org/event/dead-sea-scrolls"

# Try requests first (fast); use browser only if blocked
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
print("Fetching page...", flush=True)
resp = requests.get(url, headers=headers, timeout=15)
html = resp.text
# If Cloudflare challenge or 403, fall back to browser
if resp.status_code == 403 or "just a moment" in html.lower() or "enable javascript and cookies" in html.lower():
    print("Using browser (site requires it)...", flush=True)
    from src.app.http_client import HybridClient
    client = HybridClient()
    try:
        resp = client.get(url)
        html = resp.text
    finally:
        client.close()
print("Done.", flush=True)

soup = BeautifulSoup(html, "html.parser")



date_text = soup.select_one('div.deal-validity').get_text(strip=True)
out = parse_daily_date_range(date_text)

pprint.pprint(out)