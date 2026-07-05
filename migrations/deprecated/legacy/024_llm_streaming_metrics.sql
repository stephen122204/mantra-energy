-- scripts/migrations/024_llm_streaming_metrics.sql
-- Chunk 4: Add TTFT/TPOT streaming metrics to llm_interactions
-- Paired change: core/database/schema.py must match (SC-2)

ALTER TABLE llm_interactions ADD COLUMN ttft_ms REAL;
ALTER TABLE llm_interactions ADD COLUMN tpot_ms REAL;
ALTER TABLE llm_interactions ADD COLUMN token_throughput REAL;
ALTER TABLE llm_interactions ADD COLUMN streaming_enabled INTEGER DEFAULT 0;
ALTER TABLE llm_interactions ADD COLUMN first_token_time_ns INTEGER;
ALTER TABLE llm_interactions ADD COLUMN last_token_time_ns INTEGER;
ALTER TABLE llm_interactions ADD COLUMN prefill_energy_uj INTEGER;
