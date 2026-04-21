-- ============================================================
-- MIGRATION v6: Energy Attribution Table
-- ============================================================
-- PURPOSE:
--   Stores the full multi-layer energy decomposition for every run.
--   This is the core output of the attribution ETL pipeline.
--
-- LAYERS:
--   L0 Hardware  — raw RAPL domain readings
--   L1 System    — OS-level overhead split
--   L2 Resource  — I/O, network, memory pressure
--   L3 Workflow  — orchestration phases, tools, retries
--   L4 Model     — LLM compute decomposition
--   L5 Outcome   — energy normalised to task outcomes
--
-- ETL:  scripts/etl/energy_attribution_etl.py
-- Doc:  docs-src/mkdocs/source/research/12-energy-attribution-methodology.md
-- ============================================================

CREATE TABLE IF NOT EXISTS energy_attribution (
    run_id                          INTEGER PRIMARY KEY,

    -- ── L0: Hardware (raw RAPL domains) ─────────────────────────────────────
    -- Directly from RAPL MSR counters via RAPLReader.
    -- Units: microjoules (µJ). Source: runs.pkg_energy_uj etc.
    pkg_energy_uj                   BIGINT,
    core_energy_uj                  BIGINT,
    dram_energy_uj                  BIGINT,
    uncore_energy_uj                BIGINT,

    -- ── L1: System overhead ──────────────────────────────────────────────────
    -- background = energy not attributable to workload or OS services.
    -- Formula: background = max(0, pkg - core - dram - orchestration - application
    --                              - network_wait - io_wait)
    -- foreground is derived in views: pkg - background. NOT stored here.
    background_energy_uj            BIGINT,
    interrupt_energy_uj             BIGINT,   -- estimated from interrupt_rate × duration
    scheduler_energy_uj             BIGINT,   -- estimated from context_switches × cost

    -- ── L2: Resource contention ──────────────────────────────────────────────
    -- All INFERRED via time-fraction method: (wait_ms / total_ms) × pkg_energy
    network_wait_energy_uj          BIGINT,   -- from llm_interactions.non_local_ms
    io_wait_energy_uj               BIGINT,   -- from io_samples.io_block_time_ms
    disk_energy_uj                  BIGINT,   -- from disk_read/write bytes proxy
    memory_pressure_energy_uj       BIGINT,   -- from page_faults × 10µJ constant
    cache_dram_energy_uj            BIGINT,   -- dram_energy × (l3_misses / total_accesses)

    -- ── L3: Workflow decomposition ───────────────────────────────────────────
    -- orchestration = attributed - application (workload CPU fraction removed)
    -- phases from orchestration_events JOIN energy_samples ETL (Chunk 5)
    orchestration_energy_uj         BIGINT,
    planning_energy_uj              BIGINT,
    execution_energy_uj             BIGINT,
    synthesis_energy_uj             BIGINT,
    tool_energy_uj                  BIGINT,   -- (tool_time_ms / total_ms) × pkg — INFERRED
    retry_energy_uj                 BIGINT,   -- Σ energy of failed attempts (Chunk 8)
    failed_tool_energy_uj           BIGINT,   -- subset of retry (Chunk 8)
    rejected_generation_energy_uj   BIGINT,   -- hallucination penalty (Chunk 8)

    -- ── L4: Model compute ────────────────────────────────────────────────────
    -- llm_compute = application × ucr (compute utilisation ratio)
    -- prefill/decode split requires TTFT data (Chunk 4)
    llm_compute_energy_uj           BIGINT,
    prefill_energy_uj               BIGINT,   -- NULL until Chunk 4 TTFT available
    decode_energy_uj                BIGINT,   -- NULL until Chunk 4 TTFT available

    -- ── L5: Outcome normalisation ────────────────────────────────────────────
    -- Per-unit costs for research comparison across tasks and models.
    -- Units: µJ per unit (token, step, answer, task)
    energy_per_completion_token_uj  REAL,
    energy_per_successful_step_uj   REAL,
    energy_per_accepted_answer_uj   REAL,     -- NULL until Chunk 8 outcome data
    energy_per_solved_task_uj       REAL,     -- NULL until Chunk 8 outcome data

    -- ── Thermal penalty ──────────────────────────────────────────────────────
    -- Time-weighted: only throttled intervals contribute.
    -- Formula: Σ(interval where temp>85) / Σ(all intervals) × pkg × 0.20
    thermal_penalty_energy_uj       BIGINT,
    thermal_penalty_time_ms         REAL,     -- total milliseconds above 85°C

    -- ── Residual ─────────────────────────────────────────────────────────────
    -- Energy that could not be attributed to any layer.
    -- Research target: drive this toward zero across model iterations.
    -- Formula: unattributed = pkg - Σ(all attributed layers)
    -- A large unattributed signals missing attribution model coverage.
    unattributed_energy_uj          BIGINT,

    -- ── Attribution quality ──────────────────────────────────────────────────
    attribution_coverage_pct        REAL,     -- (pkg - unattributed) / pkg × 100
    attribution_model_version       TEXT DEFAULT 'v1',

    -- ── Metadata ─────────────────────────────────────────────────────────────
    created_at                      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at                      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_energy_attribution_run
    ON energy_attribution(run_id);
