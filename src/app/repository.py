from sqlalchemy.orm.session import Session

from sqlalchemy.orm import sessionmaker
from .models import engine, ProcessedURL, EventRecord
from .constants import DB_FIELDS

class Repository:
    def __init__(self):
        SessionLocal = sessionmaker[Session](bind=engine, autoflush=False, autocommit=False)
        self.db = SessionLocal()

    def close(self):
        self.db.close()

    def is_processed(self, url: str) -> bool:
        return self.db.query(ProcessedURL).filter_by(url=url).first() is not None

    def mark_processed(self, url: str):
        self.db.add(ProcessedURL(url=url))

    def upsert_event(self, event: dict):
        event_link = event["event_link"]
        db_event = {k: v for k, v in event.items() if k in DB_FIELDS}

        existing = self.db.query(EventRecord).filter_by(event_link=event_link).first()
        if existing:
            for k, v in db_event.items():
                setattr(existing, k, v)
        else:
            self.db.add(EventRecord(**db_event))

    def get_event_by_link(self, event_link: str) -> dict | None:
        """Return an existing event as a dict keyed by DB_FIELDS, or None if not found."""
        row = self.db.query(EventRecord).filter_by(event_link=event_link).first()
        if not row:
            return None
        return {f: getattr(row, f) for f in DB_FIELDS}

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()
