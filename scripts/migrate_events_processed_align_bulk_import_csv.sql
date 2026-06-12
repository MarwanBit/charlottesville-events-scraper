-- Upgrade existing events_processed tables toward docs/Bulk event import (CSV).pdf
-- Run manually after pull (safe to re-run where no-ops apply).
-- If id or longitude cannot cast to bigint / double, fix rows then re-run.

-- 1. Sched track / sub-type (from event_records.secondary_category); optional.
ALTER TABLE events_processed ADD COLUMN IF NOT EXISTS secondary_category TEXT;

-- 2. tags (older DBs)
ALTER TABLE events_processed ADD COLUMN IF NOT EXISTS tags TEXT;

-- 3. longitude: legacy TEXT -> DOUBLE PRECISION (PDF: decimal degrees, same as latitude)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'events_processed'
      AND column_name = 'longitude'
      AND data_type IN ('text', 'character varying')
  ) THEN
    ALTER TABLE events_processed
      ALTER COLUMN longitude TYPE DOUBLE PRECISION USING (
        CASE
          WHEN longitude IS NULL OR NULLIF(trim(longitude::text), '') IS NULL THEN NULL
          ELSE trim(longitude::text)::double precision
        END
      );
  END IF;
END $$;

-- 4. id: legacy TEXT -> BIGINT (PDF: non-negative integer source id)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'events_processed'
      AND column_name = 'id'
      AND data_type IN ('text', 'character varying')
  ) THEN
    ALTER TABLE events_processed
      ALTER COLUMN id TYPE BIGINT USING trim(id::text)::bigint;
  END IF;
END $$;

-- 5. Enforce PDF max lengths before narrowing columns (name 255, location_name 255, city 100)
UPDATE events_processed SET name = left(name, 255) WHERE name IS NOT NULL AND length(name) > 255;
UPDATE events_processed SET location_name = left(location_name, 255) WHERE location_name IS NOT NULL AND length(location_name) > 255;
UPDATE events_processed SET city = left(city, 100) WHERE city IS NOT NULL AND length(city) > 100;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'events_processed'
      AND column_name = 'name'
      AND data_type = 'text'
  ) THEN
    ALTER TABLE events_processed
      ALTER COLUMN name TYPE VARCHAR(255);
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'events_processed'
      AND column_name = 'location_name'
      AND data_type = 'text'
  ) THEN
    ALTER TABLE events_processed
      ALTER COLUMN location_name TYPE VARCHAR(255);
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'events_processed'
      AND column_name = 'city'
      AND data_type = 'text'
  ) THEN
    ALTER TABLE events_processed
      ALTER COLUMN city TYPE VARCHAR(100);
  END IF;
END $$;

-- 6. Optional: TIMESTAMP -> TIMESTAMPTZ for UTC storage per PDF (uncomment only if times are stored as UTC)
-- ALTER TABLE events_processed
--   ALTER COLUMN start_time TYPE TIMESTAMPTZ USING start_time AT TIME ZONE 'UTC';
-- ALTER TABLE events_processed
--   ALTER COLUMN end_time TYPE TIMESTAMPTZ USING end_time AT TIME ZONE 'UTC';

-- 7. Unique (name, start_time, end_time) — requires PostgreSQL 15+ for NULLS NOT DISTINCT
-- Dedupe: keep one row per triple (highest numeric id wins).
WITH ranked AS (
  SELECT ctid,
         ROW_NUMBER() OVER (
           PARTITION BY name, start_time, end_time
           ORDER BY (id::text)::bigint DESC
         ) AS rn
  FROM events_processed
)
DELETE FROM events_processed WHERE ctid IN (SELECT ctid FROM ranked WHERE rn > 1);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_events_processed_name_start_end'
  ) THEN
    ALTER TABLE events_processed
      ADD CONSTRAINT uq_events_processed_name_start_end
      UNIQUE NULLS NOT DISTINCT (name, start_time, end_time);
  END IF;
END $$;
