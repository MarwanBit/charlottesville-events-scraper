from abc import ABC, abstractmethod
import time

from .dumper import PostgreSQLDumper
from .models import connection_scope
from .url_queue import PostgreSQLURLQueue
from .url_resolver import URLResolver
from .http_client import HybridClient
from .repository import Repository
from .transformer import Transformer
import pprint


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

# Pipeline uses connection_scope(): one connection for the whole run, session bound to it.
class PostgreSQLPipeline(BasePipeline):

    def __init__(self):
        self._queue = None
        self._client = None
        self._url_resolver = None
        self._dumper = None
        self._transformer = None

    @property
    def client(self):
        if self._client is None:
            self._client = HybridClient()
        return self._client

    @property
    def url_resolver(self):
        if self._url_resolver is None:
            self._url_resolver = URLResolver()
        return self._url_resolver

    @property
    def transformer(self):
        if self._transformer is None:
            self._transformer = Transformer()
        return self._transformer

    def run(self):
        print("Connecting to database...", flush=True)
        with connection_scope() as session:
            print("Connected. Initializing queue...", flush=True)
            self._queue = PostgreSQLURLQueue(session=session)
            self._dumper = PostgreSQLDumper(session=session)
            repository = Repository(session=session)
            try:
                self._queue.init_queue()
                print("Queue ready. Processing URLs...", flush=True)
                processed = 0
                while not self._queue.empty():
                    url = self._queue.pop()
                    processed += 1
                    print(f"[PIPELINE] URL #{processed}: {url}", flush=True)
                    time.sleep(1)
                    website = self.url_resolver.resolve(url)
                    

                    # add external links/new sites to visit
                    external_links = list(website.extract_links(self.client))
                    for external_site in external_links:
                        self._queue.enqueue(external_site)
                    print(f"[PIPELINE]   discovered {len(external_links)} new URLs to enqueue", flush=True)
                    # now we need to extract the links from it
                    events = website.get_events(self.client)
                    # pprint.pprint(events)
                    print(f"[PIPELINE]   scraped {len(events)} raw events", flush=True)
                    website_type = type(website).__name__
                    if website_type not in ("ExploreGeorgiaEventWebsite", "VisitCharlottesvilleEventWebsite", "WashingtonEventWebsite", "VisitMAEventWebsite", "EnjoyIllinoisEventWebsite"):
                        before = len(events)
                        events = _dedupe_events_by_link(events)
                        print(f"[PIPELINE]   deduped events: {before} -> {len(events)}", flush=True)
                    else:
                        print(f"[PIPELINE]   {website_type}: keeping {len(events)} events (no dedupe)", flush=True)
                    # dump the information to the DB, then transform it and reinsert it
                    self._dumper.dump_events(events)
                    # extract information from the DB
                    for event in events:
                        event_link = event["event_link"]
                        existing = repository.get_event_by_unique_key(
                            event_link,
                            event.get("start_date"),
                            event.get("end_date"),
                            event.get("start_time"),
                            event.get("end_time"),
                        )
                        merged = {**(existing or {}), **event}
                        transformed_event = self.transformer.transform_event(merged)
                        self._dumper.upsert_event(transformed_event)
                    self._dumper.commit()
                    print(f"[PIPELINE]   committed {len(events)} events", flush=True)

                    # now we mark them as visited
                    self._queue.mark_complete(website.url)
                    print(f"[PIPELINE] done with URL #{processed}: {website}", flush=True)
            finally:
                if self._client is not None:
                    try:
                        self._client.close()
                    except Exception:
                        pass
                if self._dumper is not None:
                    self._dumper.close()
                if self._queue is not None:
                    self._queue.close()


if __name__ == "__main__":
    pipeline = PostgreSQLPipeline()
    pipeline.run()