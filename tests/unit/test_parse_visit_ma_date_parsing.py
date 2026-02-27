from datetime import date, datetime, time

from src.app.websites.visit_ma import extract_datetime_range


def _ref(year=2026, month=1, day=1) -> datetime:
    return datetime(year, month, day, 12, 0, 0)


test_str = "times vary depending on the day Fri, Jun 19 - Sun, Jun 28, 2026"
test_str_2 = "May 9, 2026 11 AM Sat, May 9, 2026"
test_str_3 = (
    "typically at 10:30 a.m. on Fridays Fri, Nov 21, 2025 - Fri, May 22, 2026"
)
test_str_4 = "From: 10 AM to 5 PM Sun, Mar 15, 2026"
test_str_5 = "times vary depending on the day Fri, Jul 24 - Sun, Jul 26, 2026"
test_str_6 = (
    "7:30 p.m., 2 p.m., 7:30 p.m., 1 p.m., 6:30 p.m. Fri, May 15 - Sun, May 17, 2026"
)
test_str_7 = "7:30 PM Sat, Apr 18, 2026"
test_str_8 = "10 a.m. - 4 p.m. Sat, Feb 7 - Sun, Mar 22, 2026"
test_str_9 = "9:30 AM - 4 PM Wed, Feb 18 - Sun, Mar 22, 2026"
test_str_10 = (
    "6/29, 7/6, 7/13, 7/20, 7/27, 8/3, 8/10, 8/17, 8/24, 8/31 Mon, Aug 31, 2026"
)
test_str_11 = "March 13 at 7:30 PM Fri, Mar 13, 2026"


def test_extract_visit_ma_range_1_times_vary_jun_19_to_28():
    res = extract_datetime_range(test_str, reference_date=_ref())
    start = date(2026, 6, 19)
    end = date(2026, 6, 28)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, None, None)
    assert res[-1] == (end, end, None, None)


def test_extract_visit_ma_range_2_may_9_with_time():
    res = extract_datetime_range(test_str_2, reference_date=_ref())
    assert res == [
        (date(2026, 5, 9), date(2026, 5, 9), time(11, 0), None),
    ]


def test_extract_visit_ma_range_3_fridays_1030():
    res = extract_datetime_range(test_str_3, reference_date=_ref())
    start = date(2025, 11, 21)
    end = date(2026, 5, 22)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(10, 30), None)
    assert res[-1] == (end, end, time(10, 30), None)


def test_extract_visit_ma_range_4_from_10_to_5_single_day():
    res = extract_datetime_range(test_str_4, reference_date=_ref())
    assert res == [
        (date(2026, 3, 15), date(2026, 3, 15), time(10, 0), time(17, 0)),
    ]


def test_extract_visit_ma_range_5_times_vary_jul_24_to_26():
    res = extract_datetime_range(test_str_5, reference_date=_ref())
    start = date(2026, 7, 24)
    end = date(2026, 7, 26)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, None, None)
    assert res[-1] == (end, end, None, None)


def test_extract_visit_ma_range_6_multiple_times_may_15_to_17():
    res = extract_datetime_range(test_str_6, reference_date=_ref())
    start = date(2026, 5, 15)
    end = date(2026, 5, 17)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(19, 30), None)
    assert res[-1] == (end, end, time(19, 30), None)


def test_extract_visit_ma_range_7_single_730pm():
    res = extract_datetime_range(test_str_7, reference_date=_ref())
    assert res == [
        (date(2026, 4, 18), date(2026, 4, 18), time(19, 30), None),
    ]


def test_extract_visit_ma_range_8_10_to_4_feb7_to_mar22():
    res = extract_datetime_range(test_str_8, reference_date=_ref())
    start = date(2026, 2, 7)
    end = date(2026, 3, 22)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(10, 0), None)
    assert res[-1] == (end, end, time(10, 0), None)


def test_extract_visit_ma_range_9_930_to_4_feb18_to_mar22():
    res = extract_datetime_range(test_str_9, reference_date=_ref())
    start = date(2026, 2, 18)
    end = date(2026, 3, 22)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(9, 30), None)
    assert res[-1] == (end, end, time(9, 30), None)


def test_extract_visit_ma_range_10_aug_31_only():
    res = extract_datetime_range(test_str_10, reference_date=_ref())
    assert res == [
        (date(2026, 8, 31), date(2026, 8, 31), None, None),
    ]


def test_extract_visit_ma_range_11_march_13_at_730pm():
    res = extract_datetime_range(test_str_11, reference_date=_ref())
    assert res == [
        (date(2026, 3, 13), date(2026, 3, 13), time(19, 30), None),
    ]
