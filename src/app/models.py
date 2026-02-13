from sqlalchemy import create_engine, Integer, Text, DateTime
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy.sql import func
from enum import Enum

DATABASE_URL = "postgresql+psycopg://events:events@127.0.0.1:5432/events"

engine = create_engine(DATABASE_URL)

Base = declarative_base()

class ProcessedURLStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
# ------------------------
# Processed URLs table
# ------------------------
class ProcessedURL(Base):
    __tablename__ = "processed_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, default=ProcessedURLStatus.PENDING.value, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ------------------------
# Event Records table
# ------------------------
class EventRecord(Base):
    __tablename__ = "event_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    event_link: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_time: Mapped[str | None] = mapped_column(Text, nullable=True)

    day_of_week: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_weekend: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_of_day: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_type: Mapped[str | None] = mapped_column(Text, nullable=True)

    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    organizer: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    scraped_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
