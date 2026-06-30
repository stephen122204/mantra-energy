#!/usr/bin/env python3
"""
core/utils/outlier_detector.py

Outlier detection logic for A-LEMS Layer 3 (run_outliers). Implements three
independent detection methods per SPEC_OUTLIER_DETECTION.md:

  Layer 1: domain_rule  -- deterministic, zero false positives, always active
  Layer 2: mad_zscore   -- robust statistic, primary detector for population
                           level anomalies, requires min_population_size
  Layer 3: iqr_fence    -- cross check only, not a primary detector

This module is pure computation. It reads config rows and run rows that are
handed to it; it does not open its own DB connection (Rule EEI style
separation, even though ETL scripts are not bound by EEI-1/2 the way
energy_engine.py is, this module is kept connection free anyway because it
is unit testable in isolation that way).

CQC-5 compliance: functions are kept under 50 lines, split into helpers.
DC-1 compliance: ~30% inline comments explaining WHY, not WHAT.
PVC-1/2 compliance: Python 3.9 syntax only, no | union types, no match/case.
"""

import logging
import statistics
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Modified Z-score constant: the 75th percentile of the standard normal
# distribution. This makes the modified z-score comparable in magnitude to
# a classic z-score when the underlying data is normally distributed, even
# though MAD itself makes no normality assumption.
MAD_CONSTANT = 0.6745

# Severity rank used only for in-memory comparison (max() across methods).
# Not stored in the DB, the DB stores the string directly.
_SEVERITY_RANK = {"informational": 1, "suspect": 2, "extreme": 3}


def _severity_max(a, b):
    # type: (str, str) -> str
    """Return whichever of two severities is more serious."""
    return a if _SEVERITY_RANK[a] >= _SEVERITY_RANK[b] else b


def load_active_config(conn, config_version=1):
    # type: (Any, int) -> Dict[Tuple[str, str], Dict[str, float]]
    """
    Load active outlier_detection_config rows into a lookup dict.

    Returns:
        {(method, metric_name): {parameter_name: parameter_value, ...}}
        e.g. {('mad_zscore', '*'): {'z_threshold_suspect': 3.5, ...}}

    Only rows with effective_to IS NULL are loaded, per the config table's
    versioning convention (Rule SC: no hardcoded thresholds, this is the
    single source of truth for every numeric boundary this module uses).
    """
    cur = conn.execute(
        """
        SELECT method, metric_name, parameter_name, parameter_value
        FROM outlier_detection_config
        WHERE config_version = ? AND effective_to IS NULL
        """,
        (config_version,),
    )
    config = {}  # type: Dict[Tuple[str, str], Dict[str, float]]
    for method, metric_name, param_name, param_value in cur.fetchall():
        key = (method, metric_name)
        # setdefault rather than overwrite, because multiple parameters
        # (e.g. z_threshold_suspect AND z_threshold_extreme) share a key.
        config.setdefault(key, {})[param_name] = param_value
    return config


def compute_mad_zscore(values, target_value):
    # type: (List[float], float) -> Tuple[Optional[float], float, float]
    """
    Compute the modified Z-score of target_value against a population.

    Returns:
        (z_score, population_median, population_mad)
        z_score is None if MAD is 0 (degenerate population, see fallback
        handling in detect_mad_outliers below, this function only computes,
        it does not decide what to do when MAD is 0).
    """
    median_val = statistics.median(values)
    # MAD = median absolute deviation from the median. Robust to extreme
    # outliers in a way a standard deviation is not: a single 100x outlier
    # barely moves the median, but can dominate a standard deviation.
    abs_deviations = [abs(v - median_val) for v in values]
    mad = statistics.median(abs_deviations)

    if mad == 0:
        # Degenerate population: all values identical or nearly so. A
        # division by zero here would be a silent failure (DC-3 violation),
        # so we explicitly signal "undefined" via None and let the caller
        # apply the documented range-check fallback instead.
        return None, median_val, mad

    z = MAD_CONSTANT * (target_value - median_val) / mad
    return z, median_val, mad


def detect_mad_outliers(run_values, config, min_population_size=10):
    # type: (List[Tuple[int, float]], Dict[str, float], int) -> List[Dict[str, Any]]
    """
    Apply MAD z-score detection to a population of (run_id, value) pairs.

    Args:
        run_values: list of (run_id, raw_value) for one metric, one population
        config: parameters for mad_zscore, e.g. {'z_threshold_suspect': 3.5, ...}
        min_population_size: cold start guard, below this only domain rules run

    Returns:
        list of result dicts ready for run_outliers insertion (severity,
        z_score, population_median, population_mad populated; threshold
        fields left for the caller to attach since they depend on direction)
    """
    results = []
    if len(run_values) < min_population_size:
        # Cold start: too few runs for a population level statistic to be
        # meaningful. Domain rules still apply, handled by a separate
        # function, this one simply declines to produce any MAD results.
        logger.debug(
            "Population size %d below min_population_size %d, skipping MAD",
            len(run_values), min_population_size,
        )
        return results

    values = [v for _, v in run_values]
    suspect_z = config.get("z_threshold_suspect", 3.5)
    extreme_z = config.get("z_threshold_extreme", 5.0)

    for run_id, raw_value in run_values:
        z, median_val, mad = compute_mad_zscore(values, raw_value)

        if z is None:
            # MAD = 0 fallback per spec: flag only if the value differs from
            # the median by more than 10%, since z-score is mathematically
            # undefined here, not because the run is necessarily fine.
            if median_val != 0 and abs(raw_value - median_val) / abs(median_val) > 0.10:
                results.append({
                    "run_id": run_id, "raw_value": raw_value,
                    "population_median": median_val, "population_mad": 0.0,
                    "z_score": None, "severity": "informational",
                    "direction": "above" if raw_value > median_val else "below",
                })
            continue

        abs_z = abs(z)
        if abs_z <= suspect_z:
            continue  # not anomalous by this method

        severity = "extreme" if abs_z > extreme_z else "suspect"
        results.append({
            "run_id": run_id, "raw_value": raw_value,
            "population_median": median_val, "population_mad": mad,
            "z_score": z, "severity": severity,
            "direction": "above" if z > 0 else "below",
        })
    return results


def detect_iqr_outliers(run_values, config, min_population_size=10):
    # type: (List[Tuple[int, float]], Dict[str, float], int) -> List[Dict[str, Any]]
    """
    Apply IQR fence detection. Cross check only, per spec Section 3.4: a
    single IQR flag alone never produces 'suspect' or 'extreme' severity,
    only 'informational'. Agreement with MAD is what elevates severity,
    and that elevation happens in resolve_severity, not here.
    """
    results = []
    if len(run_values) < min_population_size:
        return results

    values = sorted(v for _, v in run_values)
    n = len(values)
    # Simple percentile via index, not interpolated. Adequate for the
    # population sizes seen in this project (tens to low hundreds of runs);
    # an interpolated percentile would not materially change the fence at
    # this scale and would add a dependency.
    q1 = values[int(n * 0.25)]
    q3 = values[int(n * 0.75)]
    iqr = q3 - q1
    multiplier = config.get("iqr_multiplier", 2.5)
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr

    for run_id, raw_value in run_values:
        if raw_value < lower or raw_value > upper:
            results.append({
                "run_id": run_id, "raw_value": raw_value,
                "iqr_lower_fence": lower, "iqr_upper_fence": upper,
                "severity": "informational",  # never escalated by IQR alone
                "direction": "above" if raw_value > upper else "below",
            })
    return results


def detect_domain_rule_violations(runs, config_by_metric):
    # type: (List[Dict[str, Any]], Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]
    """
    Apply deterministic domain rules (DR-01 through DR-06). These have no
    cold start requirement and run on every population size, including
    populations of one, because they encode physical/measurement facts
    rather than statistical properties of a distribution.

    Args:
        runs: list of run dicts, each must contain run_id plus whichever
              columns the active domain rules reference
        config_by_metric: {metric_name: {parameter_name: value}}

    Returns:
        list of result dicts, one per (run_id, metric_name) violation
    """
    results = []
    for run in runs:
        run_id = run["run_id"]
        results.extend(_check_min_value_rule(run, run_id, config_by_metric))
        results.extend(_check_overhead_ratio_rule(run, run_id, config_by_metric))
        results.extend(_check_throttle_rule(run, run_id))
        results.extend(_check_coverage_rules(run, run_id, config_by_metric))
    return results


def _check_min_value_rule(run, run_id, config_by_metric):
    # type: (Dict[str, Any], int, Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]
    """DR-01, DR-06: flags values below an absolute floor."""
    out = []
    for metric in ("attributed_energy_uj", "duration_ns"):
        params = config_by_metric.get(metric, {})
        floor = params.get("min_value")
        value = run.get(metric)
        if floor is None or value is None:
            continue
        if value < floor:
            # duration_ns under floor is informational only (possibly an
            # aborted run, not necessarily wrong); attributed_energy_uj
            # under floor is suspect, since every derived ratio downstream
            # becomes meaningless once the denominator nears zero.
            severity = "informational" if metric == "duration_ns" else "suspect"
            out.append({
                "run_id": run_id, "metric_name": metric, "raw_value": value,
                "threshold_violated": floor, "severity": severity,
                "direction": "below",
            })
    return out


def _check_overhead_ratio_rule(run, run_id, config_by_metric):
    # type: (Dict[str, Any], int, Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]
    """DR-02: conservation bound, overhead cannot exceed total energy."""
    overhead = run.get("framework_overhead_energy_uj")
    total = run.get("total_energy_uj")
    if overhead is None or total is None or total <= 0:
        return []
    if overhead > total:
        return [{
            "run_id": run_id, "metric_name": "framework_overhead_energy_uj",
            "raw_value": overhead, "threshold_violated": total,
            "severity": "extreme", "direction": "above",
        }]
    return []


def _check_throttle_rule(run, run_id):
    # type: (Dict[str, Any], int) -> List[Dict[str, Any]]
    """DR-03: thermal throttle flag, deterministic, always suspect."""
    if run.get("thermal_throttle_flag") == 1:
        return [{
            "run_id": run_id, "metric_name": "thermal_throttle_flag",
            "raw_value": 1.0, "threshold_violated": 1.0,
            "severity": "suspect", "direction": None,
        }]
    return []


def _check_coverage_rules(run, run_id, config_by_metric):
    # type: (Dict[str, Any], int, Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]
    """DR-04, DR-05: sample coverage floors for energy and SPBM telemetry."""
    out = []
    for metric in ("energy_sample_coverage_pct", "spbm_sample_coverage_pct"):
        params = config_by_metric.get(metric, {})
        floor = params.get("coverage_floor_pct")
        value = run.get(metric)
        if floor is None or value is None:
            continue
        if value < floor:
            out.append({
                "run_id": run_id, "metric_name": metric, "raw_value": value,
                "threshold_violated": floor, "severity": "suspect",
                "direction": "below",
            })
    return out


def resolve_severity(domain_results, mad_results, iqr_results):
    # type: (List[Dict], List[Dict], List[Dict]) -> Dict[int, str]
    """
    Combine results from all three methods into one effective severity per
    run_id, per spec Section 3.5:
        domain rule alone        -> severity from the rule
        MAD alone                -> informational
        IQR alone                -> informational
        MAD + IQR agree          -> severity from MAD threshold
        domain + MAD + IQR       -> max of all
    Individual rows are still stored separately in run_outliers (one row
    per method per metric); this function is only used where a single
    aggregate severity is needed, e.g. web layer badges.
    """
    by_run = {}  # type: Dict[int, str]
    mad_run_ids = {r["run_id"] for r in mad_results}
    iqr_run_ids = {r["run_id"] for r in iqr_results}

    for r in domain_results:
        rid = r["run_id"]
        by_run[rid] = _severity_max(by_run.get(rid, "informational"), r["severity"])

    for r in mad_results:
        rid = r["run_id"]
        # MAD agreeing with IQR on the same run is what elevates severity
        # above informational, per the agreement rule above.
        sev = r["severity"] if rid in iqr_run_ids else "informational"
        by_run[rid] = _severity_max(by_run.get(rid, "informational"), sev)

    for r in iqr_results:
        rid = r["run_id"]
        by_run.setdefault(rid, "informational")

    return by_run
