"""Unit tests for Explore Georgia date parsing. Import is deferred so pytest collection stays fast."""
from datetime import date, time
from pathlib import Path

def test_parse_event_datetime_range_single_range():
    """Single time range returns a list of one tuple (start_date, end_date, start_time, end_time)."""
    from src.app.explore_georgia_parsing import parse_event_datetime_range

    test_str = "Saturday, February 28, 2026 9:00am - 10:00am"
    res = parse_event_datetime_range(test_str)
    assert res == [
        (
            date(2026, 2, 28),
            date(2026, 2, 28),
            time(9, 0, 0),
            time(10, 0, 0),
        ),
    ]

def test_parse_event_datetime_range_multiple_ranges():
    """Multiple time ranges on same day return a list of one tuple per range."""
    from src.app.explore_georgia_parsing import parse_event_datetime_range

    test_str = "Saturday, February 28, 2026 1:00pm - 2:00pm 2:30pm - 3:30pm"
    res = parse_event_datetime_range(test_str)
    assert res == [
        (
            date(2026, 2, 28),
            date(2026, 2, 28),
            time(13, 0, 0),
            time(14, 0, 0),
        ),
        (
            date(2026, 2, 28),
            date(2026, 2, 28),
            time(14, 30, 0),
            time(15, 30, 0),
        ),
    ]