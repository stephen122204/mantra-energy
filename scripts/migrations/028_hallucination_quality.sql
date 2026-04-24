-- Migration 028: hallucination_events, output_quality, output_quality_judges
-- Chunk 8.3 | Schema Revision: 028
-- Agent 8.3 creates tables only. ETL population owned by Agent 8.4.
-- agreement_score formula: 1 - ABS(score_a - score_b) assuming 0-1 normalized scores
-- hallucination_type / detection_method: open TEXT, governed by core/ontology_registry.py
-- goal_id denormalized in child tables for analytics speed (consistent with chunk 8 pattern)

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────
-- TABLE: hallucination_events
-- One row per hallucination detected within one attempt.
-- A hallucination is an unsupported or incorrect output later classified as hallucinatory.
-- wasted_energy_uj = energy from attempt start until hallucination detected (ETL-populated)
-- severity        = 0.0 (trivial) to 1.0 (critical), NULL until future chunk defines method
-- detection_confidence = detector confidence this IS a hallucination (not model logprob)
-- corrected_later: NOT stored — derive via goal_attempt join when needed
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hallucination_events (
    hallucination_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id              INTEGER NOT NULL,
    goal_id                 INTEGER NOT NULL,

    -- Nullable trace links — not every hallucination has full traceability
    decision_id             INTEGER,
    interaction_id          INTEGER,
    orchestration_event_id  INTEGER,

    -- Open TEXT governed by core/ontology_registry.py HALLUCINATION_TYPES
    hallucination_type      TEXT NOT NULL,
    -- Open TEXT governed by core/ontology_registry.py DETECTION_METHODS
    detection_method        TEXT NOT NULL,

    -- Detection signals
    detection_confidence    REAL,       -- detector confidence this is a hallucination, 0-1
    semantic_similarity     REAL,       -- similarity between expected and actual output, 0-1
    severity                REAL,       -- 0.0-1.0 continuous, ETL-populated by future chunk

    -- Evidence
    expected_output         TEXT,
    actual_output           TEXT,

    -- Energy cost — NULL at insert, populated by chunk8_attribution_etl.py
    wasted_energy_uj        INTEGER,

    detected_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (attempt_id)             REFERENCES goal_attempt(attempt_id),
    FOREIGN KEY (goal_id)                REFERENCES goal_execution(goal_id),
    FOREIGN KEY (decision_id)            REFERENCES agent_decision_tree(decision_id),
    FOREIGN KEY (interaction_id)         REFERENCES llm_interactions(interaction_id),
    FOREIGN KEY (orchestration_event_id) REFERENCES orchestration_events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_halluc_attempt_id
    ON hallucination_events(attempt_id);
CREATE INDEX IF NOT EXISTS idx_halluc_goal_id
    ON hallucination_events(goal_id);
CREATE INDEX IF NOT EXISTS idx_halluc_type
    ON hallucination_events(hallucination_type);
CREATE INDEX IF NOT EXISTS idx_halluc_method
    ON hallucination_events(detection_method);
CREATE INDEX IF NOT EXISTS idx_halluc_attempt_type
    ON hallucination_events(attempt_id, hallucination_type);

-- ─────────────────────────────────────────────
-- TABLE: output_quality
-- One row per goal_attempt. Reconciled judgment verdict across all judges.
-- Per-judge evidence lives in output_quality_judges child table.
-- score_method and normalized_score computed by application layer at insert (not ETL).
-- Tie-break logic (application layer must implement exactly):
--   judge_count = 1            → single_judge,     normalized_score = that judge score
--   agreement_score >= 0.8     → averaged,          normalized_score = mean of judge scores
--   agreement_score >= 0.5     → conservative_min,  normalized_score = min of judge scores
--   agreement_score <  0.5     → needs_review,      normalized_score = NULL
-- Exclude score_method = 'needs_review' from all paper analysis queries.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS output_quality (
    quality_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id              INTEGER NOT NULL,
    goal_id                 INTEGER NOT NULL,
    task_id                 TEXT,

    metric_type             TEXT NOT NULL
                            CHECK(metric_type IN (
                                'binary','scalar','pairwise','testsuite'
                            )),
    raw_score               REAL,
    normalized_score        REAL,       -- NULL when score_method = 'needs_review'
    pass_fail               INTEGER,

    judge_method            TEXT NOT NULL
                            CHECK(judge_method IN (
                                'exact_match','semantic','llm_judge','unit_test'
                            )),
    judge_count             INTEGER NOT NULL DEFAULT 1,
    agreement_score         REAL,       -- computed over output_quality_judges rows
    score_method            TEXT
                            CHECK(score_method IN (
                                'averaged','conservative_min',
                                'needs_review','single_judge'
                            )),

    expected_output         TEXT,
    actual_output           TEXT,

    -- Energy snapshot at judgment time — enables energy-per-quality-point analysis
    energy_uj_at_judgment   INTEGER,

    manual_reviewed         INTEGER NOT NULL DEFAULT 0,
    judged_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(attempt_id),
    FOREIGN KEY (attempt_id) REFERENCES goal_attempt(attempt_id),
    FOREIGN KEY (goal_id)    REFERENCES goal_execution(goal_id)
);

CREATE INDEX IF NOT EXISTS idx_output_qual_attempt
    ON output_quality(attempt_id);
CREATE INDEX IF NOT EXISTS idx_output_qual_goal
    ON output_quality(goal_id);
CREATE INDEX IF NOT EXISTS idx_output_qual_metric
    ON output_quality(metric_type);
CREATE INDEX IF NOT EXISTS idx_output_qual_score
    ON output_quality(normalized_score);
CREATE INDEX IF NOT EXISTS idx_output_qual_method
    ON output_quality(judge_method);

-- ─────────────────────────────────────────────
-- TABLE: output_quality_judges
-- One row per judge per attempt. Evidence trail for reconciled verdict.
-- Supports N judges — no hardcoded judge_1/judge_2 ceiling.
-- judge_prompt_hash: SHA of judge prompt for reproducibility across papers.
-- judge_version/temperature/provider: required for cross-paper judge pipeline comparison.
-- goal_id denormalized for analytics speed.
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS output_quality_judges (
    judge_entry_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    quality_id              INTEGER NOT NULL,
    attempt_id              INTEGER NOT NULL,
    goal_id                 INTEGER NOT NULL,

    judge_model             TEXT NOT NULL,
    judge_provider          TEXT,
    judge_version           TEXT,
    judge_temperature       REAL,
    judge_score             REAL NOT NULL,
    judge_confidence        REAL,
    judge_prompt_hash       TEXT,
    judge_reasoning         TEXT,

    judged_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (quality_id) REFERENCES output_quality(quality_id),
    FOREIGN KEY (attempt_id) REFERENCES goal_attempt(attempt_id),
    FOREIGN KEY (goal_id)    REFERENCES goal_execution(goal_id)
);

CREATE INDEX IF NOT EXISTS idx_oqj_quality
    ON output_quality_judges(quality_id);
CREATE INDEX IF NOT EXISTS idx_oqj_attempt
    ON output_quality_judges(attempt_id);
CREATE INDEX IF NOT EXISTS idx_oqj_goal
    ON output_quality_judges(goal_id);
