import sys
from pathlib import Path

# Project root so that "from src.app ..." works
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pytest
import requests
from src.app.url_resolver import URLResolver
from src.app.dumper import ExcelDumper

@pytest.fixture
def client():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


@pytest.fixture
def resolver():
    return URLResolver()

@pytest.fixture()
def excel_dumper():
    return ExcelDumper()

