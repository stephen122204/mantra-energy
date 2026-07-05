-- Migration 035: Tool instrumentation metadata on orchestration_events
-- Adds tool-specific measurement columns so energy attribution pipeline
-- can attribute per-tool CPU, I/O, and memory costs without new tables.
-- Schema revision: 035
-- Chunk: 8.5-TOOLS

ALTER TABLE orchestration_events ADD COLUMN tool_name TEXT;
ALTER TABLE orchestration_events ADD COLUMN io_bytes_read INTEGER;
ALTER TABLE orchestration_events ADD COLUMN io_bytes_written INTEGER;
-- SHA-256 hashes of input/output payloads — reproducibility and dedup
ALTER TABLE orchestration_events ADD COLUMN input_payload_hash TEXT;
ALTER TABLE orchestration_events ADD COLUMN output_payload_hash TEXT;
-- 1 = success, 0 = failure — feeds v_failure_energy_taxonomy view
ALTER TABLE orchestration_events ADD COLUMN tool_success INTEGER;
-- Row count for database_query tool — correlates query size with energy
ALTER TABLE orchestration_events ADD COLUMN tool_result_rows INTEGER;
-- CPU and memory per tool call — closes the attribution black-box gap
-- that reviewers would otherwise challenge
ALTER TABLE orchestration_events ADD COLUMN tool_cpu_time_ns INTEGER;
ALTER TABLE orchestration_events ADD COLUMN tool_memory_delta_kb INTEGER;

-- Compound index — primary paper query pattern: tool_name + success
CREATE INDEX IF NOT EXISTS idx_events_tool_name
    ON orchestration_events(tool_name);
CREATE INDEX IF NOT EXISTS idx_events_tool_success
    ON orchestration_events(tool_name, tool_success);
