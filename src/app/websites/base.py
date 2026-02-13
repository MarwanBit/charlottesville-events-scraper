from abc import ABC, abstractmethod
from bs4 import BeautifulSoup
import requests
from typing import Optional, List, Dict

class EventsWebsite(ABC):

    def __init__(self, url, soup: Optional[BeautifulSoup] = None):
        self.url = url
        self.soup = soup

    @abstractmethod
    def get_events(self, client: Optional[requests.Session] = None) -> List[Dict]:
        pass

    @abstractmethod
    def extract_links(self, client: Optional[requests.Session] = None) -> List[str]:
        pass

    def generate_soup(self, client: Optional[requests.Session] = None) -> None:
        if self.soup:
            return
        
        session = client.session if client else requests.Session()

        # Optional: set a safe User-Agent
        if "User-Agent" not in session.headers:
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (compatible; EventsWebsiteBot/1.0)"
            })

        try:
            response = session.get(self.url, timeout=10)
            response.raise_for_status()  # Raise error for HTTP 4xx/5xx
            self.soup = BeautifulSoup(response.text, 'html.parser')
        except requests.RequestException as e:
            # Handle network errors safely
            print(f"Error fetching {self.url}: {e}")
            self.soup = None
        

    def __str__(self) -> str:
        return f"EventsWebsite w/ URL: {self.url}"