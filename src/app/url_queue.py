from abc import ABC, abstractmethod
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

from .models import engine, ProcessedURL, ProcessedURLStatus
from .constants import INITIAL_URLS

class URLQueue(ABC):

    @abstractmethod
    def init_queue(self):
        pass

    @abstractmethod
    def pop(self):
        pass

    @abstractmethod
    def enqueue(self, url):
        pass

    @abstractmethod
    def mark_complete(self, url):
        pass

    @abstractmethod
    def mark_failed(self, url):
        pass

    @abstractmethod
    def empty(self) -> bool:
        pass

class PostgreSQLURLQueue(URLQueue):

    def __init__(self):
        SessionLocal = sessionmaker[Session](bind=engine, autoflush=False, autocommit=False)
        self.db = SessionLocal()

    def close(self):
        self.db.close()

    def init_queue(self):
        for url in INITIAL_URLS:
            self.enqueue(url)


    def pop(self) -> str | None:
        """Pop and return the first pending URL, or None if the queue is empty."""
        row = (
            self.db.query(ProcessedURL)
            .filter_by(status=ProcessedURLStatus.PENDING.value)
            .order_by(ProcessedURL.id)
            .limit(1)
            .first()
        )
        return row.url if row else None

    def enqueue(self, url: str) -> None:
        """Add a URL to the queue with status PENDING (ignores if url already exists)."""
        existing = self.db.query(ProcessedURL).filter_by(url=url).first()
        if not existing:
            self.db.add(ProcessedURL(url=url, status=ProcessedURLStatus.PENDING.value))
        self.db.commit()

    def mark_complete(self, url: str) -> None:
        """Mark the URL as COMPLETED after successful processing."""
        row = self.db.query(ProcessedURL).filter_by(url=url).first()
        if row:
            row.status = ProcessedURLStatus.COMPLETED.value
        self.db.commit()

    def mark_failed(self, url: str) -> None:
        """Mark the URL as FAILED after failed processing."""
        row = self.db.query(ProcessedURL).filter_by(url=url).first()
        if row:
           row.status = ProcessedURLStatus.FAILED.value
        self.db.commit()

    def empty(self) -> bool:
        """Return True if there are no pending URLs to process."""
        return (
            self.db.query(ProcessedURL)
            .filter_by(status=ProcessedURLStatus.PENDING.value)
            .limit(1)
            .first()
            is None
        )