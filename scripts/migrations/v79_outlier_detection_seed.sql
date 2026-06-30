-- =============================================================================
-- Migration 044: Outlier Detection (seed data)
-- =============================================================================
-- Schema version target: 79. Companion to 044_outlier_detection_schema.sql.
-- MSC-4 compliance: this file is data only (INSERT). No ALTER, no CREATE.
-- Must be applied after 044_outlier_detection_schema.sql, never before.
--
-- config_version = 1, the initial threshold set. Any future tuning is a new
-- config_version row with effective_to set on the old rows, never an UPDATE
-- of parameter_value in place (preserves an audit trail of what threshold
-- was active when any given run was flagged).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- MAD z-score thresholds (Layer 2: robust statistical detector)
-- -----------------------------------------------------------------------------
INSERT INTO outlier_detection_config
    (config_version, method, metric_name, parameter_name, parameter_value, description)
VALUES
    (1, 'mad_zscore', '*', 'z_threshold_suspect',  3.5,
        'Modified Z-score suspect boundary, |Z| > 3.5'),
    (1, 'mad_zscore', '*', 'z_threshold_extreme',  5.0,
        'Modified Z-score extreme boundary, |Z| > 5.0'),
    (1, 'mad_zscore', '*', 'min_population_size', 10.0,
        'Minimum runs in population before MAD activates. Below this, only domain rules apply.');

-- -----------------------------------------------------------------------------
-- IQR fence thresholds (Layer 3: cross check, not a primary detector)
-- -----------------------------------------------------------------------------
INSERT INTO outlier_detection_config
    (config_version, method, metric_name, parameter_name, parameter_value, description)
VALUES
    (1, 'iqr_fence', '*', 'iqr_multiplier',       2.5,
        'Conservative IQR multiplier, deliberately wider than the standard 1.5x to avoid trimming legitimate distribution tails'),
    (1, 'iqr_fence', '*', 'min_population_size', 10.0,
        'Minimum runs in population before IQR fence activates');

-- -----------------------------------------------------------------------------
-- Domain rules (Layer 1: deterministic, zero cold start, always active)
-- -----------------------------------------------------------------------------
INSERT INTO outlier_detection_config
    (config_version, method, metric_name, parameter_name, parameter_value, description)
VALUES
    (1, 'domain_rule', 'attributed_energy_uj', 'min_value', 1000.0,
        'DR-01: near zero denominator guard, 1 mJ floor. Below this, all derived ratios (overhead pct, EpG) are dominated by noise, not signal.'),
    (1, 'domain_rule', 'framework_overhead_energy_uj', 'max_ratio_to_total', 1.0,
        'DR-02: conservation bound. framework_overhead_energy_uj cannot exceed total_energy_uj on the same run. Physically impossible if violated, always severity extreme.'),
    (1, 'domain_rule', 'thermal_throttle_flag', 'flag_value', 1.0,
        'DR-03: any thermal throttle flags the run. Not a measurement error, but performance characteristics are altered and not representative of nominal conditions.'),
    (1, 'domain_rule', 'energy_sample_coverage_pct', 'coverage_floor_pct', 50.0,
        'DR-04: minimum acceptable energy sample coverage. Below this, energy values are extrapolated from too few samples to trust.'),
    (1, 'domain_rule', 'spbm_sample_coverage_pct', 'coverage_floor_pct', 50.0,
        'DR-05: same as DR-04 for SPBM telemetry coverage, GN100 specific.'),
    (1, 'domain_rule', 'duration_ns', 'min_value', 100000000.0,
        'DR-06: suspiciously short run, under 100ms. Possibly aborted or framework only, severity informational pending review.');
