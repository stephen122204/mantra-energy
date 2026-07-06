-- s004_outlier_detection_config.sql
-- Outlier detection configuration. Universal, all platforms.
-- Source of truth: GN100 live DB, 2026-07-05 (v79/v80 migrations).
-- See SPEC_SEED_DATA_COMPLETE.md for classification rules.

INSERT OR IGNORE INTO outlier_detection_config
    (config_version, method, metric_name, parameter_name, parameter_value,
     description, outlier_class) VALUES
-- Statistical methods (apply to all metrics via wildcard)
(1, 'mad_zscore', '*', 'z_threshold_suspect', 3.5,
 'Modified Z-score suspect boundary, |Z| > 3.5',
 'statistical_anomaly'),

(1, 'mad_zscore', '*', 'z_threshold_extreme', 5.0,
 'Modified Z-score extreme boundary, |Z| > 5.0',
 'statistical_anomaly'),

(1, 'mad_zscore', '*', 'min_population_size', 10.0,
 'Minimum runs in population before MAD activates. Below this, only domain rules apply.',
 'statistical_anomaly'),

(1, 'iqr_fence', '*', 'iqr_multiplier', 2.5,
 'Conservative IQR multiplier, deliberately wider than the standard 1.5x to avoid trimming legitimate distribution tails',
 'statistical_anomaly'),

(1, 'iqr_fence', '*', 'min_population_size', 10.0,
 'Minimum runs in population before IQR fence activates',
 'statistical_anomaly'),

-- Domain rules (metric-specific physical/logical constraints)
(1, 'domain_rule', 'attributed_energy_uj', 'min_value', 1000.0,
 'DR-01: near zero denominator guard, 1 mJ floor. Below this, all derived ratios (overhead pct, EpG) are dominated by noise, not signal.',
 'data_quality_failure'),

(1, 'domain_rule', 'framework_overhead_energy_uj', 'max_ratio_to_total', 1.0,
 'DR-02: conservation bound. framework_overhead_energy_uj cannot exceed total_energy_uj on the same run. Physically impossible if violated, always severity extreme.',
 'data_quality_failure'),

(1, 'domain_rule', 'thermal_throttle_flag', 'flag_value', 1.0,
 'DR-03: any thermal throttle flags the run. Not a measurement error, but performance characteristics are altered and not representative of nominal conditions.',
 'statistical_anomaly'),

(1, 'domain_rule', 'energy_sample_coverage_pct', 'coverage_floor_pct', 50.0,
 'DR-04: minimum acceptable energy sample coverage. Below this, energy values are extrapolated from too few samples to trust.',
 'data_quality_failure'),

(1, 'domain_rule', 'spbm_sample_coverage_pct', 'coverage_floor_pct', 50.0,
 'DR-05: same as DR-04 for SPBM telemetry coverage, GN100 specific.',
 'data_quality_failure'),

(1, 'domain_rule', 'duration_ns', 'min_value', 100000000.0,
 'DR-06: suspiciously short run, under 100ms. Possibly aborted or framework only, severity informational pending review.',
 'statistical_anomaly');
