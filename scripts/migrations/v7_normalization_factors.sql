-- ============================================================
-- MIGRATION v7: Normalization Factors Table
-- ============================================================
-- PURPOSE:
--   Stores per-run structural and behavioural factors used to
--   normalise energy metrics across different tasks, models, and
--   hardware configurations.
--
--   This enables apples-to-apples energy comparison:
--     "How much energy per successful goal, controlling for task difficulty?"
--
-- POPULATION:
--   ⚠️  This table is created empty in Chunk 6.
--   Population ETL is deferred to Chunk 8 (after query_execution,
--   query_attempt, hallucination_events tables exist).
--   TODO: scripts/etl/normalization_factors_etl.py (Chunk 8)
--
-- FACTOR GROUPS:
--   Structural — static properties of the task (input size, depth)
--   Behavioural — dynamic properties of this run (retries, failures)
--
-- Doc: docs-src/mkdocs/source/research/13-normalization-factors-methodology.md
-- ============================================================

CREATE TABLE IF NOT EXISTS normalization_factors (
    run_id                  INTEGER PRIMARY KEY,

    -- ── Structural factors (static, from task config) ────────────────────────
    -- These describe the inherent complexity of the task being evaluated.
    difficulty_score        REAL,       -- 0.0–1.0 composite difficulty rating
    difficulty_bucket       TEXT,       -- 'easy' | 'medium' | 'hard' | 'very_hard'
    task_category           TEXT,       -- from task_categories table
    workload_type           TEXT,       -- 'inference' | 'rag' | 'agentic' | 'tool_use'
    max_step_depth          INTEGER,    -- deepest planning depth observed
    branching_factor        REAL,       -- avg branches per decision node
    input_tokens            INTEGER,    -- prompt tokens (structural complexity proxy)
    output_tokens           INTEGER,    -- completion tokens
    context_window_size     INTEGER,    -- model context limit used
    total_work_units        REAL,       -- composite: tokens × steps × depth

    -- ── Behavioural factors (dynamic, from run execution) ────────────────────
    -- These describe how efficiently the run executed relative to the task.
    -- NULL until Chunk 8 outcome tracking tables are populated.
    successful_goals        INTEGER,    -- from query_execution.success (Chunk 8)
    attempted_goals         INTEGER,    -- from query_execution.num_attempts (Chunk 8)
    failed_attempts         INTEGER,    -- from query_attempt.status='failure' (Chunk 8)
    retry_depth             INTEGER,    -- max attempt_number seen (Chunk 8)
    total_retries           INTEGER,    -- COUNT(query_attempt WHERE status='retry') (Chunk 8)
    total_failures          INTEGER,    -- COUNT(query_attempt WHERE status='failure') (Chunk 8)
    total_tool_calls        INTEGER,    -- from orchestration_events
    failed_tool_calls       INTEGER,    -- from tool_failure_events (Chunk 8)
    hallucination_count     INTEGER,    -- from hallucination_events (Chunk 8)
    hallucination_rate      REAL,       -- hallucination_count / attempted_goals

    -- ── Resource factors ─────────────────────────────────────────────────────
    rss_memory_gb           REAL,       -- peak RSS during run (from runs.rss_memory_mb)
    cache_miss_rate         REAL,       -- l3_cache_misses / (l3_hits + l3_misses)
    io_wait_ratio           REAL,       -- io_block_time_ms / duration_ms
    stall_time_ms           REAL,       -- time cpu was stalled (not computing)
    sla_violations          INTEGER,    -- steps exceeding latency SLA (Chunk 8)

    -- ── Metadata ─────────────────────────────────────────────────────────────
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- TODO: populated_at — set when ETL fills behavioural factors (Chunk 8)

    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_normalization_factors_run
    ON normalization_factors(run_id);

CREATE INDEX IF NOT EXISTS idx_normalization_factors_difficulty
    ON normalization_factors(difficulty_bucket, task_category);
