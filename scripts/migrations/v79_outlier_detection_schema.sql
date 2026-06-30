-- =============================================================================
-- Migration 044: Outlier Detection (DDL only)
-- =============================================================================
-- Schema version target: 79
-- A-LEMS Layer 3 of the three layer data selection model:
--   L1 experiments.is_valid          -- experimenter intent
--   L2 run_quality.experiment_valid  -- hardware/sampling quality
--   L3 run_outliers.review_status    -- statistical anomaly, human reviewed
--
-- MSC-4 compliance: this file is DDL only (CREATE TABLE, CREATE INDEX,
-- CREATE VIEW). Seed data lives in 044_outlier_detection_seed.sql.
--
-- MSC-3 compliance: this file is platform agnostic. No machine specific
-- branching. Applies identically to GN100 and UBUNTU2505.
--
-- Forward only. Do NOT apply to frozen Paper 1 snapshot databases
-- (experiments_gn100_sigmetrics_paper1.db, experiments_ub2505_sigmetrics_paper1.db).
-- Those are read only DDL references for this project, not migration targets.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- outlier_detection_config
-- Versioned detection parameters. SC compliance: no hardcoded thresholds in
-- Python, every parameter is a row here so a config change is an INSERT plus
-- an effective_to update, never a code edit (CQC-6).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outlier_detection_config (
    config_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    config_version      INTEGER NOT NULL,
    method               TEXT NOT NULL,
    -- 'mad_zscore', 'iqr_fence', 'domain_rule'
    metric_name           TEXT NOT NULL,
    -- '*' for domain rules that apply across all metrics
    parameter_name         TEXT NOT NULL,
    -- e.g. 'z_threshold_suspect', 'iqr_multiplier', 'min_value'
    parameter_value          REAL NOT NULL,
    description                TEXT,
    effective_from               TIMESTAMP NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),
    effective_to                   TIMESTAMP,
    -- NULL means currently active. Old rows are never deleted (MSC-1 style
    -- immutability extended here by convention, not enforced by the DB).
    created_at                       TIMESTAMP NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),

    UNIQUE(config_version, method, metric_name, parameter_name)
);

CREATE INDEX IF NOT EXISTS idx_odc_active
    ON outlier_detection_config(method, metric_name)
    WHERE effective_to IS NULL;

-- -----------------------------------------------------------------------------
-- run_outliers
-- One row per (run_id, metric_name, detection_method). A single run can have
-- multiple rows when several metrics or methods flag it independently.
-- Backward compat (SC-5): purely additive, no existing table is altered.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS run_outliers (
    outlier_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                 INTEGER NOT NULL,
    metric_name              TEXT NOT NULL,
    -- e.g. 'total_energy_uj', 'attributed_energy_uj', 'framework_overhead_energy_uj'

    -- Detection metadata
    detection_method           TEXT NOT NULL,
    -- 'mad_zscore', 'iqr_fence', 'domain_rule'
    detection_version            INTEGER NOT NULL,
    -- links to outlier_detection_config.config_version active at detection time
    population_key                 TEXT NOT NULL,
    -- 'task_name|workflow_type', e.g. 'gsm8k_basic|linear'. Computed within
    -- a single platform DB, never cross platform (GN100 and UBUNTU2505 have
    -- different baselines and must not share a population).
    population_size                  INTEGER NOT NULL,
    -- size of the population at detection time, for cold start auditing

    -- Values
    raw_value                          REAL NOT NULL,
    population_median                    REAL,
    -- NULL for domain rules, which do not reference a population
    population_mad                         REAL,
    -- NULL for domain rules and IQR fence
    z_score                                  REAL,
    -- NULL for domain rules and IQR fence
    iqr_lower_fence                            REAL,
    -- NULL for MAD and domain rules
    iqr_upper_fence                              REAL,
    -- NULL for MAD and domain rules
    threshold_violated                             REAL NOT NULL,
    -- the actual bound that was crossed, in the same unit as raw_value
    direction                                        TEXT,
    -- 'above', 'below', or NULL for domain rules without a direction concept

    -- Classification
    severity                                           TEXT NOT NULL DEFAULT 'informational',
    -- 'informational', 'suspect', 'extreme'
    detection_status                                     TEXT NOT NULL DEFAULT 'flagged',
    -- only value the detector itself ever writes. Distinct from review_status,
    -- which is set only by a human (or recalibration), never by the detector.

    -- Human review, independent of detection (PDS / EIC style gated review)
    review_status                                          TEXT NOT NULL DEFAULT 'pending',
    -- 'pending', 'dismissed', 'confirmed', 'recalibrated'
    reviewed_by                                              TEXT,
    reviewed_at                                                TIMESTAMP,
    review_note                                                  TEXT,

    detected_at                                                    TIMESTAMP NOT NULL
        DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),

    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    UNIQUE(run_id, metric_name, detection_method)
);

CREATE INDEX IF NOT EXISTS idx_ro_run         ON run_outliers(run_id);
CREATE INDEX IF NOT EXISTS idx_ro_review      ON run_outliers(review_status);
CREATE INDEX IF NOT EXISTS idx_ro_severity    ON run_outliers(severity);
CREATE INDEX IF NOT EXISTS idx_ro_population  ON run_outliers(population_key);
CREATE INDEX IF NOT EXISTS idx_ro_confirmed   ON run_outliers(run_id)
    WHERE review_status = 'confirmed';

-- -----------------------------------------------------------------------------
-- v_runs_clean
-- Master filtering view, applies all three layers (L1+L2+L3). Single entry
-- point for analytical queries and paper builds going forward.
-- Existing views (v_energy, v_attribution_summary, etc.) are left untouched
-- per SC-5 backward compat; this is a new, additive view only.
-- -----------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_runs_clean AS
SELECT r.*
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
LEFT JOIN run_quality rq ON r.run_id = rq.run_id
WHERE
    e.is_valid = 1
    AND COALESCE(rq.experiment_valid, 1) = 1
    AND r.run_id NOT IN (
        SELECT DISTINCT run_id
        FROM run_outliers
        WHERE review_status = 'confirmed'
    );

-- -----------------------------------------------------------------------------
-- v_runs_unfiltered
-- Explicit raw access view. Shows every layer's verdict side by side without
-- filtering anything out, for debugging and the web layer review queue.
-- -----------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_runs_unfiltered AS
SELECT r.*,
    e.is_valid AS exp_is_valid,
    rq.experiment_valid AS quality_valid,
    rq.quality_score,
    CASE WHEN ro.run_id IS NOT NULL THEN 1 ELSE 0 END AS has_outlier_flags,
    ro.max_severity
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
LEFT JOIN run_quality rq ON r.run_id = rq.run_id
LEFT JOIN (
    SELECT run_id,
        CASE MAX(CASE severity
            WHEN 'extreme' THEN 3
            WHEN 'suspect' THEN 2
            ELSE 1 END)
            WHEN 3 THEN 'extreme'
            WHEN 2 THEN 'suspect'
            ELSE 'informational'
        END AS max_severity
    FROM run_outliers
    GROUP BY run_id
) ro ON r.run_id = ro.run_id;

-- -----------------------------------------------------------------------------
-- schema_version bump (Rule SC-7)
-- -----------------------------------------------------------------------------
INSERT INTO schema_version (version, applied_at, description)
VALUES (
    79,
    datetime('now'),
    'Outlier detection (L3 layer): outlier_detection_config, run_outliers, v_runs_clean, v_runs_unfiltered. runs.experiment_valid documented as DEPRECATED, always 1, never wired up. Use run_quality.experiment_valid or v_runs_clean instead.'
);
