-- Rows where image fields are non-empty but do not start with http:// or https:// (after trim).
-- To fix data: run  python scripts/migrate_to_backend_schema.py cleanup-images
--   (normalizes // and www., unescapes HTML, drops invalid URLs; clears additional_images segments that fail).

-- Thumbnail: invalid or relative (not http(s))
SELECT id, name, thumbnail_image
FROM events_processed
WHERE thumbnail_image IS NOT NULL
  AND trim(thumbnail_image) <> ''
  AND lower(trim(thumbnail_image)) NOT LIKE 'http://%'
  AND lower(trim(thumbnail_image)) NOT LIKE 'https://%';

-- Additional images: at least one comma-separated segment is non-empty and not http(s)
SELECT ep.id, ep.name, ep.additional_images
FROM events_processed ep
WHERE ep.additional_images IS NOT NULL
  AND trim(ep.additional_images) <> ''
  AND EXISTS (
    SELECT 1
    FROM regexp_split_to_table(trim(ep.additional_images), '\s*,\s*') AS u(part)
    WHERE trim(part) <> ''
      AND lower(trim(part)) NOT LIKE 'http://%'
      AND lower(trim(part)) NOT LIKE 'https://%'
  );

-- Combined: any row failing either check (for auditing)
SELECT id, name, thumbnail_image, additional_images
FROM events_processed
WHERE (
    thumbnail_image IS NOT NULL
    AND trim(thumbnail_image) <> ''
    AND lower(trim(thumbnail_image)) NOT LIKE 'http://%'
    AND lower(trim(thumbnail_image)) NOT LIKE 'https://%'
  )
  OR (
    additional_images IS NOT NULL
    AND trim(additional_images) <> ''
    AND EXISTS (
      SELECT 1
      FROM regexp_split_to_table(trim(additional_images), '\s*,\s*') AS p(part)
      WHERE trim(part) <> ''
        AND lower(trim(part)) NOT LIKE 'http://%'
        AND lower(trim(part)) NOT LIKE 'https://%'
    )
  );
