-- Migration 027: Goal Execution and Attempt Tables
-- goal_execution = paper's fundamental unit of analysis (energy per successful goal)
-- goal_attempt   = thin linkage layer between goal and run, records outcome only
--
-- workflow_type on goal_execution is NOT derived from experiments.workflow_type
-- Application layer sets it explicitly at insert time — always linear or agentic
-- This is intentional: experiments.workflow_type='comparison' contains both
-- Schema revision: 027

CREATE TABLE IF NOT EXISTS goal_execution (
    goal_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    exp_id                  INTEGER NOT NULL,
    first_run_id            INTEGER NOT NULL,
    goal_description        TEXT NOT NULL,
    goal_type               TEXT NOT NULL
                            CHECK(goal_type IN (
                                'factual','reasoning','tool_use',
                                'multi_step','code','other'
                            )),
    -- Never 'comparison' — a goal always executes on one workflow side
    workflow_type           TEXT NOT NULL
                            CHECK(workflow_type IN ('linear','agentic')),
    -- difficulty_level: confound control — reviewers will challenge energy
    -- differences without this (easy vs hard tasks skew results)
    difficulty_level        TEXT
                            CHECK(difficulty_level IS NULL OR difficulty_level IN (
                                'easy','medium','hard'
                            )),
    total_attempts          INTEGER NOT NULL DEFAULT 1,
    success                 INTEGER NOT NULL DEFAULT 0,
    -- NULL when no attempt succeeded
    winning_run_id          INTEGER,

    -- ETL populated by chunk8_goal_etl.py — NULL at insert time per Rule SC-4
    total_energy_uj         INTEGER,
    successful_energy_uj    INTEGER,
    overhead_energy_uj      INTEGER,
    overhead_fraction       REAL,
    orchestration_fraction  REAL,

    wall_time_ms            REAL,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (exp_id)         REFERENCES experiments(exp_id),
    FOREIGN KEY (first_run_id)   REFERENCES runs(run_id),
    FOREIGN KEY (winning_run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_goal_exec_exp_id
    ON goal_execution(exp_id);

CREATE INDEX IF NOT EXISTS idx_goal_exec_workflow
    ON goal_execution(workflow_type, success);

CREATE INDEX IF NOT EXISTS idx_goal_exec_type
    ON goal_execution(goal_type);

CREATE INDEX IF NOT EXISTS idx_goal_exec_difficulty
    ON goal_execution(difficulty_level, success);

CREATE INDEX IF NOT EXISTS idx_goal_exec_success
    ON goal_execution(success, exp_id);

-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS goal_attempt (
    attempt_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id                 INTEGER NOT NULL,
    run_id                  INTEGER NOT NULL,
    attempt_number          INTEGER NOT NULL DEFAULT 1,
    is_winning              INTEGER NOT NULL DEFAULT 0,

    outcome                 TEXT NOT NULL
                            CHECK(outcome IN (
                                'success','failure','hallucination',
                                'timeout','context_overflow','api_error'
                            )),
    -- NULL means attempt succeeded — explicit NULL semantics per MASTER spec
    failure_cause           TEXT
                            CHECK(failure_cause IS NULL OR failure_cause IN (
                                'api_error','tool_error','wrong_answer',
                                'timeout','context_overflow','rate_limit'
                            )),

    -- Denormalized snapshot from runs + energy_attribution at insert time
    -- These are point-in-time values — not recomputed if runs is updated later
    energy_uj               INTEGER,
    orchestration_uj        INTEGER,
    compute_uj              INTEGER,

    -- NULL until Agent 8.3 output_quality ETL runs
    normalized_score        REAL,
    pass_fail               INTEGER,

    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Prevents duplicate attempt numbers for same goal
    UNIQUE(goal_id, attempt_number),

    FOREIGN KEY (goal_id) REFERENCES goal_execution(goal_id),
    FOREIGN KEY (run_id)  REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_goal_attempt_goal_id
    ON goal_attempt(goal_id);

CREATE INDEX IF NOT EXISTS idx_goal_attempt_run_id
    ON goal_attempt(run_id);

CREATE INDEX IF NOT EXISTS idx_goal_attempt_outcome
    ON goal_attempt(outcome);

CREATE INDEX IF NOT EXISTS idx_goal_attempt_winning
    ON goal_attempt(goal_id, is_winning);

CREATE INDEX IF NOT EXISTS idx_goal_attempt_goal_attemptnum
    ON goal_attempt(goal_id, attempt_number);
