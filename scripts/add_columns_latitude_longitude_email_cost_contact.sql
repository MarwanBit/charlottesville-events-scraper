-- Add columns: latitude, longitude (DOUBLE PRECISION), email, cost (DOUBLE PRECISION), contact to event_records.
-- Run against your events DB, e.g.:
--   psql $DATABASE_URL -f scripts/add_columns_latitude_longitude_email_cost_contact.sql

ALTER TABLE event_records
  ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS email TEXT,
  ADD COLUMN IF NOT EXISTS cost DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS contact TEXT;
