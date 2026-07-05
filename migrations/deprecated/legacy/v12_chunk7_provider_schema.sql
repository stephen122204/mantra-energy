-- =============================================================================
-- v12_chunk7_provider_schema.sql
-- Adds provider ontology columns to experiments table.
-- These capture WHERE inference runs, HOW it connects, and WHAT energy is visible.
-- Values come from models.yaml via get_model_config_v2() at experiment creation time.
-- =============================================================================

-- model_id: actual model identifier e.g. "llama-3.3-70b-versatile"
ALTER TABLE experiments ADD COLUMN model_id TEXT;

-- execution_site: where inference actually executes
--   host       = same machine as harness (llama_cpp, ollama_local)
--   remote_vm  = controlled remote server (ollama_remote / Oracle VM)
--   vendor_api = third-party hosted API (groq, openai, anthropic, gemini)
ALTER TABLE experiments ADD COLUMN execution_site TEXT;

-- transport: how requests reach the inference endpoint
--   inprocess     = same process, no socket (llama_cpp)
--   loopback_http = localhost HTTP (ollama_local)
--   remote_http   = another machine over network (ollama_remote, groq, openai)
ALTER TABLE experiments ADD COLUMN transport TEXT;

-- energy_visibility: what energy can be measured for this run
--   host_only        = only client/host energy measured (groq, openai, llama_cpp now)
--   host_plus_remote = both client and remote VM energy measured (ollama_remote future)
ALTER TABLE experiments ADD COLUMN energy_visibility TEXT;

-- Backfill existing rows using already-corrected provider column
UPDATE experiments
SET
    execution_site    = 'vendor_api',
    transport         = 'remote_http',
    energy_visibility = 'host_only'
WHERE provider = 'groq';

UPDATE experiments
SET
    execution_site    = 'host',
    transport         = 'inprocess',
    energy_visibility = 'host_only'
WHERE provider = 'llama_cpp';
