from abc import ABC, abstractmethod

from .dumper import PostgreSQLDumper
from .url_queue import PostgreSQLURLQueue
from .url_resolver import URLResolver
from .http_client import HTTPClient
from .repository import Repository
from .new_transformer import Transformer
import time

repository = Repository()

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
        self.client = HTTPClient()
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