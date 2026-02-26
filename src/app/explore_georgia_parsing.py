"""
Pure parsing helpers for Explore Georgia date/datetime strings.
No heavy deps (no dateparser, bs4, requests) so unit tests can import this for fast runs.
"""

from datetime import date, datetime, time
import re


def _normalize_for_date_parse(s: str) -> str:
    """Reduce to 'Month DD, YYYY' for strptime with %B %d, %Y. Handles 'Sunday, March 8, 202612:00am' etc."""
    s = (s or "").strip()
    s = re.sub(r"(\d{4})(\d)(?=:\d)", r"\1 \2", s)
    s = re.sub(r"^[A-Za-z]+,\s*", "", s)
    s = re.sub(r"\s+\d{1,2}:\d{2}\s*(?:am|pm)\s*$", "", s, flags=re.I).strip()
    return s


def parse_date_range(text: str) -> tuple[date | None, date | None]:
    """Parse e.g. 'February 25, 2026 - March 6, 2026' or 'Sunday, March 8, 202612:00am - Monday, March 9, 2026'."""
    match = re.match(r"(.+?)\s*-\s*(.+)", text)
    if not match:
        return None, None

    start_str = _normalize_for_date_parse(match.group(1))
    end_str = _normalize_for_date_parse(match.group(2))
    fmt = "%B %d, %Y"

    try:
        start_dt = datetime.strptime(start_str, fmt)
        end_dt = datetime.strptime(end_str, fmt)
        return start_dt.date(), end_dt.date()
    except ValueError:
        return None, None


ALL_DAY_START = time(0, 0)
ALL_DAY_END = time(23, 59, 59)


def _normalize_datetime_str(s: str) -> str:
    """Prepare datetime string for strptime: fix year-time spacing and normalize am/pm."""
    s = (s or "").strip()
    s = re.sub(r"(\d{4})(\d{1,2})(?=:\d{2})", r"\1 \2", s)
    s = re.sub(r"\b(am|pm)\b", lambda m: m.group(1).upper(), s, flags=re.I)
    return s


def parse_event_datetime_range(
    s: str,
) -> tuple[date | None, date | None, time | None, time | None]:
    """Parse e.g. 'Saturday, April 4, 2026 7:00pm - 9:00pm' into start_date, end_date, start_time, end_time.
    Multiple time ranges on one day are merged into one event (earliest start, latest end).
    Date-only returns all-day (00:00–23:59:59)."""
    s_normalized = _normalize_datetime_str(s or "")
    if not s_normalized:
        return None, None, None, None
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
    time_range_pat = re.compile(
        r"(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)",
        re.IGNORECASE,
    )
    ranges = time_range_pat.findall(s_normalized)
    if ranges:
        date_prefix = time_range_pat.sub("", s_normalized).strip()
        try:
            start_date = datetime.strptime(date_prefix, "%A, %B %d, %Y").date()
        except ValueError:
            start_date = None
        if start_date is not None:
            times = []
            for start_t, end_t in ranges:
                try:
                    t0 = datetime.strptime(start_t.strip(), "%I:%M%p").time()
                    t1 = datetime.strptime(end_t.strip(), "%I:%M%p").time()
                    times.append((t0, t1))
                except ValueError:
                    continue
            if times:
                start_time = min(t[0] for t in times)
                end_time = max(t[1] for t in times)
                return start_date, start_date, start_time, end_time
    try:
        start_dt = datetime.strptime(s_normalized, "%A, %B %d, %Y %I:%M%p")
        return start_dt.date(), start_dt.date(), start_dt.time(), ALL_DAY_END
    except ValueError:
        pass
    s_date_only = re.sub(
        r"\s+\d{1,2}:\d{2}\s*(?:am|pm)\s*$", "", s_normalized, flags=re.I
    ).strip()
    try:
        start_date = datetime.strptime(s_date_only, "%A, %B %d, %Y").date()
        return start_date, start_date, ALL_DAY_START, ALL_DAY_END
    except ValueError:
        return None, None, None, None
