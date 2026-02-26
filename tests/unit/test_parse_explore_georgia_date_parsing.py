"""Unit tests for Explore Georgia date parsing. Import is deferred so pytest collection stays fast."""
from datetime import date, time
from pathlib import Path

# Project root on path when run as script (python tests/unit/test_parse_explore_georgia_date_parsing.py)
_root = Path(__file__).resolve().parent.parent.parent
if _root not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_root))


def test_parse_event_datetime_range_single_range():
    """Single time range returns one tuple (start_date, end_date, start_time, end_time)."""
    from src.app.explore_georgia_parsing import parse_event_datetime_range

    test_str = "Saturday, February 28, 2026 9:00am - 10:00am"
    res = parse_event_datetime_range(test_str)
    assert res == (
        date(2026, 2, 28),
        date(2026, 2, 28),
        time(9, 0, 0),
        time(10, 0, 0),
    )

def test_parse_event_datetime_range_multiple_ranges_merged():
    """Multiple time ranges on same day are merged to earliest start and latest end."""
    from src.app.explore_georgia_parsing import parse_event_datetime_range

    test_str = "Saturday, February 28, 2026 1:00pm - 2:00pm 2:30pm - 3:30pm"
    res = parse_event_datetime_range(test_str)
    assert res == (
        date(2026, 2, 28),
        date(2026, 2, 28),
        time(13, 0, 0),
        time(15, 30, 0),
    )


if __name__ == "__main__":
    """Run tests without pytest (avoids slow collection when disk is full or I/O is slow)."""
    test_parse_event_datetime_range_single_range()
    test_parse_event_datetime_range_multiple_ranges_merged()
    print("All 2 tests passed.")