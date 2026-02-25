#!/usr/bin/env python3
"""
Show current PostgreSQL connections. Uses its own connection (not the app pool).

Run (from repo root, use project venv so psycopg is available):
  .venv/bin/python scripts/show_connections.py           # show connections
  .venv/bin/python scripts/show_connections.py --terminate   # close ALL other connections

Or via Docker only (no Python needed):
  docker exec charlottesville_db psql -U events -d events -c "SELECT count(*) AS total, state FROM pg_stat_activity WHERE datname='events' GROUP BY state; SELECT pid, application_name, client_addr, state, left(query,60) FROM pg_stat_activity WHERE datname='events';"

To close all connections via Docker (run this when you see "too many clients already"):
  docker exec charlottesville_db psql -U events -d events -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='events' AND pid <> pg_backend_pid();"
"""
import argparse
from sqlalchemy import create_engine, text

# Same DB URL as app but a FRESH engine with 1 connection - never use app's engine here
DATABASE_URL = "postgresql+psycopg://events:events@127.0.0.1:5432/events?connect_timeout=5"

SQL = """
SELECT
    count(*) FILTER (WHERE state = 'active') AS active,
    count(*) FILTER (WHERE state = 'idle') AS idle,
    count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx,
    count(*) AS total
FROM pg_stat_activity
WHERE datname = current_database();
"""

SQL_DETAIL = """
SELECT
    pid,
    usename,
    application_name,
    client_addr,
    state,
    state_change,
    left(query, 80) AS query_preview
FROM pg_stat_activity
WHERE datname = current_database()
ORDER BY state, pid;
"""

# Terminate every connection to current DB except this one
SQL_TERMINATE = """
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid();
"""


def main():
    parser = argparse.ArgumentParser(description="Show or terminate PostgreSQL connections to the events DB.")
    parser.add_argument("--terminate", action="store_true", help="Close all other connections (keeps only this script's).")
    args = parser.parse_args()

    # Separate engine: pool_size=1, so we don't touch the app pool
    engine = create_engine(DATABASE_URL, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as conn:
            if args.terminate:
                result = conn.execute(text(SQL_TERMINATE))
                terminated = sum(1 for row in result if row[0] is True)
                conn.commit()
                print(f"Terminated {terminated} connection(s). Remaining:\n")
            print("=== Connection summary (current DB) ===\n")
            row = conn.execute(text(SQL)).fetchone()
            print(f"  active:           {row[0]}")
            print(f"  idle:             {row[1]}")
            print(f"  idle in transaction: {row[2]}")
            print(f"  TOTAL:            {row[3]}")
            print()
            print("=== Per-connection detail ===\n")
            rows = conn.execute(text(SQL_DETAIL)).fetchall()
            if not rows:
                print("  (none)")
            else:
                for r in rows:
                    print(f"  pid={r[0]}  app={r[2]!r}  client={r[3]}  state={r[4]!r}")
                    print(f"    query: {r[6]}")
            print()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
