from datetime import date, datetime, time

from src.app.websites.enjoy_illinois import parse_date_range


def _ref(year=2026, month=1, day=1) -> datetime:
    return datetime(year, month, day, 12, 0, 0)


test_str = ' Saturday, Jun 6 , 2026 • 8:00am - 3:00pm '
test_str_2 = 'Saturday, Jun 6 , 2026 • 8:00am - 3:00pm'
test_str_3 = 'Saturday, Jun 6 , 2026'
test_str_4 = 'Wednesday, Jun 10 to Sunday, Jun 14, 2026 • 9:00am - 8:00pm'
test_str_5 = 'Thursday, Jul 9 to Sunday, Jul 12, 2026 • 9:00am - 10:00pm'
test_str_6 = 'Friday, Aug 14 , 2026 • 8:00pm - 11:00pm'
test_str_7 = 'Sunday, Feb 1 to Saturday, Feb 28, 2026 • 8:00am - 4:00pm'
test_str_8 = 'Friday, Feb 13 to Sunday, Feb 22, 2026'
test_str_9 = 'Saturday, Jul 19 to Thursday, Dec 31, 2026 • 9:00am - 4:00pm'
test_str_10 = 'Thursday, Mar 19 , 2026'
test_str_11 = 'Saturday, Mar 14 , 2026 • 5:00pm - 10:00pm'
test_str_12 = 'Friday, Feb 27 , 2026 • 7:00pm'


def test_parse_enjoy_illinois_1_single_day_with_time_whitespace():
    res = parse_date_range(test_str)
    assert res == [
        (date(2026, 6, 6), date(2026, 6, 6), time(8, 0), time(15, 0)),
    ]


def test_parse_enjoy_illinois_2_single_day_with_time():
    res = parse_date_range(test_str_2)
    assert res == [
        (date(2026, 6, 6), date(2026, 6, 6), time(8, 0), time(15, 0)),
    ]


def test_parse_enjoy_illinois_3_single_day_no_time():
    res = parse_date_range(test_str_3)
    assert res == [
        (date(2026, 6, 6), date(2026, 6, 6), None, None),
    ]


def test_parse_enjoy_illinois_4_range_jun_10_to_14_with_time():
    res = parse_date_range(test_str_4)
    start = date(2026, 6, 10)
    end = date(2026, 6, 14)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(9, 0), time(20, 0))
    assert res[-1] == (end, end, time(9, 0), time(20, 0))


def test_parse_enjoy_illinois_5_range_jul_9_to_12_with_time():
    res = parse_date_range(test_str_5)
    start = date(2026, 7, 9)
    end = date(2026, 7, 12)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(9, 0), time(22, 0))
    assert res[-1] == (end, end, time(9, 0), time(22, 0))


def test_parse_enjoy_illinois_6_single_day_evening():
    res = parse_date_range(test_str_6)
    assert res == [
        (date(2026, 8, 14), date(2026, 8, 14), time(20, 0), time(23, 0)),
    ]


def test_parse_enjoy_illinois_7_range_feb_1_to_28():
    res = parse_date_range(test_str_7)
    start = date(2026, 2, 1)
    end = date(2026, 2, 28)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(8, 0), time(16, 0))
    assert res[-1] == (end, end, time(8, 0), time(16, 0))


def test_parse_enjoy_illinois_8_range_feb_13_to_22_no_time():
    res = parse_date_range(test_str_8)
    start = date(2026, 2, 13)
    end = date(2026, 2, 22)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, None, None)
    assert res[-1] == (end, end, None, None)


def test_parse_enjoy_illinois_9_range_jul_19_to_dec_31():
    res = parse_date_range(test_str_9)
    start = date(2026, 7, 19)
    end = date(2026, 12, 31)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(9, 0), time(16, 0))
    assert res[-1] == (end, end, time(9, 0), time(16, 0))


def test_parse_enjoy_illinois_10_single_day_mar_19_no_time():
    res = parse_date_range(test_str_10)
    assert res == [
        (date(2026, 3, 19), date(2026, 3, 19), None, None),
    ]


def test_parse_enjoy_illinois_11_single_day_mar_14_evening():
    res = parse_date_range(test_str_11)
    assert res == [
        (date(2026, 3, 14), date(2026, 3, 14), time(17, 0), time(22, 0)),
    ]


def test_parse_enjoy_illinois_12_single_day_single_time_only():
    """Single time with no end time (e.g. '7:00pm' only)."""
    res = parse_date_range(test_str_12)
    assert res == [
        (date(2026, 2, 27), date(2026, 2, 27), time(19, 0), None),
    ]

