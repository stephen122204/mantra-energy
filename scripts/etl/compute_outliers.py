#!/usr/bin/env python3
"""
scripts/etl/compute_outliers.py

Batch outlier detection. Reads runs grouped by population
(task_name|workflow_type), applies domain rules, MAD z-score, and IQR fence
detection from core/utils/outlier_detector.py, and upserts results into
run_outliers.

Run modes (matches the --run-id / --backfill-all / --db convention used by
phase_attribution_etl.py and energy_derived_metrics_etl.py):
    python scripts/etl/compute_outliers.py --dry-run
    python scripts/etl/compute_outliers.py --backfill-all
    python scripts/etl/compute_outliers.py --db /mnt/alems-data/gn100-2b96/experiments.db

This script is platform agnostic (MSC-3): population_key is always computed
within a single DB, so it never needs to know which machine it is running
on. The caller selects the DB via path_loader.get_alems_db_path() or --db.

Never run against the frozen Paper 1 snapshot databases. This script does
not currently enforce that programmatically (Rule OD-3 calls for migration
scripts to refuse frozen DBs; this is a detection script, not a migration,
but the same caution applies and is enforced here defensively).
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# scripts/etl/compute_outliers.py -> repo root is two parents up
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "tools"))

from core.utils.outlier_detector import (  # noqa: E402
    detect_domain_rule_violations,
    detect_iqr_outliers,
    detect_mad_outliers,
    load_active_config,
)
from path_loader import get_alems_db_path  # noqa: E402

logger = logging.getLogger(__name__)

# Defensive guard against accidentally pointing this at a frozen snapshot.
# Filename based, not foolproof, but catches the common mistake of copying
# a build command that still references the paper1 snapshot path.
_FROZEN_DB_MARKERS = ("sigmetrics_paper1",)


def _refuse_if_frozen(db_path):
    # type: (str) -> None
    """Raise if db_path looks like a frozen snapshot. See module docstring."""
    for marker in _FROZEN_DB_MARKERS:
        if marker in db_path:
            raise SystemExit(
                "Refusing to run compute_outliers.py against {}: filename "
                "matches a frozen snapshot marker ('{}'). Frozen Paper 1 "
                "snapshots are read only references, not detection "
                "targets.".format(db_path, marker)
            )


def _metrics_for_population_scan():
    # type: () -> List[str]
    """
    Metrics scanned by MAD and IQR per population, per spec Section 3.3.
    Domain rules are checked separately in detect_domain_rule_violations
    and are not population scoped, so they are not listed here.
    """
    return [
        "total_energy_uj", "dynamic_energy_uj", "avg_power_watts",
        "duration_ns", "framework_overhead_energy_uj", "gpu_total_energy_uj",
        "gpu_dynamic_energy_uj", "pkg_energy_uj", "dram_energy_uj",
    ]


def load_run_population(conn, metric, exp_type_filter=("normal",)):
    # type: (sqlite3.Connection, str, tuple) -> Dict[str, List[tuple]]
    """
    Load (run_id, value) pairs for one metric, grouped by population_key.

    Restricted to experiment_type IN exp_type_filter and e.is_valid = 1
    (Layer 1) by default, mirroring the existing v_quality_energy_frontier
    convention of scoping analytical queries to "real" experiments, not
    calibration/debug/pilot runs which would pollute population statistics.

    NULL values for the metric are excluded, since a NULL is "not measured"
    (MIC-1), not "measured as zero", and including it would corrupt the
    population's median/MAD.
    """
    query = """
        SELECT r.run_id, e.task_name, r.workflow_type,
               COALESCE(e.model_name, 'unknown') AS model_name,
               COALESCE(hc.hostname, CAST(e.hw_id AS TEXT), 'unknown') AS hostname,
               r.{metric}
        FROM runs r
        JOIN experiments e ON r.exp_id = e.exp_id
        LEFT JOIN hardware_config hc ON e.hw_id = hc.hw_id
        WHERE e.is_valid = 1
          AND r.{metric} IS NOT NULL
          AND e.experiment_type IN ({placeholders})
    """.format(
        metric=metric,
        placeholders=",".join("?" for _ in exp_type_filter),
    )
    cur = conn.execute(query, exp_type_filter)

    populations = {}  # type: Dict[str, List[tuple]]
    for run_id, task_name, workflow_type, model_name, hostname, value in cur.fetchall():
        # gpu_total_energy_uj / gpu_dynamic_energy_uj are 0 on x86 platforms
        # by design (no GPU). Including the long tail of legitimate zeros
        # in a GPU population would bias the median toward zero and bury
        # genuine GPU anomalies. Skip exact zero only for GPU metrics.
        if metric.startswith("gpu_") and value == 0:
            continue
        key = "{}|{}|{}|{}".format(task_name, workflow_type, model_name, hostname)
        populations.setdefault(key, []).append((run_id, value))
    return populations


def run_detection(conn, config_version=1, dry_run=False):
    # type: (sqlite3.Connection, int, bool) -> List[Dict[str, Any]]
    """
    Full detection pass: domain rules first (always active), then MAD and
    IQR per population for each scanned metric. Returns the flat list of
    result rows ready for upsert (or for printing, if dry_run).
    """
    config = load_active_config(conn, config_version)
    results = []

    results.extend(_run_domain_rules(conn, config))

    for metric in _metrics_for_population_scan():
        results.extend(_run_statistical_detection(conn, metric, config, config_version))

    if dry_run:
        _print_summary(results)
    else:
        _upsert_results(conn, results, config_version)

    return results


def _run_domain_rules(conn, config):
    # type: (sqlite3.Connection, Dict) -> List[Dict[str, Any]]
    """Domain rules need full run rows, not just one metric column."""
    cur = conn.execute(
        """
        SELECT run_id, attributed_energy_uj, duration_ns,
               framework_overhead_energy_uj, total_energy_uj,
               thermal_throttle_flag, energy_sample_coverage_pct,
               spbm_sample_coverage_pct
        FROM runs r JOIN experiments e ON r.exp_id = e.exp_id
        WHERE e.is_valid = 1 AND e.experiment_type = 'normal'
        """
    )
    cols = [d[0] for d in cur.description]
    runs = [dict(zip(cols, row)) for row in cur.fetchall()]

    config_by_metric = {}
    for (method, metric_name), params in config.items():
        if method == "domain_rule":
            config_by_metric[metric_name] = params

    violations = detect_domain_rule_violations(runs, config_by_metric)
    for v in violations:
        v["detection_method"] = "domain_rule"
        v["population_key"] = "n/a"
        v["population_size"] = len(runs)
    return violations


def _run_statistical_detection(conn, metric, config, config_version):
    # type: (sqlite3.Connection, str, Dict, int) -> List[Dict[str, Any]]
    """MAD and IQR for one metric, applied independently per population."""
    populations = load_run_population(conn, metric)
    mad_params = config.get(("mad_zscore", "*"), {})
    iqr_params = config.get(("iqr_fence", "*"), {})
    min_pop = int(mad_params.get("min_population_size", 10))

    out = []
    for pop_key, run_values in populations.items():
        mad_results = detect_mad_outliers(run_values, mad_params, min_pop)
        iqr_results = detect_iqr_outliers(run_values, iqr_params, min_pop)
        for r in mad_results:
            r.update(metric_name=metric, detection_method="mad_zscore",
                      population_key=pop_key, population_size=len(run_values),
                      threshold_violated=r.get("z_score") or 0.0)
            out.append(r)
        for r in iqr_results:
            r.update(metric_name=metric, detection_method="iqr_fence",
                      population_key=pop_key, population_size=len(run_values),
                      threshold_violated=r.get("iqr_upper_fence")
                      if r.get("direction") == "above"
                      else r.get("iqr_lower_fence"))
            out.append(r)
    return out


def _load_outlier_class_lookup(conn, config_version):
    # type: (sqlite3.Connection, int) -> Dict[Tuple[str, str], str]
    """
    Build a (method, metric_name) -> outlier_class lookup from
    outlier_detection_config. mad_zscore and iqr_fence are always
    statistical_anomaly regardless of metric, since both methods detect
    unusual-but-plausible values by definition, never measurement
    failure. domain_rule rows look up their specific outlier_class from
    config, since some domain rules are data quality failures (coverage
    floors) and others are statistical anomalies (thermal throttle,
    short duration).
    """
    cur = conn.execute(
        "SELECT method, metric_name, outlier_class FROM outlier_detection_config "
        "WHERE config_version = ? AND effective_to IS NULL",
        (config_version,),
    )
    lookup = {}
    for method, metric_name, outlier_class in cur.fetchall():
        lookup[(method, metric_name)] = outlier_class or "data_quality_failure"
    return lookup


def _resolve_outlier_class(r, class_lookup):
    # type: (Dict[str, Any], Dict[Tuple[str, str], str]) -> str
    """
    mad_zscore and iqr_fence are always statistical_anomaly. domain_rule
    rows consult class_lookup keyed on (method, metric_name); falls back
    to data_quality_failure if no config row matches, matching the
    column's DEFAULT in the schema.
    """
    method = r["detection_method"]
    if method in ("mad_zscore", "iqr_fence"):
        return "statistical_anomaly"
    return class_lookup.get((method, r.get("metric_name", "n/a")), "data_quality_failure")


def _upsert_results(conn, results, config_version):
    # type: (sqlite3.Connection, List[Dict[str, Any]], int) -> None
    """
    INSERT OR REPLACE keyed on (run_id, metric_name, detection_method), per
    the UNIQUE constraint on run_outliers. Re-running detection with the
    same config_version is therefore idempotent. review_status is NOT
    touched here on conflict for rows a human has already reviewed; see the
    guard below.
    """
    class_lookup = _load_outlier_class_lookup(conn, config_version)

    for r in results:
        # Never clobber a human review. If a row already exists and has
        # been reviewed (not 'pending'), skip rewriting it on this pass;
        # only fresh detections get inserted/updated.
        existing = conn.execute(
            "SELECT review_status FROM run_outliers "
            "WHERE run_id=? AND metric_name=? AND detection_method=?",
            (r["run_id"], r.get("metric_name", "n/a"), r["detection_method"]),
        ).fetchone()
        if existing and existing[0] != "pending":
            logger.debug(
                "Skipping run_id=%s metric=%s, already reviewed (%s)",
                r["run_id"], r.get("metric_name"), existing[0],
            )
            continue

        outlier_class = _resolve_outlier_class(r, class_lookup)

        conn.execute(
            """
            INSERT OR REPLACE INTO run_outliers
                (run_id, metric_name, detection_method, detection_version,
                 population_key, population_size, raw_value,
                 population_median, population_mad, z_score,
                 iqr_lower_fence, iqr_upper_fence, threshold_violated,
                 direction, severity, detection_status, review_status,
                 outlier_class)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'flagged', 'pending', ?)
            """,
            (
                r["run_id"], r.get("metric_name", "n/a"), r["detection_method"],
                config_version, r.get("population_key", "n/a"),
                r.get("population_size", 0), r.get("raw_value", 0.0),
                r.get("population_median"), r.get("population_mad"),
                r.get("z_score"), r.get("iqr_lower_fence"),
                r.get("iqr_upper_fence"), r.get("threshold_violated", 0.0),
                r.get("direction"), r["severity"], outlier_class,
            ),
        )
    conn.commit()
    logger.info("Upserted %d outlier rows (config_version=%d)", len(results), config_version)


def _print_summary(results):
    # type: (List[Dict[str, Any]]) -> None
    """Dry run output: counts by severity and method, no DB writes."""
    by_severity = {}  # type: Dict[str, int]
    for r in results:
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1
    print("Dry run: {} candidate outlier rows".format(len(results)))
    for sev, count in sorted(by_severity.items()):
        print("  {}: {}".format(sev, count))


def main():
    # type: () -> None
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None,
                         help="Override DB path, default: get_alems_db_path()")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print summary only, do not write to run_outliers")
    parser.add_argument("--backfill-all", action="store_true",
                         help="Run detection across all populations (current default behavior)")
    parser.add_argument("--config-version", type=int, default=1,
                         help="outlier_detection_config version to use")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    db_path = args.db or get_alems_db_path()
    _refuse_if_frozen(db_path)

    conn = sqlite3.connect(db_path)
    try:
        run_detection(conn, config_version=args.config_version, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
