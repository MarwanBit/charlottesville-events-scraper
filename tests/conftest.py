import sys
from pathlib import Path

# Project root so that "from src.app ..." works
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pytest


@pytest.fixture
def client():
    """Lazy import to avoid loading nodriver and heavy deps for tests that don't need it."""
    from src.app.http_client import HTTPClient
    return HTTPClient()


@pytest.fixture
def resolver():
    """Lazy import to avoid loading all website modules for tests that don't need it."""
    from src.app.url_resolver import URLResolver
    return URLResolver()

@pytest.fixture
def excel_dumper():
    """Lazy import so unit tests that don't use this fixture stay fast."""
    from src.app.dumper import ExcelDumper
    return ExcelDumper()

