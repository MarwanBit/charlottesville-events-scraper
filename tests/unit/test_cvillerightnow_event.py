"""Cville Right Now / CitySpark detail page: multi-date -> multiple event dicts."""

from datetime import time

from bs4 import BeautifulSoup

from src.app.websites.cvillerightnow import (
    CvilleRightNowEventWebsite,
    _date_time_from_spark_url_tail,
    _parse_schedule_row,
)


def test_get_events_emits_one_dict_per_additional_date():
    html = """
    <div class="csEvHolder">
      <div class="csName csSegment">Photo Exhibit at Westminster Canterbury</div>
      <div class="csDates csSegment">
        <div>
          <span>Sun, Apr 05, 2026</span>
          <span> , <span>8:00am</span><span>-4:00pm</span></span>
        </div>
      </div>
      <div class="csAdditionalDates">
        <div class="cs-bold">Additional Dates</div>
        <div><div>
          <span>Mon, Apr 06, 2026</span><span>,&nbsp;8:00am</span><span>-4:00pm</span>
        </div></div>
        <div><div>
          <span>Tue, Apr 07, 2026</span><span>,&nbsp;8:00am</span><span>-4:00pm</span>
        </div></div>
      </div>
      <div class="csLocation csSegment">
        <div><a href="#/show?search=Venue">Westminster Canterbury</a></div>
        <div><div>250 Pantops Mountain Rd.</div><div>Charlottesville, VA</div></div>
      </div>
      <div class="csSegment csDescription">
        <div class="csText"><p>Exhibit description here.</p></div>
      </div>
      <div class="csMoreInfo">
        <p><a class="csPillLink" href="https://www.example.org/">Visit Event Website</a></p>
        <div class="csContact">
          <div class="cs-bold">Event Contact</div>
          <div></div>
          <div>Glenn Nash</div>
          <div>glenn@example.com</div>
          <div>(704) 619-3962</div>
        </div>
      </div>
    </div>
    """
    url = (
        "https://www.cvillerightnow.com/events/"
        "#/details/photo-exhibit/18337948/2026-04-05T08"
    )
    site = CvilleRightNowEventWebsite(url, soup=BeautifulSoup(html, "html.parser"))
    events = site.get_events(None)
    assert len(events) == 3
    links = {e["event_link"] for e in events}
    assert any("2026-04-05T08" in lk for lk in links)
    assert any("2026-04-06T08" in lk for lk in links)
    assert any("2026-04-07T08" in lk for lk in links)
    titles = {e["title"] for e in events}
    assert titles == {"Photo Exhibit at Westminster Canterbury"}
    assert events[0]["website"] == "https://www.example.org/"
    assert "250 Pantops Mountain Rd." in events[0]["address"]
    assert events[0]["email"] == "glenn@example.com"


def test_parse_schedule_row_single_start_time_no_end():
    """CitySpark often shows only start (e.g. 8:00pm) with no range."""
    html = """<div>
      <span>Thu, Apr 10, 2026</span>
      <span> , <span>8:00pm</span></span>
    </div>"""
    row = BeautifulSoup(html, "html.parser").div
    d, st, et = _parse_schedule_row(row)
    assert d.isoformat() == "2026-04-10"
    assert st is not None and st.hour == 20 and st.minute == 0
    assert et is None


def test_time_from_url_tail_t20_is_8pm():
    td, tt = _date_time_from_spark_url_tail("2026-04-10T20")
    assert td and td.isoformat() == "2026-04-10"
    assert tt == time(20, 0, 0)


def test_get_events_fills_start_time_from_url_when_dom_missing_time():
    """If schedule text omits a range, fragment T20 still yields 20:00."""
    html = """
    <div class="csEvHolder">
      <div class="csName csSegment">Speidel Goodrich Goggin Lille</div>
      <div class="csDates csSegment">
        <div><span>Thu, Apr 10, 2026</span><span> (doors)</span></div>
      </div>
    </div>
    """
    url = "https://www.cvillerightnow.com/events/#/details/speidel-goodrich/17485366/2026-04-10T20"
    site = CvilleRightNowEventWebsite(url, soup=BeautifulSoup(html, "html.parser"))
    events = site.get_events(None)
    assert len(events) == 1
    assert events[0]["start_time"] == "20:00:00"


def test_detail_title_skips_shell_h1_and_uses_slug_fallback():
    """When only WP shell is present, do not use h1 'Events'; use URL slug."""
    html = "<html><body><main><h1>Events</h1></main></body></html>"
    url = "https://www.cvillerightnow.com/events/#/details/learn-rugby/17492789/2026-07-02T18"
    soup = BeautifulSoup(html, "html.parser")
    title = CvilleRightNowEventWebsite._detail_title(soup, url)
    assert title == "Learn Rugby"
