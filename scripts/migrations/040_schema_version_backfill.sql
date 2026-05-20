-- Migration 040: Backfill schema_version table with all historical migrations
-- Pure data fix — no DDL changes
-- Compliance: SC-3 (naming), data integrity only

INSERT OR IGNORE INTO schema_version (version, applied_at, description) VALUES
  (6,  '2026-04-19 18:53:00', 'Energy attribution views'),
  (9,  '2026-04-20 11:15:00', 'Duration fix v9'),
  (10, '2026-04-20 18:13:00', 'Chunk 6.1 fixes'),
  (11, '2026-04-21 06:18:00', 'TTFT metrics chunk 7'),
  (12, '2026-04-21 13:30:00', 'Provider schema chunk 7'),
  (13, '2026-04-21 17:14:00', 'LLM streaming metrics'),
  (14, '2026-04-22 13:39:00', 'Run quality table'),
  (15, '2026-04-22 18:04:00', 'Migrate DB'),
  (16, '2026-04-23 08:53:00', 'Experiment metadata'),
  (17, '2026-04-23 09:30:00', 'Goal execution attempt'),
  (18, '2026-04-23 11:55:00', 'Hallucination quality'),
  (19, '2026-04-23 12:45:00', 'Tool failure events'),
  (20, '2026-04-23 12:45:00', 'Chunk 8 views'),
  (21, '2026-04-24 14:07:00', 'Goal tracking upgrades'),
  (22, '2026-04-24 16:51:00', 'Retry policy'),
  (23, '2026-04-25 13:55:00', 'Tool instrumentation'),
  (24, '2026-04-26 17:04:00', 'Experiment validity'),
  (25, '2026-05-01 15:21:00', 'Phase attribution v2'),
  (26, '2026-05-02 17:18:00', 'Request start ns'),
  (27, '2026-05-16 09:08:00', 'ETL queue cleanup');

