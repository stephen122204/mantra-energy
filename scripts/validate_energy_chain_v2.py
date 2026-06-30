#!/usr/bin/env python3
"""
validate_energy_chain_v2.py — Platform-aware energy chain validator.

Emits structured JSON with numeric facts and PASS/FAIL/N/A/DM status.
No interpretive text in this file. Interpretation lives in report_energy_chain.py.

Two-layer architecture:
  validate_energy_chain_v2.py  →  JSON (facts + status)
  report_energy_chain.py       →  Human-readable display

Per spec validator_rewrite_spec_v2.md §1, §12.

Usage:
  python validate_energy_chain_v2.py --exp-id 144
  python validate_energy_chain_v2.py --latest
  python validate_energy_chain_v2.py --run-id 1378
  python validate_energy_chain_v2.py --all-valid
  python validate_energy_chain_v2.py --exp-id 144 --json-only
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# All imports from flat energy_chain directory
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from platform_config import get_platform_config
from dag_validator import validate_dag
from proc_attr_validator import validate_proc_attr
from check_validators import (
    validate_boundary,
    validate_activity_decomp,
    validate_phase_partition,
    validate_goal_aggregation,
)

# Also need alems-platform imports for DB path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
try:
    from scripts.tools.path_loader import get_alems_db_path
    DB_PATH = get_alems_db_path()
except ImportError:
    DB_PATH = "data/experiments.db"


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform(conn, run_id):
    # type: (sqlite3.Connection, int) -> str
    """
    Detect platform from DB data for this run.
    Returns: 'arm_spbm', 'x86_rapl', 'macos_iokit', 'unknown'
    Never raises.
    """
    try:
        row = conn.execute(
            "SELECT energy_measurement_mode FROM runs WHERE run_id=?",
            (run_id,)
        ).fetchone()
        if row and row[0]:
            mode = (row[0] or "").lower()
            if "spbm" in mode:
                return "arm_spbm"
            if "measured" in mode or "rapl" in mode:
                return "x86_rapl"
            if "iokit" in mode:
                return "macos_iokit"

        # Fallback: check SPBM data presence
        spbm = conn.execute("""
            SELECT COUNT(*) FROM energy_sample_domains esd
            JOIN energy_domains ed ON ed.domain_id = esd.domain_id
            WHERE esd.run_id = ? AND ed.name = 'PACKAGE'
        """, (run_id,)).fetchone()
        if spbm and spbm[0] > 0:
            return "arm_spbm"

        # Fallback: check RAPL samples
        rapl = conn.execute(
            "SELECT COUNT(*) FROM energy_samples WHERE run_id=?", (run_id,)
        ).fetchone()
        if rapl and rapl[0] > 0:
            return "x86_rapl"

    except Exception as e:
        logger.warning("detect_platform: run=%d error=%s", run_id, e)

    return "unknown"


# ---------------------------------------------------------------------------
# Run data fetcher
# ---------------------------------------------------------------------------

def fetch_run(conn, run_id):
    # type: (sqlite3.Connection, int) -> Optional[dict]
    """Fetch all run data needed for validation."""
    row = conn.execute("""
        SELECT r.run_id, r.workflow_type, e.provider,
            r.duration_ns, r.task_duration_ns,
            r.pkg_energy_uj, r.core_energy_uj,
            r.uncore_energy_uj, r.dram_energy_uj,
            r.baseline_energy_uj, r.dynamic_energy_uj,
            r.attributed_energy_uj, r.cpu_fraction,
            r.pre_task_energy_uj, r.post_task_energy_uj,
            r.framework_overhead_energy_uj,
            r.planning_energy_uj, r.execution_energy_uj,
            r.synthesis_energy_uj, r.inter_phase_energy_uj,
            r.phase_sample_coverage_pct,
            r.avg_power_watts, r.energy_per_token,
            r.energy_per_instruction, r.energy_sample_coverage_pct,
            r.gpu_total_energy_uj, r.gpu_dynamic_energy_uj,
            r.gpu_spbm_total_uj, r.gpu_attribution_method,
            r.energy_measurement_mode
        FROM runs r
        LEFT JOIN experiments e ON e.exp_id=r.exp_id
        WHERE r.run_id=?
    """, (run_id,)).fetchone()
    return dict(row) if row else None


def fetch_energy_attribution(conn, run_id):
    # type: (sqlite3.Connection, int) -> Optional[dict]
    """Fetch energy_attribution row for this run."""
    row = conn.execute("""
        SELECT ea.*
        FROM energy_attribution ea
        WHERE ea.run_id = ?
    """, (run_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Confidence for IDLE-SPLIT and PROC-ATTR (simple, not DAG-based)
# ---------------------------------------------------------------------------

def _simple_confidence(n_samples, platform_config, check_name):
    # type: (int, dict, str) -> dict
    """Simple confidence for non-DAG checks (no residual calibration)."""
    from confidence import sample_score, source_score, confidence_level
    s = sample_score(n_samples)
    src = source_score(check_name, platform_config)
    if src is None:
        score = s
    else:
        score = round(0.6 * s + 0.4 * src, 2)
    return {
        'score':      score,
        'level':      confidence_level(score),
        'components': {'sample': round(s, 2), 'source': src},
    }


# ---------------------------------------------------------------------------
# Per-run validation
# ---------------------------------------------------------------------------

def validate_run(conn, run_id):
    # type: (sqlite3.Connection, int) -> dict
    """
    Validate one run. Returns structured dict with all check results.
    """
    run_row = fetch_run(conn, run_id)
    if not run_row:
        return {'run_id': run_id, 'error': 'run not found'}

    ea_row   = fetch_energy_attribution(conn, run_id)
    # background_energy_uj lives in energy_attribution, not runs
    if ea_row and ea_row.get('background_energy_uj'):
        run_row['background_energy_uj'] = ea_row['background_energy_uj']
    else:
        dyn = run_row.get('dynamic_energy_uj') or 0
        attr = run_row.get('attributed_energy_uj') or 0
        run_row['background_energy_uj'] = max(0, dyn - attr)
    platform = detect_platform(conn, run_id)
    config   = get_platform_config(platform)
    wf       = run_row.get('workflow_type') or 'unknown'

    # ── DAG validation (C1/C2/C3) ────────────────────────────────────────
    dag_result = validate_dag(conn, run_id, platform, run_row, wf)

    # ── Process attribution ───────────────────────────────────────────────
    proc_attr = validate_proc_attr(
        conn, run_id, platform, run_row, dag_result['dag_nodes']
    )

    # ── IDLE-SPLIT ────────────────────────────────────────────────────────
    pkg_uj  = run_row.get('pkg_energy_uj') or 0
    base_uj = run_row.get('baseline_energy_uj') or 0
    dyn_uj  = run_row.get('dynamic_energy_uj') or 0
    delta_idle = abs(pkg_uj - (base_uj + dyn_uj))
    n_pkg_samples = (dag_result['dag_nodes'].get('pkg') or {}).get('n_samples', 0)
    idle_split = {
        'status':    'OK' if delta_idle <= 1000 else 'FAIL',
        'e_pkg_j':   round(pkg_uj / 1e6, 4),
        'e_idle_j':  round(base_uj / 1e6, 4),
        'e_dyn_j':   round(dyn_uj / 1e6, 4),
        'idle_pct':  round(100.0 * base_uj / pkg_uj, 2) if pkg_uj > 0 else 0,
        'dyn_pct':   round(100.0 * dyn_uj / pkg_uj, 2) if pkg_uj > 0 else 0,
        'delta_uj':  round(delta_idle, 0),
        'confidence': _simple_confidence(n_pkg_samples, config, 'ML1-INT'),
    }

    # ── Boundary ─────────────────────────────────────────────────────────
    boundary = validate_boundary(run_row, platform)

    # ── Activity decomposition ────────────────────────────────────────────
    activity = validate_activity_decomp(run_row, ea_row)

    # ── Phase partition ───────────────────────────────────────────────────
    sample_interval_ms = config.get('sample_interval_ms')
    phase = validate_phase_partition(run_row, conn, run_id, sample_interval_ms)

    # ── Goal aggregation ─────────────────────────────────────────────────
    goal = validate_goal_aggregation(conn, run_id, run_row, dag_result['dag_nodes'])

    # ── Power check ───────────────────────────────────────────────────────
    task_dur_ns = run_row.get('task_duration_ns') or 0
    apwr        = run_row.get('avg_power_watts') or 0
    power_check = {'status': 'N/A'}
    if task_dur_ns > 0 and dyn_uj > 0:
        computed_w = (dyn_uj / 1e6) / (task_dur_ns / 1e9)
        delta_w    = abs(computed_w - apwr)
        power_check = {
            'status':     'OK' if delta_w <= 0.5 else 'FAIL',
            'stored_w':   round(apwr, 3),
            'computed_w': round(computed_w, 3),
            'delta_w':    round(delta_w, 3),
        }

    # ── Assemble result ───────────────────────────────────────────────────
    checks = {
        'idle_split':        idle_split,
        'proc_attr_cpu':     proc_attr.get('proc_attr_cpu', {}),
        'proc_attr_gpu':     proc_attr.get('proc_attr_gpu', {}),
        'proc_attr_combined': proc_attr.get('proc_attr_combined', {}),
        'boundary':          boundary,
        'activity_decomp':   activity,
        'phase_partition':   phase,
        'goal_aggregation':  goal,
        'power':             power_check,
    }
    # Merge DAG checks (ML1-INT, ML0-ML1, ML1-ML2)
    checks.update(dag_result['checks'])

    # ── Summary counts ────────────────────────────────────────────────────
    statuses = [v.get('status', '') for v in checks.values()]
    summary = {
        'ok':           statuses.count('OK'),
        'warn':         statuses.count('WARN'),
        'fail':         statuses.count('FAIL'),
        'n_a':          statuses.count('N/A'),
        'data_missing': statuses.count('DM'),
    }

    # Overall run confidence: mean of check confidences
    confs = [
        v.get('confidence', {}).get('score')
        for v in checks.values()
        if v.get('confidence')
    ]
    run_confidence = round(sum(confs) / len(confs), 2) if confs else None

    return {
        'run_id':        run_id,
        'workflow_type': wf,
        'provider':      run_row.get('provider'),
        'platform':      platform,
        'checks':        checks,
        'dag_nodes':     {
            k: {'energy_j': v.get('energy_j'), 'n_samples': v.get('n_samples')}
            for k, v in dag_result['dag_nodes'].items()
        },
        'diagnostic_channels': {
            k: {'energy_j': v.get('energy_j')}
            for k, v in dag_result['diagnostic_channels'].items()
        },
        'derived':          dag_result['derived'],
        'summary':          summary,
        'run_confidence':   run_confidence,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # type: () -> None
    parser = argparse.ArgumentParser(
        description="A-LEMS platform-aware energy chain validator (v2)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--exp-id",    type=int)
    group.add_argument("--run-id",    type=int)
    group.add_argument("--latest",    action="store_true")
    group.add_argument("--all-valid", action="store_true")
    parser.add_argument("--experiment-type")
    parser.add_argument("--db",        default=DB_PATH)
    parser.add_argument("--json-only", action="store_true",
                        help="Emit JSON only, no human display")
    parser.add_argument("--json-out",  type=str,
                        help="Write JSON to file instead of stdout")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(json.dumps({"error": f"DB not found: {args.db}"}))
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Resolve experiment IDs
    if args.run_id:
        row = conn.execute(
            "SELECT exp_id FROM runs WHERE run_id=?", (args.run_id,)
        ).fetchone()
        exp_ids = [row[0]] if row else []
        single_run = args.run_id
    elif args.all_valid:
        q, params = "SELECT exp_id FROM experiments WHERE is_valid=1", []
        if args.experiment_type:
            q += " AND experiment_type=?"
            params.append(args.experiment_type)
        exp_ids = [r[0] for r in conn.execute(q, params).fetchall()]
        single_run = None
    elif args.latest:
        q = "SELECT MAX(exp_id) FROM experiments WHERE 1=1"
        params = []
        if args.experiment_type:
            q += " AND experiment_type=?"
            params.append(args.experiment_type)
        row = conn.execute(q, params).fetchone()
        exp_ids = [row[0]] if row and row[0] else []
        single_run = None
    else:
        exp_ids = [args.exp_id]
        single_run = None

    if not exp_ids or exp_ids[0] is None:
        print(json.dumps({"error": "no experiments found"}))
        sys.exit(1)

    # Validate
    output = {
        "validation_timestamp": datetime.now(timezone.utc).isoformat(),
        "db": str(args.db),
        "experiments": [],
    }

    for exp_id in exp_ids:
        exp_row = conn.execute(
            "SELECT experiment_type, workflow_type, runs_completed, is_valid "
            "FROM experiments WHERE exp_id=?", (exp_id,)
        ).fetchone()
        if not exp_row:
            continue

        run_ids_to_validate = (
            [single_run] if single_run else
            [r[0] for r in conn.execute(
                "SELECT run_id FROM runs WHERE exp_id=? ORDER BY run_id",
                (exp_id,)
            ).fetchall()]
        )

        exp_result = {
            "exp_id":          exp_id,
            "experiment_type": exp_row[0],
            "workflow_type":   exp_row[1],
            "runs_completed":  exp_row[2],
            "is_valid":        exp_row[3],
            "runs":            [],
        }

        total = {'ok': 0, 'warn': 0, 'fail': 0, 'n_a': 0, 'data_missing': 0}
        for run_id in run_ids_to_validate:
            run_result = validate_run(conn, run_id)
            exp_result["runs"].append(run_result)
            for k, v in run_result.get('summary', {}).items():
                total[k] = total.get(k, 0) + v

        exp_result["summary"] = total
        output["experiments"].append(exp_result)

    conn.close()

    # Output JSON
    json_str = json.dumps(output, indent=2, default=str)

    if args.json_out:
        with open(args.json_out, 'w') as f:
            f.write(json_str)
        print(f"JSON written to {args.json_out}")
    elif args.json_only:
        print(json_str)
    else:
        # Import and run the report layer
        try:
            from report_energy_chain import render_report
            render_report(output)
        except ImportError:
            # Fall back to JSON if report layer not available
            print(json_str)

    # Exit code: 1 if any failures
    total_fails = sum(
        exp.get('summary', {}).get('fail', 0)
        for exp in output['experiments']
    )
    sys.exit(0 if total_fails == 0 else 1)


if __name__ == "__main__":
    main()
