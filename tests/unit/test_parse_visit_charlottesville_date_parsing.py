from datetime import date, time
from pathlib import Path

def test_parse_event_datetime_range_1():
    from src.app.visit_charlottesville_date_parsing import parse_event_datetime_range
    test_str = "February 28 12:00 PM to 2:00 PM"
    res = parse_event_datetime_range(test_str)
    assert res == [(
        date(2026, 2, 28),
        date(2026, 2, 28),
        time(12, 0, 0),
        time(14, 0, 0),
    )]

def test_parse_event_datetime_range_2():
    from src.app.visit_charlottesville_date_parsing import parse_event_datetime_range
    test_str = "March 4 9:00 PM"
    res = parse_event_datetime_range(test_str)
    assert res == [(
        date(2026, 3, 4),
        date(2026, 3, 4),
        time(21, 0, 0),
        None
    )]


def test_parse_event_datetime_range_2_multiline():
    from src.app.visit_charlottesville_date_parsing import parse_event_datetime_range
    test_str = "March 4\n9:00 PM"
    res = parse_event_datetime_range(test_str)
    assert res == [(
        date(2026, 3, 4),
        date(2026, 3, 4),
        time(21, 0, 0),
        None
    )]

def test_parse_event_datetime_range_3():
    from src.app.visit_charlottesville_date_parsing import parse_event_datetime_range
    test_str = 'February 27 7:00 PM to 8:00 PM'
    res = parse_event_datetime_range(test_str)
    assert res == [(
        date(2026, 2, 27),
        date(2026, 2, 27),
        time(19, 0, 0),
        time(20, 0, 0),
    )]

def test_parse_event_datetime_range_4():
    from src.app.visit_charlottesville_date_parsing import parse_event_datetime_range
    test_str = 'March 5 to March 8 6:00 PM to 8:00 PM'
    res = parse_event_datetime_range(test_str)
    assert res == [
        (
            date(2026, 3, 5),
            date(2026, 3, 5),
            time(18, 0, 0),
            time(20, 0, 0),
        ),
        (
            date(2026, 3, 6),
            date(2026, 3, 6),
            time(18, 0, 0),
            time(20, 0, 0),
        ),
        (
            date(2026, 3, 7),
            date(2026, 3, 7),
            time(18, 0, 0),
            time(20, 0, 0),
        ),
        (
            date(2026, 3, 8),
            date(2026, 3, 8),
            time(18, 0, 0),
            time(20, 0, 0),
        )
    ]


def test_parse_event_datetime_range_date_only():
    from src.app.visit_charlottesville_date_parsing import parse_event_datetime_range
    test_str = "March 21"
    res = parse_event_datetime_range(test_str)
    assert res == [(
        date(2026, 3, 21),
        date(2026, 3, 21),
        None,
        None,
    )]


def test_parse_event_datetime_range_date_only_trailing_comma():
    from src.app.visit_charlottesville_date_parsing import parse_event_datetime_range
    test_str = "March 21,"
    res = parse_event_datetime_range(test_str)
    assert res == [(
        date(2026, 3, 21),
        date(2026, 3, 21),
        None,
        None,
    )]