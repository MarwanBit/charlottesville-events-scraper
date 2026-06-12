-- Sched track / sub-type label (e.g. Tom Tom sched-event-type div), distinct from event_category.
--
-- Apply with either:
--   python scripts/add_secondary_category_column.py
--   psql "$DATABASE_URL" -f scripts/add_column_secondary_category_event_records.sql

ALTER TABLE event_records
  ADD COLUMN IF NOT EXISTS secondary_category TEXT;
