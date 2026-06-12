#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Optional


def _clean_text(text: Any) -> str:
    if text is None:
        return ""
    return " ".join(str(text).split())


def _looks_like_day_heading(raw_title: str) -> bool:
    # Example pattern we’ve seen on the page: "Saturday, March 28"
    return bool(
        re.match(
            r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,?\s+[A-Za-z]+\.?\s+\d{1,2}$",
            raw_title,
            flags=re.IGNORECASE,
        )
    )


def _normalize_title(raw_title: str) -> str:
    # If the title includes a day prefix, strip it (the actual event title is after it).
    m_prefix = re.match(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,?\s+([A-Za-z]+)\.?\s+(\d{1,2})\s+(.+)$",
        raw_title,
        flags=re.IGNORECASE,
    )
    if m_prefix:
        return _clean_text(m_prefix.group(4))
    return raw_title


def scrape_event_paragraphs(
    *,
    url: str,
    limit_paragraphs: Optional[int],
    include_day_headings: bool,
) -> list[dict[str, Any]]:
    # Lazy imports so this script only depends on runtime packages.
    import requests
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (compatible; EventsScraper/1.0)"}
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    out: list[dict[str, Any]] = []
    for p in soup.find_all("p"):
        strong = p.select_one("strong, b")
        if strong is None:
            continue

        raw_title = _clean_text(strong.get_text(" ", strip=True))
        if not raw_title:
            continue

        if _looks_like_day_heading(raw_title) and not include_day_headings:
            continue

        # Normalize the title; for event paragraphs the title is already the bold text,
        # but day-prefixed entries can occur.
        title = _normalize_title(raw_title)

        p_text = _clean_text(p.get_text(" ", strip=True))
        if not p_text:
            continue

        out.append(
            {
                "idx": len(out),
                "title": title,
                "paragraph_text": p_text,
            }
        )

        if limit_paragraphs is not None and len(out) >= limit_paragraphs:
            break

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Addison Independent calendar paragraphs to JSON.")
    parser.add_argument(
        "--url",
        default="https://www.addisonindependent.com/calendar/",
        help="Addison Independent calendar URL to scrape.",
    )
    parser.add_argument(
        "--limit-paragraphs",
        type=int,
        default=0,
        help="Max number of paragraphs/events to extract (0 = no limit).",
    )
    parser.add_argument(
        "--include-day-headings",
        action="store_true",
        help="If set, include day heading paragraphs that look like 'Saturday, March 28'.",
    )
    parser.add_argument(
        "--output",
        default="./tmp/addison_independent_paragraphs.json",
        help="Output path for the JSON array.",
    )
    args = parser.parse_args()

    limit = args.limit_paragraphs if args.limit_paragraphs and args.limit_paragraphs > 0 else None
    paragraphs = scrape_event_paragraphs(
        url=args.url,
        limit_paragraphs=limit,
        include_day_headings=args.include_day_headings,
    )

    out_path = args.output
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(paragraphs, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(paragraphs)} paragraphs to: {out_path}", flush=True)


if __name__ == "__main__":
    main()

