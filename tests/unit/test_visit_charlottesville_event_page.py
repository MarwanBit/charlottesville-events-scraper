from datetime import date, time

from bs4 import BeautifulSoup

from src.app.websites import VisitCharlottesvilleEventWebsite


HTML = """
<html>
  <body>
    <div class="background-image" style="background-image:url('/images/example.jpg')"></div>
    <h1 class="page-title__heading">The World Between: Egypt and Nubia in Africa</h1>
    <p class="page-title__subheading">February 27 to June 14</p>
    <div class="text__text">
      Featuring loans from multiple museums in the U.S. and Canada, the exhibition demonstrates the
      complex interaction of different cultures in Egypt and Nubia. Open daily 10:00am to 5:00pm.
    </div>
    <div class="detail__address">
      155 Rugby Road  Charlottesville, Virginia 22904
    </div>
    <ul class="detail__info">
      <li>Contact: The Fralin Museum of Art at the University of Virginia</li>
      <li><a href="tel:(434) 924-3592">(434) 924-3592</a></li>
    </ul>
    <a class="btn dms-ext-link" href="https://www.fralin.virginia.edu/">Website</a>
  </body>
</html>
"""


def test_visit_charlottesville_event_page_world_between_dates():
  url = "https://www.visitcharlottesville.org/events/the-world-between-egypt-and-nubia-in-africa/"
  soup = BeautifulSoup(HTML, "html.parser")
  website = VisitCharlottesvilleEventWebsite(url, soup)

  events = website.get_events()
  assert events, "Expected at least one expanded event"

  # With DEFAULT_YEAR = 2026 in visit_charlottesville_date_parsing,
  # 'February 27 to June 14' should expand to one entry per calendar day.
  start = date(2026, 2, 27)
  end = date(2026, 6, 14)
  expected_len = (end - start).days + 1
  assert len(events) == expected_len

  first = events[0]
  last = events[-1]

  assert first["title"] == "The World Between: Egypt and Nubia in Africa"
  assert first["address"].startswith("155 Rugby Road")
  assert first["start_date"] == start
  assert first["end_date"] == start
  assert first["start_time"] == time(10, 0)
  assert first["end_time"] == time(17, 0)

  assert last["start_date"] == end
  assert last["end_date"] == end
  assert last["start_time"] == time(10, 0)
  assert last["end_time"] == time(17, 0)

