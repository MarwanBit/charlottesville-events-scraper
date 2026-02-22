from src.app.websites import extract_datetime_range
from datetime import date, time, datetime

import pytest

def test_extract_datetime_range_1():
    test_string = "Sep 13, 2026. 8 p.m."
    result = extract_datetime_range(test_string)
    assert result["start_date"] == date(2026, 9, 13)
    assert result["end_date"] is None
    assert result["start_time"] == time(20, 0)
    assert result["end_time"] is None

def test_extract_datetime_range_2():
    test_string = "Sundays, Mondays, ... , Now - Mar 09, 2026. 11 AM - 4 PM"
    result = extract_datetime_range(test_string)
    assert result["start_date"] == datetime.now().date()
    assert result["end_date"] == date(2026, 3, 9)
    assert result["start_time"] == time(11, 0)
    assert result["end_time"] == time(16, 0)

def test_extract_datetime_range_3():
    test_string = "3rd Thursdays, Now - Dec 17, 2026. 6 p.m. to 7 p.m."
    result = extract_datetime_range(test_string)
    assert result["start_date"] == datetime.now().date()
    assert result["end_date"] == date(2026, 12, 17)
    assert result["start_time"] == time(18, 0)
    assert result["end_time"] == time(19, 0)

def test_extract_datetime_range_4():
    """Text like 'Jul 11, 2026. Evening' has no numeric time (e.g. '8 p.m.'), so times are None; date part may not parse."""
    test_string = "Jul 11, 2026. Evening"
    result = extract_datetime_range(test_string)
    assert result["start_date"] == date(2026, 7, 11)
    assert result["end_date"] == None
    assert result["start_time"] == None
    assert result["end_time"] == None

def test_extract_datetime_range_5():
    """'TBA' is not a numeric time, so no time suffix is matched; date part may not parse."""
    test_string = "Jun 26, 2026. TBA"
    result = extract_datetime_range(test_string)
    assert result["start_date"] == date(2026, 6, 26)
    assert result["end_date"] == None
    assert result["start_time"] == None
    assert result["end_time"] == None

def test_extract_datetime_range_6():
    test_string = "May 10, 2026. Starting 12:00 AM"
    result = extract_datetime_range(test_string)
    assert result["start_date"] == date(2026, 5, 10)
    assert result["end_date"] == None
    assert result["start_time"] == time(0, 0)
    assert result["end_time"] == None