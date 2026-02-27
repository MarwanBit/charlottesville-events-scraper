from contextlib import contextmanager
import os
from sqlalchemy import create_engine, Integer, Text, DateTime, UniqueConstraint, Float
from sqlalchemy.orm import declarative_base, Mapped, mapped_column, sessionmaker
from sqlalchemy.orm.session import Session
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func
from enum import Enum

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://events:events@127.0.0.1:5432/events",
)

# No connection pool: each session/connect gets a real connection that is closed when done.
# Avoids "QueuePool limit reached" entirely. Slightly more churn, fine for pipeline/dashboard.
POOL_CLASS = NullPool


class _LazyEngine:
    """Defers create_engine() (and thus psycopg import) until first use, so importing models is fast."""

    _engine = None

    def _get_engine(self):
        if self._engine is None:
            # connect_timeout in URL may not be passed to psycopg; set explicitly so we fail fast
            # if Postgres isn't running instead of hanging.
            self._engine = create_engine(
                DATABASE_URL,
                poolclass=POOL_CLASS,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 5},
            )
        return self._engine

    def dispose(self):
        """Close all connections and clear the engine so the next use creates a fresh one."""
        global _session_factory
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
        _session_factory = None

    def __getattr__(self, name):
        return getattr(self._get_engine(), name)


engine = _LazyEngine()

_session_factory = None


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return _session_factory


def get_session() -> Session:
    """Return a new DB session. Prefer session_scope() so it is always closed."""
    return _get_session_factory()()


@contextmanager
def session_scope():
    """Context manager: yields a session and always closes it. Use for pipeline and DB work."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def connection_scope():
    """
    One connection for the whole block: no pool, no extra connections.
    Opens a single DB connection and yields a session bound to it. Use this for
    pipeline/long-running scripts when you've hit "too many clients" with session_scope.
    """
    with engine.connect() as conn:
        session_factory = sessionmaker(bind=conn, autoflush=False, autocommit=False)
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


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
    __table_args__ = (
        UniqueConstraint(
            "event_link",
            "start_date",
            "end_date",
            "start_time",
            "end_time",
            name="uq_event_link_start_date_end_date_start_time_end_time",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    event_link: Mapped[str] = mapped_column(Text, nullable=False)

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

    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    contact: Mapped[str | None] = mapped_column(Text, nullable=True)

    scraped_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
