import re
from datetime import date, datetime, time

from bs4 import BeautifulSoup

from src.app.http_client import HybridClient


# All-day event: start at midnight, end at last second of the day
ALL_DAY_START = time(0, 0)
ALL_DAY_END = time(23, 59, 59)


def parse_event_datetime_range(s: str) -> tuple[date | None, date | None, time | None, time | None]:
    """Parse e.g. 'Saturday, April 4, 2026 7:00pm - 9:00pm' into start_date, end_date, start_time, end_time.
    If there is no time component (e.g. 'Saturday, April 4, 2026'), returns all-day: start_time=00:00, end_time=23:59:59."""
    s = (s or "").strip()
    if not s:
        return None, None, None, None
    # Site often omits space between year and time: "20267:00pm" -> "2026 7:00pm"
    s_normalized = re.sub(r"(\d{4})(\d)(?=:\d)", r"\1 \2", s)
    if " - " in s_normalized:
        parts = s_normalized.split(" - ", 1)
        start_str = parts[0].strip()
        end_str = parts[1].strip()
        try:
            start_dt = datetime.strptime(start_str, "%A, %B %d, %Y %I:%M%p")
            end_time = datetime.strptime(end_str, "%I:%M%p").time()
            start_date = start_dt.date()
            start_time = start_dt.time()
            return start_date, start_date, start_time, end_time
        except ValueError:
            pass
    # No time range or parse failed: try date-only and treat as all-day
    try:
        start_date = datetime.strptime(s.strip(), "%A, %B %d, %Y").date()
        return start_date, start_date, ALL_DAY_START, ALL_DAY_END
    except ValueError:
        return None, None, None, None

url = "https://exploregeorgia.org/jekyll-island/events/culinary-food-wine-beer/brag-winter-ride-cycling-vacation"

client = HybridClient()
try:
    response = client.get(url)
    html = response.text
finally:
    client.close()

soup = BeautifulSoup(html, "html.parser")

dates = []

for item in soup.select(".month-group .date-list-item"):
    date_text = item.select_one(".month-and-day-number").get_text(strip=True)
    print(date_text)
    start_date, end_date, start_time, end_time = parse_event_datetime_range(date_text)

    dates.append({
        'start_date': start_date,
        'end_date': end_date,
        'start_time': start_time,
        'end_time': end_time,
    })

for d in dates:
    print(d)