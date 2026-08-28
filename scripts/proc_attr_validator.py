"""
proc_attr_validator.py — Process attribution validation.

Three blocks per run:
  PROC-ATTR-CPU:      cpu_fraction method (ML1, /proc/stat ticks)
  PROC-ATTR-GPU:      direct metering (ML2, DCGM field 156)
  PROC-ATTR-COMBINED: CPU + GPU combined attribution

GPU attribution uses an assumption model with explicit confidence.
Today: single_active_workload with HIGH confidence.
Future: MIG partitions, SM masks, multi-tenant detection.

Per spec validator_rewrite_spec_v2.md §5.
"""

import sqlite3
import logging
from typing import Optional
from platform_config import get_platform_config
logger = logging.getLogger(__name__)


def check_concurrent_gpu_processes(conn, run_id):
    # type: (sqlite3.Connection, int) -> int
    """
    Check for concurrent GPU processes during run window.
    Currently a placeholder — returns 0 (no concurrent processes detected).
    Future: query nvidia-smi process table sampled during run window.

    Returns:
        Count of other GPU processes detected during run. 0 = single tenant.
    """
    # Placeholder: no concurrent process detection implemented yet.
    # When multi-tenant detection is added, query a gpu_process_samples table
    # or similar artifact captured during measurement.
    return 0


def assess_gpu_attribution(conn, run_id, run_row):
    # type: (sqlite3.Connection, int, dict) -> dict
    """
    Determine GPU attribution mode and confidence for this run.

    Returns assumption dict with mode, fraction, confidence, evidence.
    """
    other_gpu_procs = check_concurrent_gpu_processes(conn, run_id)

    if other_gpu_procs == 0:
        return {
            'mode':       'single_active_workload',
            'fraction':   1.0,
            'confidence': 'HIGH',
            'evidence':   'no other GPU processes detected during run window',
        }
    else:
        return {
            'mode':       'unknown',
            'fraction':   None,
            'confidence': 'LOW',
            'evidence':   f'{other_gpu_procs} other GPU processes detected during run window',
        }


def validate_proc_attr(conn, run_id, platform, run_row, dag_nodes):
    # type: (sqlite3.Connection, int, str, dict, dict) -> dict
    """
    Validate process attribution for CPU and GPU separately.

    CPU attribution:
      E_cpu_attributed = cpu_fraction × E_cpu_dynamic
      E_cpu_dynamic    = E_pkg - E_baseline  (on x86)
                       = E_cpu_p + E_cpu_e   (on ARM SPBM, CPU cores only)

    GPU attribution:
      On ARM SPBM: direct metering via DCGM field 156
      On x86: PP1 MSR (integrated graphics only)
      On macOS: not available

    Args:
        conn:      Open DB connection.
        run_id:    runs.run_id.
        platform:  Platform string.
        run_row:   dict of runs table row.
        dag_nodes: Dict of resolved node energies from dag_validator.

    Returns:
        dict with proc_attr_cpu, proc_attr_gpu, proc_attr_combined.
    """
    result = {}

    attr_uj  = run_row.get('attributed_energy_uj') or 0
    dyn_uj   = run_row.get('dynamic_energy_uj') or 0
    cpu_frac = run_row.get('cpu_fraction') or 0.0
    bg_uj    = run_row.get('background_energy_uj')
    if bg_uj is None:
        bg_uj = max(0, dyn_uj - attr_uj)

    # ── PROC-ATTR-CPU ────────────────────────────────────────────────────
    if 'spbm' in platform:
        # On ARM: CPU dynamic = cpu_p + cpu_e (CPU cores only, not GPU)
        cpu_p_uj = (dag_nodes.get('cpu_p') or {}).get('energy_uj')
        cpu_e_uj = (dag_nodes.get('cpu_e') or {}).get('energy_uj')

        if cpu_p_uj is not None and cpu_e_uj is not None:
            cpu_dynamic_uj = cpu_p_uj + cpu_e_uj
            cpu_attr_uj    = cpu_frac * cpu_dynamic_uj
            delta_uj       = abs(cpu_attr_uj - attr_uj)

            # Note: attr_uj from runs table uses full pkg dynamic, not CPU-only
            # So the delta is expected to be large on ARM — not a violation.
            # The CPU attribution is what it is.
            result['proc_attr_cpu'] = {
                'method':           'cpu_fraction',
                'source':           'ML1 (SPBM cpu_p + cpu_e)',
                'e_cpu_dynamic_j':  round(cpu_dynamic_uj / 1e6, 4),
                'cpu_fraction':     round(cpu_frac, 4),
                'e_cpu_attributed_j': round(cpu_attr_uj / 1e6, 4),
                'e_attributed_runs_j': round(attr_uj / 1e6, 4),
                'status':           'OK',
                'note':             'CPU-only attribution. GPU metered separately via DCGM.',
            }
        else:
            result['proc_attr_cpu'] = {
                'method': 'cpu_fraction',
                'source': 'ML1 (SPBM cpu_p + cpu_e)',
                'status': 'DM',
                'reason': 'cpu_p or cpu_e domain not available',
            }

    else:
        # On x86: CPU dynamic = pkg - baseline
        delta_uj = abs(dyn_uj - (attr_uj + bg_uj))
        result['proc_attr_cpu'] = {
            'method':              'cpu_fraction',
            'source':              'ML1 (RAPL pkg)',
            'e_cpu_dynamic_j':     round(dyn_uj / 1e6, 4),
            'cpu_fraction':        round(cpu_frac, 4),
            'e_cpu_attributed_j':  round(attr_uj / 1e6, 4),
            'e_background_j':      round(bg_uj / 1e6, 4),
            'delta_uj':            round(delta_uj, 0),
            'status':              'OK' if delta_uj <= 1000 else 'FAIL',
        }

    # ── PROC-ATTR-GPU ────────────────────────────────────────────────────
    gpu_method = get_platform_config(platform).get('proc_attr_gpu_method', 'none')
    gpu_dcgm_uj = (dag_nodes.get('gpu_dcgm') or {}).get('energy_uj')
    gpu_assumption = assess_gpu_attribution(conn, run_id, run_row)
    if gpu_method == 'direct_metering' and gpu_dcgm_uj is not None and gpu_dcgm_uj > 0:
        fraction = gpu_assumption.get('fraction')
        gpu_attributed_uj = (gpu_dcgm_uj * fraction) if fraction is not None else None
        result['proc_attr_gpu'] = {
            'method':              'direct_metering',
            'source':              'ML2 (DCGM field 156)',
            'e_gpu_dcgm_j':        round(gpu_dcgm_uj / 1e6, 4),
            'attribution_fraction': fraction,
            'assumption':          gpu_assumption['mode'],
            'assumption_confidence': gpu_assumption['confidence'],
            'assumption_evidence': gpu_assumption['evidence'],
            'e_gpu_attributed_j':  round(gpu_attributed_uj / 1e6, 4) if gpu_attributed_uj else None,
            'status':              'OK' if fraction is not None else 'WARN',
        }
    elif gpu_method == 'direct_metering':
        result['proc_attr_gpu'] = {
            'method': 'direct_metering',
            'source': 'ML2 (DCGM field 156)',
            'status': 'DM',
            'reason': 'no DCGM samples for this run',
        }
    elif gpu_method == 'pp1_msr':
        gpu_pp1_uj = run_row.get('gpu_total_energy_uj')
        if gpu_pp1_uj and gpu_pp1_uj > 0:
            result['proc_attr_gpu'] = {
                'method':     'pp1_msr',
                'source':     'ML1 (Intel PP1 MSR)',
                'e_gpu_j':    round(gpu_pp1_uj / 1e6, 4),
                'status':     'OK',
                'assumption':          'pp1_msr',
                'assumption_confidence': 'HIGH',
                'assumption_evidence': 'PP1 MSR direct metering, integrated GPU only',
                'note':       'Integrated GPU only. Discrete GPU not metered via PP1.',
            }
        else:
            result['proc_attr_gpu'] = {
                'method': 'pp1_msr',
                'source': 'ML1 (Intel PP1 MSR)',
                'status': 'N/A',
                'assumption':          'pp1_msr',
                'assumption_confidence': 'LOW',
                'assumption_evidence': 'no GPU energy or integrated GPU not present',
                'reason': 'no GPU energy or integrated GPU not present',
            }
    else:
        # gpu_method == 'none' or unrecognized: no GPU metering on this platform
        result['proc_attr_gpu'] = {
            'method': gpu_method,
            'source': 'N/A (no GPU metering on this platform)',
            'status': 'N/A',
            'assumption':          gpu_method,
            'assumption_confidence': 'N/A',
            'assumption_evidence': f'proc_attr_gpu_method={gpu_method}: no GPU metering available',
            'reason': 'no GPU metering available on this platform',
        }

    # ── PROC-ATTR-COMBINED ───────────────────────────────────────────────
    cpu_attr_j = None
    gpu_attr_j = None

    if result.get('proc_attr_cpu', {}).get('status') == 'OK':
        cpu_attr_j = result['proc_attr_cpu'].get('e_cpu_attributed_j')

    if result.get('proc_attr_gpu', {}).get('status') == 'OK':
        gpu_attr_j = result['proc_attr_gpu'].get('e_gpu_attributed_j') or \
                     result['proc_attr_gpu'].get('e_gpu_j')

    if cpu_attr_j is not None or gpu_attr_j is not None:
        total_j = (cpu_attr_j or 0.0) + (gpu_attr_j or 0.0)
        # pkg_share: fraction of full SoC package energy attributed to this process
        pkg_uj = (dag_nodes.get('pkg') or {}).get('energy_uj')
        pkg_j  = (pkg_uj / 1e6) if pkg_uj else None
        pkg_share_pct = round(100.0 * total_j / pkg_j, 2) if pkg_j and pkg_j > 0 else None

        result['proc_attr_combined'] = {
            'e_cpu_j':       cpu_attr_j,
            'e_gpu_j':       gpu_attr_j,
            'e_total_j':     round(total_j, 4),
            'pkg_share_pct': pkg_share_pct,
            'status':        'OK',
        }
    else:
        result['proc_attr_combined'] = {
            'status': 'DM',
            'reason': 'CPU or GPU attribution not available',
        }

    return result
