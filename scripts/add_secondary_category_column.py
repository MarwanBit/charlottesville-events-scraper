#!/usr/bin/env python3
"""
Add optional ``event_records`` columns (TEXT, nullable):

- ``secondary_category`` (Sched track / type)
- ``location_name`` (venue display label, e.g. list-single layout)

Uses ``DATABASE_URL`` (environment or project-root ``.env``). If unset, uses the same
default as ``src.app.models``: local Postgres ``events`` / ``events`` (docker-compose ``db``).

Example::

  python scripts/add_secondary_category_column.py
  python scripts/add_secondary_category_column.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Same default as src.app.models — matches docker-compose `db` published on localhost:5432.
_DEFAULT_DATABASE_URL = "postgresql+psycopg://events:events@127.0.0.1:5432/events"


def _ensure_database_url() -> bool:
    """
    Return True if we filled a default (caller may print a hint).
    Empty string counts as unset — SQLAlchemy would otherwise get a bad URL.
    """
    v = (os.environ.get("DATABASE_URL") or "").strip()
    if v:
        return False
    os.environ["DATABASE_URL"] = _DEFAULT_DATABASE_URL
    return True


def _load_env_file(path: Path) -> None:
    """Set missing keys from .env (no extra dependency)."""
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip().strip('"').strip("'")
        os.environ[key] = val


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the SQL and exit without connecting.",
    )
    args = parser.parse_args()

    _load_env_file(_ROOT / ".env")
    used_default = _ensure_database_url()

    statements = [
        "ALTER TABLE event_records ADD COLUMN IF NOT EXISTS secondary_category TEXT",
        "ALTER TABLE event_records ADD COLUMN IF NOT EXISTS location_name TEXT",
    ]

    if args.dry_run:
        for s in statements:
            print(s)
        if used_default:
            print(
                f"(would use default DATABASE_URL: {_safe_url_host(_DEFAULT_DATABASE_URL)})",
                file=sys.stderr,
            )
        return

    from sqlalchemy import text

    from src.app.models import connection_scope, DATABASE_URL

    if used_default:
        print(
            "DATABASE_URL not in environment or .env — using default "
            f"localhost Postgres ({_safe_url_host(DATABASE_URL)}).",
            flush=True,
        )

    with connection_scope() as session:
        for s in statements:
            session.execute(text(s))
    print(
        "OK: event_records.secondary_category and location_name columns are present.",
        flush=True,
    )
    print(f"(DATABASE_URL host: {_safe_url_host(DATABASE_URL)})", flush=True)


def _safe_url_host(url: str) -> str:
    """Avoid printing credentials."""
    from urllib.parse import urlparse

    try:
        p = urlparse(url.replace("postgresql+psycopg", "postgresql", 1))
        host = p.hostname or "?"
        db = (p.path or "").lstrip("/") or "?"
        return f"{host}/{db}"
    except Exception:
        return "(unparsed)"


if __name__ == "__main__":
    main()
