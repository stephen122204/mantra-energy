-- scripts/migrations/039_etl_queue_cleanup.sql
-- One-time cleanup: mark all pre-existing pending etl_queue rows as done.
-- Root cause (N40): goal_execution_manager.py previously called queue_etl()
-- but never marked entries done after synchronous ETL ran.
-- Fix already applied in code (lines 388-389) — this cleans historical rows.
-- Safe to rerun — UPDATE WHERE is idempotent.

-- Mark all pending goal_execution_etl rows done — ETL ran synchronously at save time
UPDATE etl_queue
SET    status       = 'done',
       processed_at = CURRENT_TIMESTAMP
WHERE  status   = 'pending'
  AND  etl_name = 'goal_execution_etl';

-- Mark all pending energy_attribution_etl rows done — ETL ran synchronously at save time
UPDATE etl_queue
SET    status       = 'done',
       processed_at = CURRENT_TIMESTAMP
WHERE  status   = 'pending'
  AND  etl_name = 'energy_attribution_etl';

-- Verify — should return no pending rows
SELECT status, etl_name, COUNT(*)
FROM   etl_queue
GROUP  BY status, etl_name;

PRAGMA integrity_check;
