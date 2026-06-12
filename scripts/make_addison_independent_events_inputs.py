#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import os
import re
from typing import Any, Optional


def _load_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _clean_text(text: Any) -> str:
    if not text:
        return ""
    return " ".join(str(text).split())


def _scrape_addisonindependent_events_inputs(
    *,
    url: str,
    limit_events: Optional[int],
) -> tuple[list[dict[str, Any]], str]:
    """
    Scrape https://www.addisonindependent.com/calendar/ and build EVENTS_INPUTS_JSON
    compatible entries: {idx,title,paragraph_text,start_date,end_date,start_time,end_time}.
    """
    # Lazy import to avoid forcing dependencies when not scraping.
    import requests
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; EventsScraper/1.0)"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    page_text = _clean_text(soup.get_text(" ", strip=True))
    years = re.findall(r"\b(20\d{2})\b", page_text)
    default_year = max(int(y) for y in years) if years else (os.environ.get("DEFAULT_YEAR") or "")
    if not default_year:
        import datetime

        default_year = datetime.datetime.now().year
    default_year = int(default_year)

    day_heading_re = re.compile(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,?\s+([A-Za-z]+)\.?\s+(\d{1,2})$",
        flags=re.IGNORECASE,
    )
    months = {
        "JANUARY": 1,
        "FEBRUARY": 2,
        "MARCH": 3,
        "APRIL": 4,
        "MAY": 5,
        "JUNE": 6,
        "JULY": 7,
        "AUGUST": 8,
        "SEPTEMBER": 9,
        "OCTOBER": 10,
        "NOVEMBER": 11,
        "DECEMBER": 12,
        "SEPT": 9,
        "AUG": 8,
    }

    current_start_date: Optional[str] = None
    event_entries: list[dict[str, Any]] = []

    for p in soup.find_all("p"):
        strong = p.select_one("strong, b")
        if strong is None:
            continue

        raw_title = _clean_text(strong.get_text(" ", strip=True))
        if not raw_title:
            continue

        m_day = day_heading_re.match(raw_title)
        if m_day:
            month_token = re.sub(r"[^A-Za-z]", "", m_day.group(2).strip()).upper()
            month = months.get(month_token)
            if month:
                current_start_date = f"{default_year:04d}-{month:02d}-{int(m_day.group(3)):02d}"
            else:
                current_start_date = None
            continue

        # Skip obvious non-event headings/navigation.
        if (
            len(raw_title) <= 30
            and raw_title.upper() == raw_title
            and re.search(r"[A-Z]", raw_title)
        ):
            continue

        # Normalize title (remove leading weekday/date prefix if present).
        title = raw_title
        m_prefix = re.match(
            r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,?\s+([A-Za-z]+)\.?\s+(\d{1,2})\s+(.+)$",
            raw_title,
            flags=re.IGNORECASE,
        )
        if m_prefix:
            title = _clean_text(m_prefix.group(4))

        p_text = _clean_text(p.get_text(" ", strip=True))
        if not p_text:
            continue

        entry = {
            "idx": len(event_entries),
            "title": title,
            "paragraph_text": p_text,
            "start_date": current_start_date,
            "end_date": current_start_date,
            "start_time": None,
            "end_time": None,
        }
        event_entries.append(entry)

        if limit_events is not None and len(event_entries) >= limit_events:
            break

    return event_entries, page_text


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the EVENTS_INPUTS_JSON array for the Addison Independent LLM prompt. "
            "Input is a JSON array (or an object with key 'events') containing per-event fields."
        )
    )
    parser.add_argument(
        "--input",
        default="",
        help="Path to JSON file (use '-' to read from stdin). Required when not using --scrape-url.",
    )
    parser.add_argument(
        "--scrape-url",
        default="",
        help="If set, scrape the given URL instead of reading --input. "
        "Example: --scrape-url https://www.addisonindependent.com/calendar/",
    )
    parser.add_argument(
        "--limit-events",
        type=int,
        default=0,
        help="When scraping, limit number of events extracted (0 = no limit).",
    )
    parser.add_argument(
        "--raw-page-text-output",
        default="./tmp/addison_independent_calendar_page_text.txt",
        help="Optional path to write the full page text (scraped calendar page) to a file.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Indent level for the printed JSON (default: 2).",
    )
    parser.add_argument(
        "--output",
        default="./tmp/addison_independent_events_inputs.json",
        help="Path to write the EVENTS_INPUTS_JSON output (default: ./tmp/addison_independent_events_inputs.json).",
    )
    args = parser.parse_args()

    if args.scrape_url:
        limit = args.limit_events if args.limit_events and args.limit_events > 0 else None
        out, page_text = _scrape_addisonindependent_events_inputs(
            url=args.scrape_url,
            limit_events=limit,
        )
        if args.raw_page_text_output:
            parent = os.path.dirname(args.raw_page_text_output)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(args.raw_page_text_output, "w", encoding="utf-8") as f:
                # Add a trailing newline for nicer diffs / line-based tooling.
                f.write(page_text + "\n")
    else:
        if not args.input:
            raise SystemExit("Missing --input. Provide --input (JSON file or '-') or use --scrape-url.")
        raw = _load_json(args.input)
        events = raw.get("events") if isinstance(raw, dict) else raw
        if not isinstance(events, list):
            raise SystemExit("Input JSON must be a list or an object with key 'events'.")

        out: list[dict[str, Any]] = []
        for i, ev in enumerate(events):
            if not isinstance(ev, dict):
                raise SystemExit(f"Each event must be an object; got {type(ev)} at index {i}")

            idx = ev.get("idx", i)
            title = ev.get("title")
            paragraph_text = ev.get("paragraph_text")
            if not title or paragraph_text is None:
                raise SystemExit(
                    f"Event at index {i} must include 'title' and 'paragraph_text'. Got keys: {list(ev.keys())}"
                )

            out.append(
                {
                    "idx": int(idx),
                    "title": str(title),
                    "paragraph_text": str(paragraph_text),
                    # Optional: include these if you know them, otherwise they become null.
                    "start_date": ev.get("start_date"),
                    "end_date": ev.get("end_date"),
                    "start_time": ev.get("start_time"),
                    "end_time": ev.get("end_time"),
                }
            )

    # Ensure output directory exists.
    out_path = args.output
    if out_path:
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    payload = json.dumps(out, ensure_ascii=False, indent=args.indent)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"Wrote EVENTS_INPUTS_JSON to: {out_path}", flush=True)
    else:
        print(payload)


if __name__ == "__main__":
    main()

