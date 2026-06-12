# Only light imports at top level so "from src.app.websites import ..." doesn't stall.
# Heavy modules are loaded lazily via get_resolver_map() or __getattr__.
from .base import EventsWebsite

__all__ = [
    "EventsWebsite",
    "get_resolver_map",
    "extract_datetime_range",
    "VisitMAEventWebsite",
    "VisitMAWebsite",
    "VisitCharlottesvilleEventWebsite",
    "VisitCharlottesvilleWebsite",
    "DiscoverDurhamWebsite",
    "WashingtonWebsite",
    "WashingtonEventWebsite",
    "ExploreGeorgiaWebsite",
    "ExploreGeorgiaEventWebsite",
    "EnjoyIllinoisWebsite",
    "EnjoyIllinoisEventWebsite",
    "TexasTimeTravelWebsite",
    "TexasTimeTravelEventWebsite",
    "ILoveNYWebsite",
    "ILoveNYEventWebsite",
    "IndieShortFilmFestivalWebsite",
    "IndieShortFilmFestivalEventWebsite",
    "TomTomFestivalWebsite",
    "TomTomFestivalEventWebsite",
    "MiddleburyWebsite",
    "MiddleburyEventWebsite",
    "AddisonIndependentWebsite",
    "TheParamountWebsite",
    "TheParamountEventWebsite",
    "CharlottesvilleFamilyWebsite",
    "CharlottesvilleFamilyEventWebsite",
    "CvilleRightNowWebsite",
    "CvilleRightNowEventWebsite",
    "CharlottesvilleEventbriteWebsite",
    "CharlottesvilleEventbriteEventWebsite",
    "MexicoCityEventbriteWebsite",
    "FrontPorchvilleWebsite",
]


def __getattr__(name):
    """Lazy load heavy website modules when someone does 'from src.app.websites import X'."""
    if name == "extract_datetime_range":
        from .washington import extract_datetime_range
        return extract_datetime_range
    # Individual class access loads one module
    _modules = {
        "DiscoverDurhamWebsite": (".discover_durham", "DiscoverDurhamWebsite"),
        "VisitCharlottesvilleWebsite": (".visit_charlottesville", "VisitCharlottesvilleWebsite"),
        "VisitCharlottesvilleEventWebsite": (".visit_charlottesville", "VisitCharlottesvilleEventWebsite"),
        "WashingtonWebsite": (".washington", "WashingtonWebsite"),
        "WashingtonEventWebsite": (".washington", "WashingtonEventWebsite"),
        "ExploreGeorgiaWebsite": (".explore_georgia", "ExploreGeorgiaWebsite"),
        "ExploreGeorgiaEventWebsite": (".explore_georgia", "ExploreGeorgiaEventWebsite"),
        "VisitMAWebsite": (".visit_ma", "VisitMAWebsite"),
        "VisitMAEventWebsite": (".visit_ma", "VisitMAEventWebsite"),
        "EnjoyIllinoisWebsite": (".enjoy_illinois", "EnjoyIllinoisWebsite"),
        "EnjoyIllinoisEventWebsite": (".enjoy_illinois", "EnjoyIllinoisEventWebsite"),
        "TexasTimeTravelWebsite": (".texas_time_travel", "TexasTimeTravelWebsite"),
        "TexasTimeTravelEventWebsite": (".texas_time_travel", "TexasTimeTravelEventWebsite"),
        "ILoveNYWebsite": (".i_love_ny", "ILoveNYWebsite"),
        "ILoveNYEventWebsite": (".i_love_ny", "ILoveNYEventWebsite"),
        "IndieShortFilmFestivalWebsite": ('.indie_short_film_festival', 'IndieShortFilmFestivalWebsite'),
        "IndieShortFilmFestivalEventWebsite": ('.indie_short_film_festival', 'IndieShortFilmFestivalEventWebsite'),
        "TomTomFestivalWebsite": ('.tomtomfestival', 'TomTomFestivalWebsite'),
        "TomTomFestivalEventWebsite": ('.tomtomfestival', 'TomTomFestivalEventWebsite'),
        "MiddleburyWebsite": ('.middlebury', 'MiddleburyWebsite'),
        "MiddleburyEventWebsite": ('.middlebury', 'MiddleburyEventWebsite'),
        "AddisonIndependentWebsite": (".addison_independent", "AddisonIndependentWebsite"),
        "TheParamountWebsite": (".the_paramount", "TheParamountWebsite"),
        "TheParamountEventWebsite": (".the_paramount", "TheParamountEventWebsite"),
        "CharlottesvilleFamilyWebsite": (".charlottesvillefamily", "CharlottesvilleFamilyWebsite"),
        "CharlottesvilleFamilyEventWebsite": (".charlottesvillefamily", "CharlottesvilleFamilyEventWebsite"),
        "CvilleRightNowWebsite": (".cvillerightnow", "CvilleRightNowWebsite"),
        "CvilleRightNowEventWebsite": (".cvillerightnow", "CvilleRightNowEventWebsite"),
        "CharlottesvilleEventbriteWebsite": (".charlottesville_eventbrite", "CharlottesvilleEventbriteWebsite"),
        "CharlottesvilleEventbriteEventWebsite": (".charlottesville_eventbrite", "CharlottesvilleEventbriteEventWebsite"),
        "MexicoCityEventbriteWebsite": (".mexico_cityeventbrite", "MexicoCityEventbriteWebsite"),
        "FrontPorchvilleWebsite": (".frontporchville", "FrontPorchvilleWebsite"),
    }
    if name in _modules:
        mod_path, attr = _modules[name]
        from importlib import import_module
        mod = import_module(mod_path, package=__name__)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_resolver_map():
    """Import all website modules and return [(regex, website_class), ...]. Call this on first resolve()."""
    import re
    from . import discover_durham
    from . import visit_charlottesville
    from . import washington
    from . import explore_georgia
    from . import visit_ma
    from . import enjoy_illinois
    from . import texas_time_travel
    from . import i_love_ny
    from . import indie_short_film_festival
    from . import tomtomfestival
    from . import middlebury
    from . import the_paramount
    from . import charlottesvillefamily
    from . import charlottesville_eventbrite
    from . import mexico_cityeventbrite
    from . import frontporchville
    from .discover_durham import DiscoverDurhamWebsite
    from .visit_charlottesville import VisitCharlottesvilleWebsite, VisitCharlottesvilleEventWebsite
    from .washington import WashingtonWebsite, WashingtonEventWebsite
    from .explore_georgia import ExploreGeorgiaWebsite, ExploreGeorgiaEventWebsite
    from .visit_ma import VisitMAWebsite, VisitMAEventWebsite
    from .enjoy_illinois import EnjoyIllinoisWebsite, EnjoyIllinoisEventWebsite
    from .texas_time_travel import TexasTimeTravelWebsite, TexasTimeTravelEventWebsite
    from .i_love_ny import ILoveNYWebsite, ILoveNYEventWebsite
    from .indie_short_film_festival import IndieShortFilmFestivalWebsite, IndieShortFilmFestivalEventWebsite
    from .tomtomfestival import TomTomFestivalWebsite, TomTomFestivalEventWebsite
    from .middlebury import MiddleburyWebsite, MiddleburyEventWebsite
    from .addison_independent import AddisonIndependentWebsite
    from .the_paramount import TheParamountWebsite, TheParamountEventWebsite
    from .charlottesvillefamily import CharlottesvilleFamilyWebsite, CharlottesvilleFamilyEventWebsite
    from .cvillerightnow import CvilleRightNowWebsite, CvilleRightNowEventWebsite
    from .charlottesville_eventbrite import CharlottesvilleEventbriteWebsite, CharlottesvilleEventbriteEventWebsite
    from .mexico_cityeventbrite import MexicoCityEventbriteWebsite
    from .frontporchville import FrontPorchvilleWebsite
    # Event detail pages may use regional hosts (eventbrite.sg, eventbrite.co.uk, …), not only .com.
    _eventbrite_event_host = (
        r"(?:www\.)?eventbrite\.(?:(?:com)(?:\.[a-z]{2})?|[a-z]{2}(?:\.[a-z]{2})?)"
    )
    return [
        (re.compile(r"^https:\/\/www\.discoverdurham\.com\/events\/?(?:\?page=\d+)?&?$"), DiscoverDurhamWebsite),
        (re.compile(r"^https:\/\/www\.visitcharlottesville\.org\/events\/?(?:\?page=\d+)?&?$"), VisitCharlottesvilleWebsite),
        (re.compile(r"^https:\/\/www\.visitcharlottesville\.org\/events\/[A-Za-z0-9\u00C0-\u017F\-]+\/?&?$"), VisitCharlottesvilleEventWebsite),
        (re.compile(r"^https:\/\/washington\.org\/find-dc-listings\/events(?:\?page=\d+)?$"), WashingtonWebsite),
        (re.compile(r"^https://washington\.org/event/[a-z0-9-]+$"), WashingtonEventWebsite),
        (re.compile(r"^https://www\.visitma\.com/events/?(\?.*)?$"), VisitMAWebsite),
        (re.compile(r"^https://www\.visitma\.com/event/[0-9]+/?$"), VisitMAEventWebsite),
        (re.compile(r"^https:\/\/exploregeorgia\.org\/calendar-of-events(?:\?page=\d+)?$"), ExploreGeorgiaWebsite),
        (re.compile(r"^https:\/\/exploregeorgia\.org\/[^\/]+\/events\/[^\/]+(?:\/[^\/]+)?$"), ExploreGeorgiaEventWebsite),
        (re.compile(r"^https:\/\/www\.enjoyillinois\.com\/things-to-do\/festivals-and-events\/?(?:\?.*)?$"), EnjoyIllinoisWebsite),
        (re.compile(r"^https://www\.enjoyillinois\.com/things-to-do/festivals-and-events/listing/([a-z0-9-]+)/?$"), EnjoyIllinoisEventWebsite),
        (re.compile(r"^https://texastimetravel\.com/events/?(?:\?page=\d+)?&?$"), TexasTimeTravelWebsite),
        (re.compile(r"^https://texastimetravel\.com/events/[a-z0-9-]+/?$"), TexasTimeTravelEventWebsite),
        (re.compile(r"^https?:\/\/(www\.)?iloveny\.com\/events\/(\?.*)?$"), ILoveNYWebsite),
        (re.compile(r"^https?:\/\/(www\.)?iloveny\.com\/event\/[^\/]+\/[^\/]+\/?$"), ILoveNYEventWebsite),
        (re.compile(r"https://isff2026.eventive.org/films"), IndieShortFilmFestivalWebsite),
        (re.compile(r"^https://isff2026\.eventive\.org/films/[^/?#]+/?(?:\?.*)?$"), IndieShortFilmFestivalEventWebsite),
        (re.compile(r"^https://tomtomfestival2026\.sched\.com/list/simple$"), TomTomFestivalWebsite),
        # Sched event URLs are /event/{id}/{slug}; allow slashes in the path (not just a single segment).
        (re.compile(r"^https://tomtomfestival2026\.sched\.com/event/[^?#]+/?(?:\?.*)?$"), TomTomFestivalEventWebsite),
        (re.compile(r"^https://(?:www\.)?middlebury\.edu/events/?(?:\?page=\d+)?&?$"), MiddleburyWebsite),
        # Middlebury event detail pages look like: /events/event/<OTHER STUFF>
        (re.compile(r"^https://(?:www\.)?middlebury\.edu/events/event/[^?#]+/?(?:\?.*)?$"), MiddleburyEventWebsite),
        (re.compile(r"^https://www\.addisonindependent\.com/calendar/?(?:\?.*)?$"), AddisonIndependentWebsite),
        # Listing: /events/ ; detail: /event/{slug}/ (singular). Host may be www or bare.
        (re.compile(r"^https://(?:www\.)?theparamount\.net/events/?(?:\?.*)?$"), TheParamountWebsite),
        (re.compile(r"^https://(?:www\.)?theparamount\.net/event/[^?#]+/?(?:\?.*)?$"), TheParamountEventWebsite),
        (re.compile(
            r"^https://(?:www\.)?charlottesvillefamily\.com/top-family-events/?(?:\?.*)?$"
        ), CharlottesvilleFamilyWebsite),
        (re.compile(
            r"^https://(?:www\.)?charlottesvillefamily\.com/family-events/list(?:/page/\d+)?/?(?:\?.*)?$"
        ), CharlottesvilleFamilyWebsite),
        (re.compile(
            r"^https://(?:www\.)?charlottesvillefamily\.com/event/[^?#]+/?(?:\?.*)?$"
        ), CharlottesvilleFamilyEventWebsite),
        (re.compile(
            r"^https://(?:www\.)?frontporchcville\.org/concerts/?(?:\?.*)?(?:#.*)?$"
        ), FrontPorchvilleWebsite),
        # Detail hash routes must be checked before the general /events listing (same prefix).
        (re.compile(
            r"^https://(?:www\.)?cvillerightnow\.com/events/#/details/[^?#]+/?(?:\?.*)?$"
        ), CvilleRightNowEventWebsite),
        (re.compile(
            r"^https://(?:www\.)?cvillerightnow\.com/events/#/(?!details(?:/|$|\?)).*$"
        ), CvilleRightNowWebsite),
        (re.compile(
            r"^https://(?:www\.)?eventbrite\.com/d/mexico--mexico-city/all-events/?(?:\?.*)?$"
        ), MexicoCityEventbriteWebsite),
        (re.compile(
            r"^https://(?:www\.)?eventbrite\.com/d/va--charlottesville/all-events/?(?:\?.*)?$"
        ), CharlottesvilleEventbriteWebsite),
        (re.compile(
            rf"^https://{_eventbrite_event_host}/e/[^?#]+/?(?:\?.*)?$"
        ), CharlottesvilleEventbriteEventWebsite),
    ]
