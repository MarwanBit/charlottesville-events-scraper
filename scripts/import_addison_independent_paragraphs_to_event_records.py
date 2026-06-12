#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional


def _project_root_on_path() -> None:
    # Allow running as: `python3 scripts/....py`
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _load_paragraphs(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict) and isinstance(raw.get("events"), list):
        return raw["events"]
    if isinstance(raw, list):
        return raw
    raise SystemExit("Input JSON must be a list or an object with key 'events'.")


def _synthetic_event_link(base_url: str, idx: int) -> str:
    base = base_url.rstrip("/")
    return f"{base}/calendar-paragraph#{idx}"


def _should_skip_non_event(title: str, paragraph_text: str) -> bool:
    t = (title or "").strip()
    p = (paragraph_text or "").strip()
    if not p:
        return True

    # Common footer/menu entries your paragraph extractor picked up.
    if p.upper() in {"NAVIGATION", "CONNECT", "CONTACT"}:
        return True
    if t.upper() in {"NAVIGATION", "CONNECT", "CONTACT"} and len(t) <= 12:
        return True

    # If it doesn't look like it contains a date token, it's likely not a real event.
    dateish = bool(
        re.search(
            r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\b|\btime\s*tbd\b|TBD",
            p,
            flags=re.IGNORECASE,
        )
    )
    return not dateish


def main() -> None:
    _project_root_on_path()

    parser = argparse.ArgumentParser(
        description="Import Addison Independent scraped paragraph JSON into event_records."
    )
    parser.add_argument(
        "--input",
        default="./tmp/addison_independent_paragraphs.json",
        help="Path to addison_independent_paragraphs.json",
    )
    parser.add_argument(
        "--base-url",
        default="https://www.addisonindependent.com",
        help="Used to build synthetic event_link values.",
    )
    parser.add_argument(
        "--website",
        default="https://www.addisonindependent.com",
        help="Value for EventRecord.website",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only import first N paragraphs (0 = no limit).",
    )
    parser.add_argument(
        "--skip-non-events",
        action="store_true",
        default=True,
        help="Skip likely non-event paragraphs (NAVIGATION/CONTACT etc).",
    )
    parser.add_argument(
        "--no-skip-non-events",
        dest="skip_non_events",
        action="store_false",
        help="Do not apply non-event filtering.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse input and show counts, but do not connect/write to DB.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write to DB. Without this flag, the script runs in dry mode.",
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        default=True,
        help="If event_link already exists, update title/description/scraped_at.",
    )
    parser.add_argument(
        "--limit-skipped-print",
        type=int,
        default=10,
        help="How many skipped items to print for debugging.",
    )
    args = parser.parse_args()

    paragraphs = _load_paragraphs(args.input)
    if args.limit and args.limit > 0:
        paragraphs = paragraphs[: args.limit]

    total = len(paragraphs)
    skipped = 0
    kept: list[dict[str, Any]] = []
    sample_skipped: list[dict[str, Any]] = []

    for row in paragraphs:
        if not isinstance(row, dict):
            continue
        idx = row.get("idx")
        title = row.get("title") or ""
        p_text = row.get("paragraph_text") or ""
        if args.skip_non_events and _should_skip_non_event(str(title), str(p_text)):
            skipped += 1
            if len(sample_skipped) < args.limit_skipped_print:
                sample_skipped.append({"idx": idx, "title": title})
            continue
        kept.append(row)

    print(f"Loaded {total} paragraph rows from: {args.input}")
    print(f"Keeping {len(kept)} / Skipping {skipped}")
    if sample_skipped:
        print("Skipped sample (idx/title):")
        for s in sample_skipped:
            print(f"  - {s.get('idx')}: {s.get('title')}")

    if args.dry_run or not args.commit:
        print("Dry run (no DB writes). Re-run with: --commit")
        return

    # DB write
    from src.app.models import EventRecord, session_scope

    now = datetime.now(timezone.utc).isoformat()
    with session_scope() as session:
        inserted = 0
        updated = 0

        for row in kept:
            if not isinstance(row, dict):
                continue

            idx_val = row.get("idx")
            try:
                idx = int(idx_val)
            except Exception:
                # Fallback: use enumeration index, but keep stable ordering within the file.
                idx = len(kept)

            title = row.get("title")
            p_text = row.get("paragraph_text")
            if not isinstance(title, str) or not isinstance(p_text, str):
                continue

            event_link = _synthetic_event_link(args.base_url, idx)
            existing = session.query(EventRecord).filter_by(event_link=event_link).first()

            if existing and args.overwrite_existing:
                existing.title = title
                existing.description = p_text
                existing.website = args.website
                existing.scraped_at = now
                updated += 1
            elif not existing:
                session.add(
                    EventRecord(
                        event_link=event_link,
                        title=title,
                        description=p_text,
                        website=args.website,
                        scraped_at=now,
                    )
                )
                inserted += 1

        # session_scope() commits on success
        print(f"DB upsert complete. inserted={inserted} updated={updated}")


if __name__ == "__main__":
    main()

