-- If you already ran add_columns_... when latitude/longitude/cost were TEXT, run this to convert to numbers.
-- Run against your events DB, e.g.:
--   psql $DATABASE_URL -f scripts/alter_latitude_longitude_cost_to_numeric.sql

ALTER TABLE event_records
  ALTER COLUMN latitude TYPE DOUBLE PRECISION USING NULLIF(trim(latitude), '')::double precision,
  ALTER COLUMN longitude TYPE DOUBLE PRECISION USING NULLIF(trim(longitude), '')::double precision,
  ALTER COLUMN cost TYPE DOUBLE PRECISION USING NULLIF(trim(cost), '')::double precision;
