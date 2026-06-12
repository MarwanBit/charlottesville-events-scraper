-- events_processed: aligned with docs/Bulk event import (CSV).pdf (column names, order, and types).
-- UNIQUE NULLS NOT DISTINCT requires PostgreSQL 15+ (project docker-compose uses PG 16).
-- PDF: UTF-8 CSV; name 1–255 chars; location_name 1–255 if set; city 1–100 if set; lat/lon decimal degrees;
--      start/end time stored as UTC; primary_category (existing system categories); secondary_category (e.g. Sched track, from event_records);
--      tags comma-separated 1–30 chars, max 10;
--      thumbnail/additional image URLs http(s); external_link URL; is_paid boolean.

CREATE TABLE IF NOT EXISTS events_processed (
    id BIGINT PRIMARY KEY,
    name VARCHAR(255),
    description TEXT,
    location_name VARCHAR(255),
    address TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    city VARCHAR(100),
    primary_category TEXT,
    secondary_category TEXT,
    tags TEXT,
    thumbnail_image TEXT,
    additional_images TEXT,
    external_link TEXT,
    is_paid BOOLEAN,
    CONSTRAINT uq_events_processed_name_start_end UNIQUE NULLS NOT DISTINCT (name, start_time, end_time)
);
