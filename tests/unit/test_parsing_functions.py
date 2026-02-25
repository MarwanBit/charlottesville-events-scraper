from src.app.websites.get_washington_dates import parse_daily_date_range

def text_parse_daily_date_range_1():
    test_str = 'Daily, Now - Sep 07, 2026. 10 a.m. to 5 p.m.'
    res = parse_daily_date_range(test_str)