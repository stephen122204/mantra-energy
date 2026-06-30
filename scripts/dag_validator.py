"""
dag_validator.py — DAG-driven conservation invariant validation.

Validates C1/C2/C3 (ML1-INT/ML0-ML1/ML1-ML2) conservation checks
by walking the platform DAG edges from platform_config.py.

No platform-specific if/else branches. All logic driven by config.

Per spec validator_rewrite_spec_v2.md §3, §8.
"""

import sqlite3
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

from platform_config import get_platform_config
from confidence import composite_score, get_historical_stats


# ---------------------------------------------------------------------------
# Node energy fetchers
# ---------------------------------------------------------------------------

def _get_spbm_domain_uj(conn, run_id, domain_name):
    # type: (sqlite3.Connection, int, str) -> Optional[float]
    """Sum energy_uj for a named SPBM domain from energy_sample_domains."""
    row = conn.execute("""
        SELECT COALESCE(SUM(esd.energy_uj), 0) as total_uj, COUNT(*) as n
        FROM energy_sample_domains esd
        JOIN energy_domains ed ON ed.domain_id = esd.domain_id
        WHERE esd.run_id = ? AND ed.name = ?
    """, (run_id, domain_name)).fetchone()
    if not row or row[1] == 0:
        return None
    return float(row[0])


def _get_rail_uj(conn, run_id, rail_name):
    # type: (sqlite3.Connection, int, str) -> Optional[float]
    """Integrate power_mw x interval_ns for a named power rail."""
    row = conn.execute("""
        SELECT COALESCE(SUM(ps.power_mw * ps.interval_ns / 1000000.0), 0), COUNT(*)
        FROM power_rail_samples ps
        JOIN power_rails pr ON pr.rail_id = ps.rail_id
        WHERE ps.run_id = ? AND pr.rail_name = ?
    """, (run_id, rail_name)).fetchone()
    if not row or row[1] == 0:
        return None
    return float(row[0])


def _get_gpu_dcgm_uj(conn, run_id):
    # type: (sqlite3.Connection, int) -> Optional[float]
    """Sum GPU energy from gpu_samples (DCGM field 156)."""
    row = conn.execute("""
        SELECT COALESCE(SUM(energy_uj), 0), COUNT(*)
        FROM gpu_samples
        WHERE run_id = ? AND energy_uj IS NOT NULL AND energy_uj > 0
    """, (run_id,)).fetchone()
    if not row or row[1] == 0:
        return None
    return float(row[0])


def _get_rapl_domain_uj(conn_run_row, domain):
    # type: (dict, str) -> Optional[float]
    """Get RAPL domain energy from the runs table row."""
    col_map = {
        'pkg':    'pkg_energy_uj',
        'core':   'core_energy_uj',
        'uncore': 'uncore_energy_uj',
        'dram':   'dram_energy_uj',
    }
    col = col_map.get(domain)
    if not col:
        return None
    val = conn_run_row.get(col)
    return float(val) if val else None


def _get_node_sample_count(conn, run_id, node_name, platform):
    # type: (sqlite3.Connection, int, str, str) -> int
    """Get sample count for a node (used in confidence scoring)."""
    if 'spbm' in platform:
        # Map node name to domain/rail
        domain_map = {
            'pkg': 'PACKAGE', 'cpu_p': 'CPU_P', 'cpu_e': 'CPU_E',
            'gpu_spbm': 'GPU', 'dla': None,
        }
        rail_map = {
            'dc_input': 'dc_input', 'dla': 'dla',
            'soc_pkg': 'soc_pkg', 'cpu_gpu': 'cpu_gpu',
            'vcore': 'vcore', 'prereg': 'prereg',
        }
        if node_name in domain_map and domain_map[node_name]:
            row = conn.execute("""
                SELECT COUNT(*) FROM energy_sample_domains esd
                JOIN energy_domains ed ON ed.domain_id = esd.domain_id
                WHERE esd.run_id = ? AND ed.name = ?
            """, (run_id, domain_map[node_name])).fetchone()
            return row[0] if row else 0
        elif node_name in rail_map:
            row = conn.execute("""
                SELECT COUNT(*) FROM power_rail_samples ps
                JOIN power_rails pr ON pr.rail_id = ps.rail_id
                WHERE ps.run_id = ? AND pr.rail_name = ?
            """, (run_id, rail_map[node_name])).fetchone()
            return row[0] if row else 0
        elif node_name == 'gpu_dcgm':
            row = conn.execute(
                "SELECT COUNT(*) FROM gpu_samples WHERE run_id=?",
                (run_id,)
            ).fetchone()
            return row[0] if row else 0
    return 0


# ---------------------------------------------------------------------------
# Node energy resolver
# ---------------------------------------------------------------------------

def resolve_node_energy(conn, run_id, node_name, platform, run_row):
    # type: (sqlite3.Connection, int, str, str, dict) -> Optional[float]
    """
    Resolve energy for a named node on this platform.
    Platform-aware: routes to correct source based on platform string.
    Returns None if node not available on this platform.
    """
    if 'spbm' in platform:
        # SPBM energy accumulators
        domain_names = {
            'pkg':      'PACKAGE',
            'cpu_p':    'CPU_P',
            'cpu_e':    'CPU_E',
            'gpu_spbm': 'GPU',
        }
        # Power rail integrations
        rail_names = {
            'dc_input': 'dc_input',
            'dla':      'dla',
            'soc_pkg':  'soc_pkg',
            'cpu_gpu':  'cpu_gpu',
            'vcore':    'vcore',
            'prereg':   'prereg',
            'sys_total': 'sys_total',
        }
        if node_name in domain_names:
            return _get_spbm_domain_uj(conn, run_id, domain_names[node_name])
        elif node_name in rail_names:
            return _get_rail_uj(conn, run_id, rail_names[node_name])
        elif node_name == 'gpu_dcgm':
            return _get_gpu_dcgm_uj(conn, run_id)

    elif 'rapl' in platform or 'x86' in platform:
        rapl_nodes = ['pkg', 'core', 'uncore', 'dram']
        if node_name in rapl_nodes:
            return _get_rapl_domain_uj(run_row, node_name)
        elif node_name == 'gpu_dcgm':
            return _get_gpu_dcgm_uj(conn, run_id)

    elif 'macos' in platform or 'iokit' in platform:
        if node_name == 'pkg':
            val = run_row.get('pkg_energy_uj')
            return float(val) if val else None
        elif node_name == 'cpu':
            val = run_row.get('core_energy_uj')
            return float(val) if val else None

    return None


# ---------------------------------------------------------------------------
# Main DAG validation function
# ---------------------------------------------------------------------------

def validate_dag(conn, run_id, platform, run_row, workflow_type='agentic'):
    # type: (sqlite3.Connection, int, str, dict, str) -> dict
    """
    Validate all conservation invariants for one run using the platform DAG.

    Walks dag_edges from platform config. For each edge:
      1. Resolve parent and child node energies.
      2. Compute residual (parent - sum(children)).
      3. Check conservation relation (gte or exact).
      4. Compute confidence score.
      5. Emit structured result.

    Also resolves all DAG node energies and diagnostic channel values.

    Args:
        conn:          Open DB connection.
        run_id:        runs.run_id.
        platform:      Platform string from _detect_platform().
        run_row:       dict of runs table row for this run_id.
        workflow_type: 'agentic' or 'linear'.

    Returns:
        dict with 'checks', 'dag_nodes', 'diagnostic_channels', 'derived'.
    """
    config = get_platform_config(platform)
    results = {
        'checks':              {},
        'dag_nodes':           {},
        'diagnostic_channels': {},
        'derived':             {},
    }

    # ── Resolve all node energies ─────────────────────────────────────────
    all_nodes = (
        config.get('conservation_nodes', []) +
        config.get('diagnostic_nodes', [])
    )
    for node_name in all_nodes:
        energy = resolve_node_energy(conn, run_id, node_name, platform, run_row)
        n_samples = _get_node_sample_count(conn, run_id, node_name, platform)
        node_entry = {
            'energy_uj': energy,
            'energy_j':  round(energy / 1e6, 4) if energy is not None else None,
            'n_samples': n_samples,
        }
        if node_name in config.get('conservation_nodes', []):
            results['dag_nodes'][node_name] = node_entry
        else:
            results['diagnostic_channels'][node_name] = node_entry

    # ── Compute derived quantities ────────────────────────────────────────
    for derived_name, (parent_name, child_names, description) in \
            config.get('derived', {}).items():
        parent_uj = (results['dag_nodes'].get(parent_name) or
                     results['diagnostic_channels'].get(parent_name) or {}).get('energy_uj')
        children_sum = 0.0
        all_children_available = True
        for child_name in child_names:
            child_uj = (results['dag_nodes'].get(child_name) or
                        results['diagnostic_channels'].get(child_name) or {}).get('energy_uj')
            if child_uj is None:
                all_children_available = False
                break
            children_sum += child_uj

        if parent_uj is not None and all_children_available:
            value_uj = max(0.0, parent_uj - children_sum)
            results['derived'][derived_name] = {
                'value_uj':    value_uj,
                'value_j':     round(value_uj / 1e6, 4),
                'description': description,
            }
            # Add percentage for residuals
            if parent_uj > 0:
                results['derived'][derived_name]['pct_of_parent'] = round(
                    100.0 * value_uj / parent_uj, 2)
            # Add ratio for cross-source checks
            if len(child_names) == 1:
                child_uj = (results['dag_nodes'].get(child_names[0]) or {}).get('energy_uj')
                if child_uj and child_uj > 0:
                    results['derived'][derived_name]['ratio'] = round(
                        parent_uj / child_uj, 3)
        else:
            results['derived'][derived_name] = {
                'value_uj':    None,
                'value_j':     None,
                'description': description,
                'status':      'DM',
            }

    # ── Walk DAG edges and validate each conservation check ───────────────
    expected_c1 = config.get('expected_c1_residual_pct', {})
    hist_mean = expected_c1.get('mean') if expected_c1 else None
    hist_std  = expected_c1.get('std')  if expected_c1 else None

    for edge in config.get('dag_edges', []):
        check_name = edge['check']
        parent_name = edge['parent']
        child_names = edge['children']
        cross_source = edge.get('cross_source', False)
        relation = edge.get('relation', 'gte')
        description = edge.get('description', '')

        # Resolve parent energy
        parent_uj = results['dag_nodes'].get(parent_name, {}).get('energy_uj')
        if parent_uj is None:
            results['checks'][check_name] = {
                'status': 'DM',
                'reason': f'{parent_name} energy not available',
                'cross_source': cross_source,
                'description': description,
            }
            continue

        # Resolve children energies
        children_uj = {}
        any_missing = False
        for child_name in child_names:
            child_uj = results['dag_nodes'].get(child_name, {}).get('energy_uj')
            if child_uj is None:
                any_missing = True
            children_uj[child_name] = child_uj

        if any_missing:
            results['checks'][check_name] = {
                'status':      'DM',
                'reason':      'one or more child nodes not available',
                'parent_uj':   parent_uj,
                'parent_j':    round(parent_uj / 1e6, 4),
                'children_uj': children_uj,
                'cross_source': cross_source,
                'description': description,
            }
            continue

        children_sum = sum(v for v in children_uj.values() if v is not None)
        residual_uj = parent_uj - children_sum
        residual_pct = 100.0 * residual_uj / parent_uj if parent_uj > 0 else 0.0

        # Determine status
        if relation == 'exact':
            # Exact: delta must be within 1mJ
            delta = abs(residual_uj)
            if delta <= 1000:
                status = 'OK'
            else:
                status = 'FAIL'
        else:
            # GTE: parent must be >= sum(children)
            if residual_uj < -1000:  # 1mJ tolerance
                status = 'FAIL'
            else:
                status = 'OK'

        # Get sample count for confidence scoring
        parent_samples = results['dag_nodes'].get(parent_name, {}).get('n_samples', 0)

        # Compute confidence
        # Use historical stats for calibration score if available from DB
        db_hist_mean, db_hist_std = get_historical_stats(
            conn, platform, workflow_type, check_name)
        actual_hist_mean = db_hist_mean if db_hist_mean is not None else hist_mean
        actual_hist_std  = db_hist_std  if db_hist_std  is not None else hist_std

        conf = composite_score(
            n_samples=parent_samples,
            residual_pct=residual_pct,
            historical_mean=actual_hist_mean,
            historical_std=actual_hist_std,
            check_name=check_name,
            platform_config=config,
        )

        results['checks'][check_name] = {
            'status':        status,
            'parent':        parent_name,
            'parent_uj':     parent_uj,
            'parent_j':      round(parent_uj / 1e6, 4),
            'children':      {k: round(v / 1e6, 4) for k, v in children_uj.items()},
            'children_sum_j': round(children_sum / 1e6, 4),
            'residual_uj':   round(residual_uj, 0),
            'residual_j':    round(residual_uj / 1e6, 4),
            'residual_pct':  round(residual_pct, 2),
            'cross_source':  cross_source,
            'relation':      relation,
            'description':   description,
            'confidence':    conf,
        }

        logger.info(
            "dag_validator: run=%d check=%s status=%s residual=%.1f%% conf=%.2f(%s)",
            run_id, check_name, status, residual_pct,
            conf['score'], conf['level']
        )

    return results
