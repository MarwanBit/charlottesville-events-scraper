from datetime import date, datetime, time, timedelta
import re


DEFAULT_YEAR = 2026


def _parse_month_day(text: str) -> date | None:
    """Parse strings like 'February 28' into a date in DEFAULT_YEAR."""
    text = (text or "").strip()
    try:
        return datetime.strptime(f"{text} {DEFAULT_YEAR}", "%B %d %Y").date()
    except ValueError:
        return None


def _parse_time(text: str) -> time | None:
    """Parse strings like '12:00 PM' into a time object."""
    text = (text or "").strip()
    if not text:
        return None
    # Normalize things like '10am' or '10 AM' → '10:00 AM'
    m = re.match(r"^(\d{1,2})\s*([AP]M)$", text, flags=re.I)
    if m:
        hour, ampm = m.groups()
        text = f"{hour}:00 {ampm.upper()}"
    else:
        # Accept both '12:00PM' and '12:00 PM'
        text = re.sub(r"\s*([AP]M)$", r" \1", text, flags=re.I)
    try:
        return datetime.strptime(text.upper(), "%I:%M %p").time()
    except ValueError:
        return None


def parse_event_datetime_range(
    s: str,
) -> list[tuple[date | None, date | None, time | None, time | None]]:
    """
    Parse Visit Charlottesville-style date/time strings into a list of
    (start_date, end_date, start_time, end_time) tuples.

    Examples covered by tests:
    - 'February 28 12:00 PM to 2:00 PM'
    - 'March 4 9:00 PM'
    - 'February 27 7:00 PM to 8:00 PM'
    - 'March 5 to March 8 6:00 PM to 8:00 PM'
    - 'March 21'
    - 'March 4\\n9:00 PM'
    """
    s = (s or "").strip()
    # Normalize any internal whitespace (including newlines) to single spaces
    s = re.sub(r"\s+", " ", s)
    # Trim a trailing comma (e.g. 'March 21,' -> 'March 21')
    s = re.sub(r",\s*$", "", s)
    if not s:
        return [(None, None, None, None)]

    # Case 1: Multi-day range, e.g. 'March 5 to March 8 6:00 PM to 8:00 PM'
    multi_day_pattern = re.compile(
        r"^([A-Za-z]+ \d{1,2})\s+to\s+([A-Za-z]+ \d{1,2})\s+"
        r"(\d{1,2}:\d{2}\s*[AP]M)\s+to\s+(\d{1,2}:\d{2}\s*[AP]M)$",
        re.IGNORECASE,
    )
    m = multi_day_pattern.match(s)
    if m:
        start_day_str, end_day_str, start_time_str, end_time_str = m.groups()
        start_date = _parse_month_day(start_day_str)
        end_date = _parse_month_day(end_day_str)
        start_time = _parse_time(start_time_str)
        end_time = _parse_time(end_time_str)

        if start_date and end_date and start_time and end_time:
            results: list[tuple[date, date, time, time]] = []
            current = start_date
            while current <= end_date:
                results.append((current, current, start_time, end_time))
                current += timedelta(days=1)
            return results

    # Case 2: Multi-day date-only range, e.g. 'February 27 to June 14'
    multi_day_date_only_pattern = re.compile(
        r"^([A-Za-z]+ \d{1,2})\s+to\s+([A-Za-z]+ \d{1,2})$",
        re.IGNORECASE,
    )
    m = multi_day_date_only_pattern.match(s)
    if m:
        start_day_str, end_day_str = m.groups()
        start_date = _parse_month_day(start_day_str)
        end_date = _parse_month_day(end_day_str)
        if start_date and end_date:
            results: list[tuple[date, date, time | None, time | None]] = []
            current = start_date
            while current <= end_date:
                results.append((current, current, None, None))
                current += timedelta(days=1)
            return results

    # Case 3: Single day with time range,
    # e.g. 'February 28 12:00 PM to 2:00 PM'
    single_day_range_pattern = re.compile(
        r"^([A-Za-z]+ \d{1,2})\s+"
        r"(\d{1,2}:\d{2}\s*[AP]M)\s+to\s+(\d{1,2}:\d{2}\s*[AP]M)$",
        re.IGNORECASE,
    )
    m = single_day_range_pattern.match(s)
    if m:
        day_str, start_time_str, end_time_str = m.groups()
        d = _parse_month_day(day_str)
        start_time = _parse_time(start_time_str)
        end_time = _parse_time(end_time_str)
        if d and start_time and end_time:
            return [(d, d, start_time, end_time)]

    # Case 4: Single day, date-only, e.g. 'March 21'
    single_day_date_only_pattern = re.compile(
        r"^([A-Za-z]+ \d{1,2})$",
        re.IGNORECASE,
    )
    m = single_day_date_only_pattern.match(s)
    if m:
        (day_str,) = m.groups()
        d = _parse_month_day(day_str)
        if d:
            return [(d, d, None, None)]

    # Case 5: Single day + single time,
    # e.g. 'March 4 9:00 PM'
    single_day_single_time_pattern = re.compile(
        r"^([A-Za-z]+ \d{1,2})\s+(\d{1,2}:\d{2}\s*[AP]M)$",
        re.IGNORECASE,
    )
    m = single_day_single_time_pattern.match(s)
    if m:
        day_str, time_str = m.groups()
        d = _parse_month_day(day_str)
        t = _parse_time(time_str)
        if d and t:
            return [(d, d, t, None)]

    # Fallback: unparsed / unexpected format
    return [(None, None, None, None)]