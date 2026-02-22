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
from src.app.http_client import HTTPClient

@pytest.fixture
def client():
    return HTTPClient()


@pytest.fixture
def resolver():
    return URLResolver()

@pytest.fixture()
def excel_dumper():
    return ExcelDumper()

