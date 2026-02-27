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
    from .discover_durham import DiscoverDurhamWebsite
    from .visit_charlottesville import VisitCharlottesvilleWebsite, VisitCharlottesvilleEventWebsite
    from .washington import WashingtonWebsite, WashingtonEventWebsite
    from .explore_georgia import ExploreGeorgiaWebsite, ExploreGeorgiaEventWebsite
    from .visit_ma import VisitMAWebsite, VisitMAEventWebsite
    from .enjoy_illinois import EnjoyIllinoisWebsite, EnjoyIllinoisEventWebsite
    from .texas_time_travel import TexasTimeTravelWebsite, TexasTimeTravelEventWebsite
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
    ]
