SELECT 
		id, 
		title AS name,
		description,
		latitude,
		longitude,
		address,
		location_name,
		(start_date || 'T' || COALESCE(NULLIF(trim(left(trim(CASE WHEN position(' ' in trim(start_time)) > 0 THEN split_part(trim(start_time), ' ', 2) ELSE trim(start_time) END), 8)), ''), '00:00:00') || 'Z') AS start_time,
		(end_date || 'T' || COALESCE(NULLIF(trim(left(trim(CASE WHEN position(' ' in trim(end_time)) > 0 THEN split_part(trim(end_time), ' ', 2) ELSE trim(end_time) END), 8)), ''), '00:00:00') || 'Z') AS end_time,
		event_category AS primary_category,
		secondary_category,
		audience,
		location_type,
		image_url AS thumbnail_image,
		-- Per-event source URL (Tom Tom and others set `website` to the series/homepage, not the event page).
		event_link AS external_link
FROM event_records
WHERE
	start_date IS NOT NULL
	AND end_date IS NOT NULL
 	AND start_time IS NOT NULL
	AND end_time IS NOT NULL
	AND address IS NOT NULL;