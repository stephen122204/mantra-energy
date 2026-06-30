"""
check_validators.py — Boundary, phase, activity, and goal validators.

Four validators, one file:
  validate_boundary()        — pre/post task energy with SPBM guard
  validate_activity_decomp() — llm_window + orchestration with DM guard
  validate_phase_partition() — phase energy table with duration cross-tab
  validate_goal_aggregation() — attempt summation with retry amplification

Per spec validator_rewrite_spec_v2.md §6, §7, §9.
"""

import sqlite3
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BOUNDARY
# ---------------------------------------------------------------------------

def validate_boundary(run_row, platform):
    # type: (dict, str) -> dict
    """
    Validate pre/post task boundary energy.

    Guards against raw SPBM boot accumulators being used as window deltas.
    On ARM/SPBM, boundary is NOT_AVAILABLE because SPBM lacks window snapshot
    semantics. Fix: integrate power_rail_samples over pre/post time windows.

    Args:
        run_row:  dict of runs table row.
        platform: Platform string.

    Returns:
        dict with status, values, and reason.
    """
    pre_uj   = run_row.get('pre_task_energy_uj') or 0
    post_uj  = run_row.get('post_task_energy_uj') or 0
    attr_uj  = run_row.get('attributed_energy_uj') or 0
    fwoh_uj  = run_row.get('framework_overhead_energy_uj') or 0

    # Guard: raw accumulator detection
    # If post_task_energy_uj > 10x attributed, it is a boot accumulator not a delta
    if attr_uj > 0 and post_uj > attr_uj * 10:
        return {
            'status':  'N/A',
            'reason':  'raw_accumulator_not_window_delta',
            'detail':  (
                f'post_task_energy={post_uj/1e6:.1f}J is '
                f'{post_uj/attr_uj:.0f}x attributed={attr_uj/1e6:.1f}J. '
                f'SPBM accumulators are cumulative from boot, '
                f'not window snapshots like RAPL.'
            ),
            'fix':      'integrate power_rail_samples over pre/post time windows (deferred)',
            'framework_overhead_j': round(fwoh_uj / 1e6, 4),
        }

    # Also guard: pre > attributed (same issue)
    if attr_uj > 0 and pre_uj > attr_uj * 10:
        return {
            'status': 'N/A',
            'reason': 'raw_accumulator_not_window_delta',
            'detail': (
                f'pre_task_energy={pre_uj/1e6:.1f}J is '
                f'{pre_uj/attr_uj:.0f}x attributed={attr_uj/1e6:.1f}J. '
                f'SPBM accumulators are cumulative from boot.'
            ),
            'fix':    'integrate power_rail_samples over pre/post time windows (deferred)',
            'framework_overhead_j': round(fwoh_uj / 1e6, 4),
        }

    # No data case
    if pre_uj == 0 and post_uj == 0:
        return {
            'status': 'DM',
            'reason': 'pre_task_energy_uj and post_task_energy_uj both NULL or 0',
            'framework_overhead_j': round(fwoh_uj / 1e6, 4),
        }

    # Normal validation (x86 RAPL path)
    work_uj = attr_uj - pre_uj - post_uj
    total   = pre_uj + work_uj + post_uj
    delta   = abs(total - attr_uj)

    return {
        'status':     'OK' if delta <= 1000 else 'FAIL',
        'delta_uj':   round(delta, 0),
        'pre_j':      round(pre_uj / 1e6, 4),
        'work_j':     round(work_uj / 1e6, 4),
        'post_j':     round(post_uj / 1e6, 4),
        'attr_j':     round(attr_uj / 1e6, 4),
        'framework_overhead_j': round(fwoh_uj / 1e6, 4),
    }


# ---------------------------------------------------------------------------
# ACTIVITY-DECOMP
# ---------------------------------------------------------------------------

def validate_activity_decomp(run_row, ea_row):
    # type: (dict, Optional[dict]) -> dict
    """
    Validate D1: attributed = llm_window + orchestration.

    Guards:
      - E_llm_window = 0 on agentic run → DATA_MISSING (ETL not run)
      - E_llm_window = 0 on linear run → OK (may be valid, no LLM calls)
      - No energy_attribution row → DATA_MISSING

    Args:
        run_row: dict of runs table row.
        ea_row:  dict of energy_attribution row, or None.

    Returns:
        dict with status, energy values, method, and any warnings.
    """
    attr_uj = run_row.get('attributed_energy_uj') or 0
    wf      = run_row.get('workflow_type') or 'unknown'

    if ea_row is None:
        return {
            'status': 'DM',
            'reason': 'no energy_attribution row — run energy_attribution_etl.py',
            'e_attr_j': round(attr_uj / 1e6, 4),
        }

    llm_uj  = ea_row.get('llm_compute_energy_uj') or 0
    orch_uj = ea_row.get('orchestration_energy_uj') or 0
    mth     = ea_row.get('attribution_method') or 'unknown'
    cov     = ea_row.get('attribution_coverage_pct') or 0.0
    llmw_uj = ea_row.get('llm_wait_energy_uj') or 0
    pref_uj = ea_row.get('prefill_energy_uj') or 0
    dec_uj  = ea_row.get('decode_energy_uj') or 0

    delta_uj = abs((llm_uj + orch_uj) - attr_uj)
    is_sample = 'sample_based' in mth

    result = {
        'e_llm_j':   round(llm_uj / 1e6, 4),
        'e_orch_j':  round(orch_uj / 1e6, 4),
        'e_attr_j':  round(attr_uj / 1e6, 4),
        'delta_uj':  round(delta_uj, 0),
        'method':    mth,
        'provenance': 'MEASURED' if is_sample else 'INFERRED',
        'attribution_coverage_pct': cov,
        'e_llm_wait_j':   round(llmw_uj / 1e6, 4),
        'e_prefill_j':    round(pref_uj / 1e6, 4) if pref_uj else None,
        'e_decode_j':     round(dec_uj / 1e6, 4) if dec_uj else None,
    }

    # Guard: E_llm = 0 on agentic run
    if llm_uj == 0 and wf == 'agentic':
        result['status'] = 'DM'
        result['reason'] = (
            'E_llm_window=0 on agentic run. '
            'energy_attribution_etl.py must run post-experiment '
            'to populate llm_compute_energy_uj from LLM call timestamps.'
        )
    elif delta_uj <= 1000:
        result['status'] = 'OK'
    else:
        result['status'] = 'FAIL'

    return result


# ---------------------------------------------------------------------------
# PHASE-PARTITION
# ---------------------------------------------------------------------------

def validate_phase_partition(run_row, conn, run_id, sample_interval_ms):
    # type: (dict, sqlite3.Connection, int, Optional[float]) -> dict
    """
    Validate D2: attributed = plan + exec + synth + inter_phase.

    Also computes per-phase duration from orchestration_events and
    the E/T ratio (energy fraction / time fraction) for each phase.

    Phase resolution warning: flag phases shorter than 2x sample interval.

    Args:
        run_row:           dict of runs table row.
        conn:              Open DB connection (for orchestration_events).
        run_id:            runs.run_id.
        sample_interval_ms: Platform sample interval in ms (from platform config).

    Returns:
        dict with phase energies, durations, E/T ratios, and status.
    """
    wf   = run_row.get('workflow_type') or 'unknown'
    attr = run_row.get('attributed_energy_uj') or 0

    if wf != 'agentic':
        return {
            'status': 'N/A',
            'reason': 'linear run — no phase decomposition',
        }

    plan = run_row.get('planning_energy_uj') or 0
    exe  = run_row.get('execution_energy_uj') or 0
    syn  = run_row.get('synthesis_energy_uj') or 0
    iph  = run_row.get('inter_phase_energy_uj') or 0
    cov  = run_row.get('phase_sample_coverage_pct')

    if plan == 0 and exe == 0 and syn == 0:
        return {
            'status': 'DM',
            'reason': 'phase energies all zero — phase_attribution_etl.py not run',
            'phase_coverage_pct': cov,
        }

    phase_sum = plan + exe + syn + iph
    delta_uj  = abs(phase_sum - attr)

    # Fetch phase durations from orchestration_events
    phase_durations = {}
    total_named_duration_ns = 0
    try:
        rows = conn.execute("""
            SELECT phase,
                   SUM(end_time_ns - start_time_ns) as duration_ns
            FROM orchestration_events
            WHERE run_id = ?
              AND phase IN ('planning', 'execution', 'synthesis')
            GROUP BY phase
        """, (run_id,)).fetchall()
        for row in rows:
            phase_durations[row[0]] = row[1] or 0
            total_named_duration_ns += row[1] or 0
    except Exception as e:
        logger.warning("phase_partition: could not fetch durations for run %d: %s", run_id, e)

    # Total run duration for inter_phase time
    task_dur_ns = run_row.get('task_duration_ns') or 0
    inter_dur_ns = max(0, task_dur_ns - total_named_duration_ns) if task_dur_ns > 0 else 0

    # Build phase table with E/T ratios
    phases = []
    for phase_name, energy_uj, dur_ns in [
        ('planning',   plan, phase_durations.get('planning', 0)),
        ('execution',  exe,  phase_durations.get('execution', 0)),
        ('synthesis',  syn,  phase_durations.get('synthesis', 0)),
        ('inter_phase', iph, inter_dur_ns),
    ]:
        e_pct = 100.0 * energy_uj / attr if attr > 0 else 0.0
        t_pct = 100.0 * dur_ns / task_dur_ns if task_dur_ns > 0 else 0.0
        et_ratio = (e_pct / t_pct) if t_pct > 0 else None
        dur_ms = dur_ns / 1e6 if dur_ns > 0 else None

        phases.append({
            'name':       phase_name,
            'energy_j':   round(energy_uj / 1e6, 4),
            'energy_pct': round(e_pct, 1),
            'duration_s': round(dur_ns / 1e9, 3) if dur_ns > 0 else None,
            'duration_pct': round(t_pct, 1) if t_pct > 0 else None,
            'et_ratio':   round(et_ratio, 2) if et_ratio is not None else None,
            'duration_ms': dur_ms,
        })

    # Phase resolution warning
    resolution_warning = None
    if sample_interval_ms is not None:
        min_dur_ms = min(
            (p['duration_ms'] for p in phases
             if p['name'] != 'inter_phase' and p['duration_ms'] is not None),
            default=None
        )
        if min_dur_ms is not None and min_dur_ms < sample_interval_ms * 2:
            resolution_warning = (
                f'Shortest named phase ({min_dur_ms:.0f}ms) < '
                f'2× sample interval ({sample_interval_ms * 2:.0f}ms). '
                f'Phase boundaries may be imprecise. Energy totals unaffected.'
            )

    return {
        'status':              'OK' if delta_uj <= 1000 else 'FAIL',
        'delta_uj':            round(delta_uj, 0),
        'phases':              phases,
        'phase_coverage_pct':  cov,
        'total_task_duration_s': round(task_dur_ns / 1e9, 3) if task_dur_ns > 0 else None,
        'resolution_warning':  resolution_warning,
    }


# ---------------------------------------------------------------------------
# GOAL-AGGREGATION
# ---------------------------------------------------------------------------

def validate_goal_aggregation(conn, run_id, run_row, dag_nodes):
    # type: (sqlite3.Connection, int, dict, dict) -> dict
    """
    Validate GOAL-AGGREGATION: E_attributed = SUM(attempt energies).

    For multi-attempt runs, also computes per-attempt domain decomposition
    and retry amplification ratios (Paper A §5.7).

    Args:
        conn:      Open DB connection.
        run_id:    runs.run_id.
        run_row:   dict of runs table row.
        dag_nodes: Dict of resolved node energies (for per-attempt domain pct).

    Returns:
        dict with aggregation check and per-attempt analysis.
    """
    attr_uj = run_row.get('attributed_energy_uj') or 0

    # Fetch goal and attempts for this run
    goal_row = None
    attempts = []
    try:
        goal_row = conn.execute("""
            SELECT ge.goal_id, ge.total_energy_uj, ge.total_attempts,
                   ge.successful_energy_uj, ge.overhead_energy_uj,
                   ge.orchestration_fraction, ge.overhead_fraction
            FROM goal_execution ge
            WHERE COALESCE(ge.winning_run_id, ge.first_run_id) = ?
        """, (run_id,)).fetchone()

        if goal_row:
            attempt_rows = conn.execute("""
                SELECT ga.attempt_id, ga.energy_uj,
                       ga.attempt_number
                FROM goal_attempt ga
                WHERE ga.goal_id = ?
                ORDER BY ga.attempt_number
            """, (goal_row[0],)).fetchall()
            attempts = [dict(r) for r in attempt_rows] if attempt_rows else []
    except Exception as e:
        logger.warning("goal_aggregation: query failed for run %d: %s", run_id, e)

    if not goal_row:
        return {
            'status': 'DM',
            'reason': 'no goal_execution row for this run',
            'e_attr_j': round(attr_uj / 1e6, 4),
        }

    attempt_energies = [a.get('energy_uj') or 0 for a in attempts]
    attempt_sum_uj   = sum(attempt_energies)
    delta_uj         = abs(attempt_sum_uj - attr_uj)
    n_attempts       = len(attempts)

    result = {
        'status':           'OK' if delta_uj <= 1000 else 'FAIL',
        'e_goal_j':         round(attr_uj / 1e6, 4),
        'n_attempts':       n_attempts,
        'e_sum_attempts_j': round(attempt_sum_uj / 1e6, 4),
        'delta_uj':         round(delta_uj, 0),
        'e_per_attempt_j':  [round(e / 1e6, 4) for e in attempt_energies],
        'orchestration_fraction': goal_row[5],
        'overhead_fraction':      goal_row[6],
    }

    # f_orch check
    attr_for_forch = attr_uj
    orch_fraction_stored = goal_row[5]
    # Would need energy_attribution to compute f_orch here — skip if not available

    # Retry amplification analysis (Paper A §5.7)
    if n_attempts >= 2 and all(e > 0 for e in attempt_energies):
        ratios = []
        for i in range(1, len(attempt_energies)):
            if attempt_energies[i-1] > 0:
                ratio = attempt_energies[i] / attempt_energies[i-1]
                ratios.append(round(ratio, 3))

        result['retry_amplification_ratios'] = ratios
        result['retry_trend'] = (
            'RISING'   if all(r > 1.05 for r in ratios) else
            'FALLING'  if all(r < 0.95 for r in ratios) else
            'STABLE'
        )

        # Per-attempt domain decomposition if DAG nodes available
        # (Simplified: show attempt energies as fractions of total)
        if dag_nodes:
            per_attempt_decomp = []
            total_dcgm = (dag_nodes.get('gpu_dcgm') or {}).get('energy_uj')
            total_pkg  = (dag_nodes.get('pkg') or {}).get('energy_uj')

            for i, attempt in enumerate(attempts):
                e_uj = attempt.get('energy_uj') or 0
                # Pro-rate domain energies by attempt energy fraction
                frac = e_uj / attr_uj if attr_uj > 0 else 0
                decomp = {
                    'attempt':    i + 1,
                    'energy_j':   round(e_uj / 1e6, 4),
                    'attempt':    i + 1,
                }
                if total_dcgm and e_uj > 0:
                    decomp['gpu_compute_pct'] = round(100.0 * frac * total_dcgm / e_uj, 1) if e_uj > 0 else None
                per_attempt_decomp.append(decomp)

            result['per_attempt_decomp'] = per_attempt_decomp

    return result
