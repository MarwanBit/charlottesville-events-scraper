import requests
from config import HEADERS

def create_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s
