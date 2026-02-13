from abc import ABC, abstractmethod

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from .utils import val
from .config import MISSING

from sqlalchemy.orm.session import Session
from sqlalchemy.orm import sessionmaker
from .models import engine, ProcessedURL, EventRecord
from .constants import DB_FIELDS

class BaseDumper(ABC):

    @abstractmethod
    def dump_events(self, events: list[dict]) -> None:
        pass

class ExcelDumper(BaseDumper):

    def __init__(self, filename: str, ws_title = "Events"):
        self.filename = filename
        # setup excel workbook
        self.wb = Workbook()
        #setup current tab/ worksheet
        self.ws = self.wb.active
        self.ws.title = ws_title
        # set headers for the worksheet and append them to the sheet
        self.headers = [
            "Title", "StartDate", "EndDate",
            "StartTime", "EndTime", "DayOfWeek", "IsWeekend", "TimeOfDay",
            "EventCategory", "Audience", "LocationType",
            "Address", "Organizer", "Phone", "Website", "ImageURL",
            "Description", "Event Page", "Scraped At"
        ]
        self.ws.append(self.headers)

    def dump_events(self, events: list[dict]) -> None:
        for e in events:
            self.ws.append([
                val(e.get("title"), MISSING),
                val(e.get("start_date"), MISSING),
                val(e.get("end_date"), MISSING),
                val(e.get("start_time"), MISSING),
                val(e.get("end_time"), MISSING),
                val(e.get("day_of_week"), MISSING),
                val(e.get("is_weekend"), MISSING),
                val(e.get("time_of_day"), MISSING),
                val(e.get("event_category"), MISSING),
                val(e.get("audience"), MISSING),
                val(e.get("location_type"), MISSING),
                val(e.get("address"), MISSING),
                val(e.get("organizer"), MISSING),
                val(e.get("phone"), MISSING),
                val(e.get("website"), MISSING),
                val(e.get("image_url"), MISSING),
                val(e.get("description"), MISSING),
                val(e.get("event_link"), MISSING),
                val(e.get("scraped_at"), MISSING),
            ])
        # Auto-size column widths to fit content (max width 60).
        for col in range(1, len(self.headers) + 1):
            max_len = 0
            col_letter = get_column_letter(col)
            for cell in self.ws[col_letter]:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
            self.ws.column_dimensions[col_letter].width = min(max_len + 2, 60)
        self.wb.save(self.filename)

class PostgreSQLDumper(BaseDumper):

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

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def dump_events(self, events: list[dict]) -> None:
        try:
            for event in events:
                self.upsert_event(event)
            self.commit()
        except Exception:
            self.rollback()
            raise

