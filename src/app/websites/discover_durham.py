from .base import EventsWebsite

class DiscoverDurhamWebsite(EventsWebsite):
    
    def get_events(self) -> list[dict]:
        pass

    def extract_links(self) -> list[str]:
        pass 

    def __str__(self) -> str:
        return f"DiscoverDurhamWebsite w/ URL: {self.url}"