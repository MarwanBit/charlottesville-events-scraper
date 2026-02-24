from abc import ABC, abstractmethod

from .dumper import PostgreSQLDumper
from .url_queue import PostgreSQLURLQueue
from .url_resolver import URLResolver
from .http_client import HTTPClient, HybridClient
from .repository import Repository
from .transformer import Transformer
import time

repository = Repository()


def _dedupe_events_by_link(events: list[dict]) -> list[dict]:
    """Merge duplicate events that share the same event_link (e.g. recurring listings).
    Keeps one record per event_link with the earliest start_date and latest end_date."""
    by_link: dict[str, list[dict]] = {}
    for e in events:
        link = e.get("event_link") or ""
        by_link.setdefault(link, []).append(e)
    out = []
    for link, group in by_link.items():
        if not group:
            continue
        base = dict(group[0])
        if len(group) == 1:
            out.append(base)
            continue
        start_dates = [e.get("start_date") for e in group if e.get("start_date")]
        end_dates = [e.get("end_date") for e in group if e.get("end_date")]
        if start_dates:
            base["start_date"] = min(start_dates)
        if end_dates:
            base["end_date"] = max(end_dates)
        out.append(base)
    return out


class BasePipeline(ABC):

    def __init__(self, client, queue, url_resolver, transformer, dumper):
        self.client = client
        self.queue = queue
        self.url_resolver = url_resolver
        self.transformer = transformer
        self.dumper = dumper

    @abstractmethod
    def run(self):
        pass

# Here's what I want to do with the new pipeline
class PostgreSQLPipeline(BasePipeline):

    def __init__(self):
        self.queue = PostgreSQLURLQueue()
        self.client = HybridClient()
        self.url_resolver = URLResolver()
        self.dumper = PostgreSQLDumper()
        self.transformer = Transformer()

    def run(self):
        self.queue.init_queue()
        while not self.queue.empty():
            url = self.queue.pop()
            print(url)
            time.sleep(1)
            website = self.url_resolver.resolve(url)

            # add external links/new sites to visit
            for external_site in website.extract_links(self.client):
                self.queue.enqueue(external_site)
            # now we need to extract the links from it
            events = website.get_events(self.client)
            events = _dedupe_events_by_link(events)
            print(events)
            # dump the information to the DB, then transform it and reinsert it
            self.dumper.dump_events(events)
            # extract information from the DB
            for event in events:
                event_link = event["event_link"]
                existing = repository.get_event_by_link(event_link)
                merged =  {**(existing or {}), **event}
                transformed_event = self.transformer.transform_event(merged)
                self.dumper.upsert_event(transformed_event)
            self.dumper.commit()

            # now we mark them as visited
            self.queue.mark_complete(website.url)
            print(website)


if __name__ == "__main__":
    pipeline = PostgreSQLPipeline()
    pipeline.run()