"""Canonical primary_category normalization and comma-separated tags for events_processed."""

from src.app.constants import (
    PRIMARY_CATEGORIES,
    TAG_MAX_COUNT,
    TAG_MAX_LEN,
    build_tags_csv,
    normalize_primary_category,
)


def test_normalize_primary_category_canonical_unchanged():
    for c in PRIMARY_CATEGORIES:
        assert normalize_primary_category(c) == c


def test_normalize_primary_category_case_insensitive():
    assert normalize_primary_category("music") == "Music"
    assert normalize_primary_category("FOOD & DRINK") == "Food & Drink"


def test_normalize_primary_category_legacy_food():
    assert normalize_primary_category("Food") == "Food & Drink"


def test_normalize_primary_category_unknown_to_other():
    assert normalize_primary_category("not a real category xyz") == "Other"
    assert normalize_primary_category("") == "Other"
    assert normalize_primary_category(None) == "Other"


def test_build_tags_csv_empty():
    assert build_tags_csv(None, None) is None
    assert build_tags_csv("", "  ") is None


def test_build_tags_csv_audience_and_location():
    assert build_tags_csv("Families", "Restaurant/Bar") == "Families, Restaurant/Bar"


def test_build_tags_csv_truncates_to_30_chars():
    long_tag = "x" * 40
    out = build_tags_csv(long_tag, None)
    assert out is not None
    assert len(out) == TAG_MAX_LEN


def test_build_tags_csv_max_10_tags():
    assert TAG_MAX_COUNT == 10
    assert TAG_MAX_LEN == 30
    twelve = [str(i) for i in range(12)]
    out = build_tags_csv(twelve[0], twelve[1], *twelve[2:])
    assert out is not None
    assert out.count(", ") == 9  # 10 tags → 9 separators
    parts = [p.strip() for p in out.split(",")]
    assert parts == [str(i) for i in range(10)]
    assert "10" not in out
