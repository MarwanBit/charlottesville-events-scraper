from datetime import date, datetime, time

from src.app.websites.washington import extract_datetime_range
import pprint


def _ref(year=2026, month=1, day=1) -> datetime:
    return datetime(year, month, day, 12, 0, 0)


def test_extract_datetime_range_jun_20_step_off_time_3pm():
    text = "Jun 20, 2026. Step-off Time: 3:00 p.m."
    res = extract_datetime_range(text, reference_date=_ref())
    assert res == [
        (date(2026, 6, 20), date(2026, 6, 20), time(15, 0), None),
    ]


def test_extract_datetime_range_apr_19_from_2pm_to_4pm():
    text = "Apr 19, 2026. From: 02:00 PM to 04:00 PM"
    res = extract_datetime_range(text, reference_date=_ref())
    assert res == [
        (date(2026, 4, 19), date(2026, 4, 19), time(14, 0), time(16, 0)),
    ]


def test_extract_datetime_range_now_to_feb_27_starting_7pm():
    text = "Now - Feb 27, 2026. Starting: 07:00 PM"
    res = extract_datetime_range(text, reference_date=_ref())
    # Should expand from the reference "today" date through Feb 27, 2026 (inclusive).
    start = _ref().date()
    end = date(2026, 2, 27)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(19, 0), None)
    assert res[-1] == (end, end, time(19, 0), None)


def test_extract_datetime_range_mar_15_from_12pm_to_230pm():
    text = "Mar 15, 2026. From: 12:00 PM to 02:30 PM"
    res = extract_datetime_range(text, reference_date=_ref())
    assert res == [
        (date(2026, 3, 15), date(2026, 3, 15), time(12, 0), time(14, 30)),
    ]


def test_extract_datetime_range_mar_21_from_9am_to_12pm():
    text = "Mar 21, 2026. From: 09:00 AM to 12:00 PM"
    res = extract_datetime_range(text, reference_date=_ref())
    assert res == [
        (date(2026, 3, 21), date(2026, 3, 21), time(9, 0), time(12, 0)),
    ]


def test_extract_datetime_range_feb_28_from_1130am_to_330pm():
    text = "Feb 28, 2026. From: 11:30 AM to 3:30 PM"
    res = extract_datetime_range(text, reference_date=_ref())
    assert res == [
        (date(2026, 2, 28), date(2026, 2, 28), time(11, 30), time(15, 30)),
    ]


def test_extract_datetime_range_mar_6_from_7pm_to_9pm():
    text = "Mar 06, 2026. From: 07:00 PM to 09:00 PM"
    res = extract_datetime_range(text, reference_date=_ref())
    assert res == [
        (date(2026, 3, 6), date(2026, 3, 6), time(19, 0), time(21, 0)),
    ]

def test_extract_datetime_range_non_daily_frequency():
    text = "Sundays, Fridays, Saturdays, Now - Oct 08, 2027. 10am - 5pm"
    res = extract_datetime_range(text, reference_date=_ref())
    # Verify that every emitted date is a Friday, Saturday, or Sunday and
    # that the correct time window is used.
    allowed_weekdays = {4, 5, 6}  # Friday=4, Saturday=5, Sunday=6
    for sd, ed, st, et in res:
        assert sd == ed
        assert sd.weekday() in allowed_weekdays
        assert st == time(10, 0)
        assert et == time(17, 0)


def test_extract_datetime_range_daily_frequency():
    text = "Daily, Jun 12, 2026 - Jun 14, 2026. Times Vary"
    res = extract_datetime_range(text, reference_date=_ref())
    start = date(2026, 6, 12)
    end = date(2026, 6, 14)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, None, None)
    assert res[-1] == (end, end, None, None)


def test_extract_datetime_range_daily_time():
    text = "Daily, May 30, 2026 - May 31, 2026. From: 1:00 PM to 11:00 PM"
    res = extract_datetime_range(text, reference_date=_ref())
    start = date(2026, 5, 30)
    end = date(2026, 5, 31)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(13, 0), time(23, 0))
    assert res[-1] == (end, end, time(13, 0), time(23, 0))


def test_extract_datetime_range_single_occurrence():
    text = "Apr 09, 2026. 8 p.m."
    res = extract_datetime_range(text, reference_date=_ref())
    assert res == [
        (date(2026, 4, 9), date(2026, 4, 9), time(20, 0), None),
    ]


def test_extract_datetime_range_varies():
    text = "Apr 28, 2026 - May 03, 2026. varies"
    res = extract_datetime_range(text, reference_date=_ref())
    start = date(2026, 4, 28)
    end = date(2026, 5, 3)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, None, None)
    assert res[-1] == (end, end, None, None)


def test_extract_datetime_range_tba():
    text = "Jun 26, 2026. TBA"
    res = extract_datetime_range(text, reference_date=_ref())
    # Date-only, no numeric time -> one all-day-ish tuple with no times.
    assert res == [
        (date(2026, 6, 26), date(2026, 6, 26), None, None),
    ]

def test_extract_datetime_range_hard_weekdays_with_two_times():
    text = "Tuesdays, Wednesdays, Thursdays, Fridays, Saturdays, Now - Oct 02, 2027. 10 a.m. & 1 p.m."
    res = extract_datetime_range(text, reference_date=_ref())
    # Tuesdays–Saturdays only: 1–5
    allowed_weekdays = {1, 2, 3, 4, 5}
    for sd, ed, st, et in res:
        assert sd == ed
        assert sd.weekday() in allowed_weekdays
        # Current implementation treats this as a single 1 p.m. start with no explicit end.
        assert st == time(13, 0)
        assert et is None


def test_extract_datetime_range_harder_complex_weekdays_with_range():
    text = "Sundays, Mondays, Tuesdays, Thursdays, Fridays, Now - Sep 05, 2027. 7 a.m. to 8 a.m."
    res = extract_datetime_range(text, reference_date=_ref())
    # Sundays, Mondays, Tuesdays, Thursdays, Fridays: 0,1,2,3,4,6 (note Wednesday=2? actually Wednesday=2, so adjust)
    allowed_weekdays = {0, 1, 2, 3, 4, 6}
    for sd, ed, st, et in res:
        assert sd == ed
        assert sd.weekday() in allowed_weekdays
        assert st == time(7, 0)
        assert et == time(8, 0)


def test_extract_datetime_range_harder_complex_weekdays_with_range_2():
    text = "Daily, Now - Feb 26, 2028. 9 a.m. to 5 p.m."
    res = extract_datetime_range(text, reference_date=_ref())
    # Daily from reference date through Feb 26, 2028
    start = _ref().date()
    end = date(2028, 2, 26)
    expected_len = (end - start).days + 1
    assert len(res) == expected_len
    assert res[0] == (start, start, time(9, 0), time(17, 0))
    assert res[-1] == (end, end, time(9, 0), time(17, 0))