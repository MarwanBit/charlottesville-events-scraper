from sqlalchemy.orm.session import Session

from .models import ProcessedURL, EventRecord
from .constants import DB_FIELDS


def _normalize_date_for_key(start_date):
    """Return a YYYY-MM-DD string for DB lookup; accept date, datetime, or str."""
    if start_date is None:
        return None
    if hasattr(start_date, "date"):  # datetime
        return start_date.date().isoformat()
    if hasattr(start_date, "isoformat"):  # date
        return start_date.isoformat()
    return str(start_date)


def _normalize_time_for_key(t):
    """Return a string for DB lookup; accept time, datetime, or str. None -> None."""
    if t is None:
        return None
    if t == "":
        return None
    if hasattr(t, "hour") and hasattr(t, "isoformat"):
        if hasattr(t, "year"):  # datetime
            return t.time().isoformat()
        return t.isoformat()  # time
    return str(t)

class Repository:
    """Requires session= from session_scope() or get_session()."""

    def __init__(self, session: Session):
        if session is None:
            raise TypeError("Repository requires session= (e.g. from session_scope()).")
        self.db = session
        self._own_session = False

    def close(self):
        if self._own_session:
            self.db.close()

    def is_processed(self, url: str) -> bool:
        return self.db.query(ProcessedURL).filter_by(url=url).first() is not None

    def mark_processed(self, url: str):
        self.db.add(ProcessedURL(url=url))

    def upsert_event(self, event: dict):
        event_link = event["event_link"]
        start_date_key = _normalize_date_for_key(event.get("start_date"))
        end_date_key = _normalize_date_for_key(event.get("end_date"))
        start_time_key = _normalize_time_for_key(event.get("start_time"))
        end_time_key = _normalize_time_for_key(event.get("end_time"))
        db_event = {k: v for k, v in event.items() if k in DB_FIELDS}
        if db_event.get("start_date") is not None and hasattr(db_event["start_date"], "isoformat"):
            db_event["start_date"] = _normalize_date_for_key(db_event["start_date"])
        if db_event.get("end_date") is not None and hasattr(db_event["end_date"], "isoformat"):
            db_event["end_date"] = _normalize_date_for_key(db_event["end_date"])
        if db_event.get("start_time") is not None and hasattr(db_event["start_time"], "isoformat"):
            db_event["start_time"] = _normalize_time_for_key(db_event["start_time"])
        if db_event.get("end_time") is not None and hasattr(db_event["end_time"], "isoformat"):
            db_event["end_time"] = _normalize_time_for_key(db_event["end_time"])

        existing = self.db.query(EventRecord).filter_by(
            event_link=event_link,
            start_date=start_date_key,
            end_date=end_date_key,
            start_time=start_time_key,
            end_time=end_time_key,
        ).first()
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

    def get_event_by_link_and_date(self, event_link: str, start_date) -> dict | None:
        """Return an existing event for this link and start_date, or None. start_date can be date or str."""
        key = _normalize_date_for_key(start_date)
        row = self.db.query(EventRecord).filter_by(event_link=event_link, start_date=key).first()
        if not row:
            return None
        return {f: getattr(row, f) for f in DB_FIELDS}

    def get_event_by_unique_key(
        self,
        event_link: str,
        start_date,
        end_date,
        start_time,
        end_time,
    ) -> dict | None:
        """Return an existing event for the full unique key, or None."""
        start_date_key = _normalize_date_for_key(start_date)
        end_date_key = _normalize_date_for_key(end_date)
        start_time_key = _normalize_time_for_key(start_time)
        end_time_key = _normalize_time_for_key(end_time)
        row = self.db.query(EventRecord).filter_by(
            event_link=event_link,
            start_date=start_date_key,
            end_date=end_date_key,
            start_time=start_time_key,
            end_time=end_time_key,
        ).first()
        if not row:
            return None
        return {f: getattr(row, f) for f in DB_FIELDS}

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()
