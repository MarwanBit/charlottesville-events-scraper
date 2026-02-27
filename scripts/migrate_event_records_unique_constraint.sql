-- One-time migration: replace (event_link, start_date) unique constraint with
-- (event_link, start_date, end_date, start_time, end_time).
-- Run against your events DB, e.g. psql $DATABASE_URL -f scripts/migrate_event_records_unique_constraint.sql

ALTER TABLE event_records
  DROP CONSTRAINT IF EXISTS uq_event_link_start_date;

ALTER TABLE event_records
  ADD CONSTRAINT uq_event_link_start_date_end_date_start_time_end_time
  UNIQUE (event_link, start_date, end_date, start_time, end_time);
