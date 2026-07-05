-- Fix 040b: Correct schema_version per environment_config record
-- Assigns schema version active at time of environment creation
-- Pure data fix, no DDL

UPDATE environment_config SET schema_version = 10
WHERE created_at >= '2026-04-20 00:00:00' 
AND created_at < '2026-04-21 00:00:00';

UPDATE environment_config SET schema_version = 12
WHERE created_at >= '2026-04-21 00:00:00' 
AND created_at < '2026-04-22 00:00:00';

UPDATE environment_config SET schema_version = 14
WHERE created_at >= '2026-04-22 00:00:00' 
AND created_at < '2026-04-24 00:00:00';

UPDATE environment_config SET schema_version = 21
WHERE created_at >= '2026-04-24 00:00:00' 
AND created_at < '2026-04-25 00:00:00';

UPDATE environment_config SET schema_version = 23
WHERE created_at >= '2026-04-25 00:00:00' 
AND created_at < '2026-05-02 00:00:00';

UPDATE environment_config SET schema_version = 26
WHERE created_at >= '2026-05-02 00:00:00' 
AND created_at < '2026-05-17 00:00:00';

UPDATE environment_config SET schema_version = 27
WHERE created_at >= '2026-05-17 00:00:00';

