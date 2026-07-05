-- Migration 038: Add request_start_ns to llm_interactions
-- Enables precise prefill window measurement: [request_start_ns → first_token_ns]
ALTER TABLE llm_interactions ADD COLUMN request_start_ns INTEGER;
