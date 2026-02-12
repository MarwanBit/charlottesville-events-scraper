from sqlalchemy.orm import sessionmaker
from app.models import engine, ProcessedURL, EventRecord
from app.constants import DB_FIELDS

class Repository:
    def __init__(self):
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
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

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()
