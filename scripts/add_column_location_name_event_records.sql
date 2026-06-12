-- Venue / location display label (e.g. Sched list-single venue link text). Maps to events_processed.location_name.
-- Run with psql, or add to your migration process.
--   psql "$DATABASE_URL" -f scripts/add_column_location_name_event_records.sql

ALTER TABLE event_records
  ADD COLUMN IF NOT EXISTS location_name TEXT;
