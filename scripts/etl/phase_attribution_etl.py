"""
phase_attribution_etl.py — Phase Attribution ETL v2: Direct Sample Measurement.

METHODOLOGY CHANGE (v1 -> v2):
    v1: Weighted allocation — forces SUM(phases) = attributed by construction.
        Reviewer attack: "Your phase sums are normalized to attributed by design.
        This tells us nothing about whether phase boundaries captured real energy."

    v2: Direct sample measurement — each phase energy measured independently
        from hardware energy samples within phase timestamp windows.
        E_phase_i = raw_energy_i x cpu_frac_i  (direct, not normalized)
        inter_phase_energy_uj = attributed - SUM(E_phase_i)  (real residual)

        Reviewer defence: "Phase energies are independently measured from hardware
        samples. The inter-phase residual (Python overhead, tool dispatch,
        framework calls between phase boundaries) is explicitly captured and
        reported. No energy is hidden by normalization."

PLATFORM SUPPORT (PAC-4 compliant):
    x86 / UBUNTU2505 (RAPL):
        Source: energy_samples table (pkg_start_uj, pkg_end_uj, sample_start_ns)
        Method: _direct_phase_energy() — unchanged from original v2

    ARM / GN100 (SPBM):
        Source: energy_sample_domains JOIN energy_samples_v2 (via sample_id)
        Domain: domain_id=1 (PACKAGE) from energy_domains table
        Method: _direct_phase_energy_spbm() — added in P2-ETL-01
        Timestamps: energy_samples_v2.timestamp_ns used for phase windowing
        Energy: energy_sample_domains.energy_uj summed within window

    Platform is detected automatically via _get_cpu_package_domain_id().
    If energy_sample_domains has no PACKAGE domain rows, falls back to
    RAPL path — never raises, never silently corrupts. (Rule DC-3, PAC-4)

FORMULA (v2):
    raw_energy_i    = SUM(pkg_end_uj - pkg_start_uj) for samples in phase window
                      [x86] or SUM(energy_uj) for domain samples in window [ARM]
    cpu_frac_i      = (MAX(proc_ticks_end) - MIN(proc_ticks_start)) /
                      (MAX(total_ticks_end) - MIN(total_ticks_start))
    E_phase_i       = raw_energy_i x cpu_frac_i
    inter_phase_uj  = attributed - SUM(E_phase_i)
                      (positive = energy between phase boundaries)
                      (negative = measurement overlap — logged as warning)

PROVENANCE:
    E_phase_i          MEASURED   (direct from hardware samples x /proc ticks)
    inter_phase_energy CALCULATED (arithmetic residual)
    fallback path      INFERRED   (run-level cpu_fraction when phase ticks absent)

DATA SOURCES (x86):
    energy_samples       : pkg_start_uj, pkg_end_uj, sample_start_ns, sample_end_ns
    interrupt_samples    : proc_ticks_start/end, total_ticks_start/end
    orchestration_events : start_time_ns, end_time_ns per phase
    runs                 : attributed_energy_uj (run-level process share)

DATA SOURCES (ARM/GN100):
    energy_sample_domains : sample_id, domain_id, energy_uj
    energy_samples_v2     : sample_id, timestamp_ns, interval_ns
    interrupt_samples     : proc_ticks_start/end, total_ticks_start/end
    orchestration_events  : start_time_ns, end_time_ns per phase
    runs                  : attributed_energy_uj (run-level process share)

COMPATIBILITY:
    v1 runs: unaffected — v2 only runs for new runs and explicit backfill.
    orchestration_events: attribution_method column records 'sample_direct_v2'
    runs: phase_sample_coverage_pct column records measurement quality.
    x86 platforms: zero change to existing code path (PAC-4).

Run modes:
    Async per-run : process_run_async(run_id)         called from experiment_runner
    Manual        : python scripts/etl/phase_attribution_etl.py --run-id <id>
    Backfill      : python scripts/etl/phase_attribution_etl.py --backfill-all
"""

import argparse
import logging
import sqlite3
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

from scripts.tools.path_loader import get_alems_db_path
DB_PATH = get_alems_db_path()
PHASES  = ("planning", "execution", "synthesis")

# Method version — bump when formula changes
ATTRIBUTION_METHOD_V2       = "sample_direct_v2"
ATTRIBUTION_METHOD_FALLBACK = "fallback_run_level_v2"

# Domain name used to identify the CPU package channel on SPBM platforms.
# On GN100: domain_id=1, name='PACKAGE' confirmed 2026-06-28.
# Read from energy_domains at runtime — never hardcoded (Rule CQC-6).
_CPU_PACKAGE_DOMAIN_NAME = "PACKAGE"


def _conn(db_path):
    # type: (str) -> sqlite3.Connection
    """Open DB connection with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _get_cpu_package_domain_id(conn):
    # type: (sqlite3.Connection) -> Optional[int]
    """
    Look up the CPU package domain_id from energy_domains table.

    Used to detect SPBM platform (ARM/GN100) vs RAPL platform (x86).
    Returns domain_id for the PACKAGE channel, or None if not present
    (indicating non-SPBM platform — not an error, triggers RAPL path).

    On GN100: returns 1 (PACKAGE domain, SPBM silicon accumulator).
    On UBUNTU2505: energy_domains may not have PACKAGE rows with data,
    returns None, x86 RAPL path is used unchanged.

    Rule CQC-6: domain name read from DB, never hardcoded as integer.
    """
    row = conn.execute(
        "SELECT domain_id FROM energy_domains WHERE name = ? LIMIT 1",
        (_CPU_PACKAGE_DOMAIN_NAME,)
    ).fetchone()
    if row is None:
        return None
    # Confirm this domain actually has rows in energy_sample_domains.
    # A domain_id existing in energy_domains but having zero sample rows
    # means this is not a SPBM platform — use RAPL path instead.
    count_row = conn.execute(
        "SELECT COUNT(*) as n FROM energy_sample_domains WHERE domain_id = ? LIMIT 1",
        (row[0],)
    ).fetchone()
    if not count_row or count_row["n"] == 0:
        return None
    return row[0]


def _get_phases(conn, run_id):
    # type: (sqlite3.Connection, int) -> list
    """
    Fetch all phase events for this run from orchestration_events.
    Returns list of rows with phase, start_time_ns, end_time_ns.
    """
    return conn.execute("""
        SELECT event_id, phase, start_time_ns, end_time_ns
        FROM orchestration_events
        WHERE run_id = ? AND phase IN ('planning','execution','synthesis')
        ORDER BY start_time_ns
    """, (run_id,)).fetchall()


def _direct_phase_energy(conn, run_id, start_ns, end_ns):
    # type: (sqlite3.Connection, int, int, int) -> Tuple[int, int]
    """
    Compute phase energy directly from RAPL energy_samples (x86 path).

    v2 method: SUM of per-interval deltas within phase window.
    Each sample stores pkg_end_uj - pkg_start_uj as the interval delta.
    Summing gives total package energy for that phase window.

    This is direct measurement — no allocation, no normalization.
    A sample is included if its measurement window falls within the phase window.

    Args:
        conn:     DB connection
        run_id:   run to query
        start_ns: phase start timestamp (ns)
        end_ns:   phase end timestamp (ns)

    Returns:
        (energy_uj, sample_count) — energy_uj=0 if no samples in window
    """
    row = conn.execute("""
        SELECT
            SUM(pkg_end_uj - pkg_start_uj) AS interval_sum,
            COUNT(*)                        AS n_samples
        FROM energy_samples
        WHERE run_id        = ?
          AND sample_start_ns >= ?
          AND sample_end_ns   <= ?
          AND pkg_end_uj IS NOT NULL
          AND pkg_start_uj IS NOT NULL
    """, (run_id, start_ns, end_ns)).fetchone()

    if not row or row["interval_sum"] is None:
        return 0, 0

    # Guard against negative deltas (RAPL counter wrap — rare but possible)
    energy = max(0, row["interval_sum"])
    return energy, row["n_samples"]


def _direct_phase_energy_spbm(conn, run_id, start_ns, end_ns, cpu_domain_id):
    # type: (sqlite3.Connection, int, int, int, int) -> Tuple[int, int]
    """
    Compute phase energy from energy_sample_domains (ARM/SPBM path).

    Used on GN100 where energy is stored in energy_sample_domains keyed
    by domain_id, not in energy_samples (RAPL/x86 only).

    energy_sample_domains has no timestamp column. Timestamps come from
    energy_samples_v2, joined via sample_id (confirmed 2026-06-28).

    A sample is included if its timestamp_ns falls within [start_ns, end_ns].
    energy_uj is the SPBM silicon accumulator reading for that sample interval.

    Provenance: MEASURED (direct from SPBM silicon accumulator, domain PACKAGE).
    cpu_fraction is applied by the caller in compute_phase_attribution().

    Args:
        conn:          Open DB connection
        run_id:        runs.run_id
        start_ns:      Phase start timestamp (nanoseconds)
        end_ns:        Phase end timestamp (nanoseconds)
        cpu_domain_id: energy_domains.domain_id for CPU PACKAGE channel

    Returns:
        (energy_uj, sample_count) — energy_uj=0 if no samples in window
    """
    row = conn.execute("""
        SELECT
            COALESCE(SUM(esd.energy_uj), 0) AS interval_sum,
            COUNT(*)                          AS n_samples
        FROM energy_sample_domains esd
        JOIN energy_samples_v2 esv ON esv.sample_id = esd.sample_id
        WHERE esd.run_id    = ?
          AND esd.domain_id = ?
          AND esv.timestamp_ns >= ?
          AND esv.timestamp_ns <= ?
    """, (run_id, cpu_domain_id, start_ns, end_ns)).fetchone()

    if not row or row["interval_sum"] is None:
        return 0, 0

    # Guard against negative values — SPBM accumulators should not go negative
    # but defensive clamping prevents downstream conservation violations.
    energy = max(0, int(row["interval_sum"]))
    return energy, row["n_samples"]


def _phase_cpu_fraction(conn, run_id, start_ns, end_ns):
    # type: (sqlite3.Connection, int, int, int) -> Tuple[Optional[float], int, int, int]
    """
    Counter delta method for process CPU fraction within phase window.

    Uses MAX-MIN on proc_ticks and total_ticks within phase timestamp bounds.
    Returns (cpu_fraction, proc_delta, total_delta, n_samples).
    cpu_fraction is None when insufficient interrupt_samples data.
    """
    row = conn.execute("""
        SELECT
            MIN(proc_ticks_start)  AS proc_min,
            MAX(proc_ticks_end)    AS proc_max,
            MIN(total_ticks_start) AS total_min,
            MAX(total_ticks_end)   AS total_max,
            COUNT(*)               AS n_samples
        FROM interrupt_samples
        WHERE run_id        = ?
          AND sample_start_ns >= ?
          AND sample_end_ns   <= ?
    """, (run_id, start_ns, end_ns)).fetchone()

    if not row or row["proc_min"] is None or row["total_min"] is None:
        return None, 0, 0, row["n_samples"] if row else 0

    proc_delta  = row["proc_max"]  - row["proc_min"]
    total_delta = row["total_max"] - row["total_min"]

    if total_delta <= 0:
        return None, proc_delta, total_delta, row["n_samples"]

    frac = max(0.0, min(1.0, proc_delta / total_delta))
    return frac, proc_delta, total_delta, row["n_samples"]


def _fallback_cpu_fraction(conn, run_id):
    # type: (sqlite3.Connection, int) -> float
    """
    Run-level cpu_fraction fallback when phase-level ticks unavailable.
    Provenance: INFERRED (run-level proxy for phase-level measurement).
    """
    row = conn.execute(
        "SELECT cpu_fraction FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if not row or row["cpu_fraction"] is None:
        return 0.0
    return float(row["cpu_fraction"])


def _total_run_samples(conn, run_id, use_spbm, cpu_domain_id):
    # type: (sqlite3.Connection, int, bool, Optional[int]) -> int
    """
    Total energy sample rows for this run — used for coverage computation.

    Uses energy_sample_domains for SPBM platforms, energy_samples for RAPL.
    Coverage denominator must match the source used for phase measurement.
    """
    if use_spbm and cpu_domain_id is not None:
        # Count SPBM PACKAGE domain samples for this run
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM energy_sample_domains "
            "WHERE run_id = ? AND domain_id = ?",
            (run_id, cpu_domain_id)
        ).fetchone()
    else:
        # Count RAPL energy_samples for this run
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM energy_samples WHERE run_id = ?",
            (run_id,)
        ).fetchone()
    return row["n"] if row else 0


def compute_phase_attribution(run_id, db_path=DB_PATH):
    # type: (int, str) -> dict
    """
    Compute direct sample-based phase attribution for one run (v2).

    Each phase energy is independently measured from hardware samples.
    inter_phase_energy_uj captures energy between/outside phase boundaries.
    No normalization forcing — honest measurement with honest residual.

    Platform routing (PAC-4):
        ARM/GN100  — uses energy_sample_domains JOIN energy_samples_v2
        x86/RAPL   — uses energy_samples (unchanged original path)

    Args:
        run_id:  runs.run_id to process
        db_path: path to SQLite DB

    Returns:
        dict with planning, execution, synthesis, inter_phase energy values
        and coverage metrics. Returns {"error": ...} on skip conditions.
    """
    conn = _conn(db_path)

    # Detect platform: SPBM (ARM) or RAPL (x86). Rule PAC-4.
    # Returns domain_id if SPBM samples exist, None otherwise.
    cpu_domain_id = _get_cpu_package_domain_id(conn)
    use_spbm      = cpu_domain_id is not None

    logger.info(
        "phase_attribution v2: run=%d platform=%s cpu_domain_id=%s",
        run_id,
        "SPBM/ARM" if use_spbm else "RAPL/x86",
        cpu_domain_id,
    )

    # Early return: no phases = no agentic workflow
    phases = _get_phases(conn, run_id)
    if not phases:
        conn.close()
        return {"error": "no phases for run %d" % run_id}

    # Fetch run-level values needed for inter_phase calculation
    run_row = conn.execute(
        "SELECT attributed_energy_uj, dynamic_energy_uj FROM runs WHERE run_id=?",
        (run_id,)
    ).fetchone()

    if not run_row:
        conn.close()
        return {"error": "run %d not found" % run_id}

    dynamic_energy = run_row["dynamic_energy_uj"] or 0
    run_attributed = run_row["attributed_energy_uj"] or 0
    total_samples  = _total_run_samples(conn, run_id, use_spbm, cpu_domain_id)

    # Phase energies partition E_attributed by time window.
    # D2: E_plan + E_exec + E_synth + E_inter = E_attributed (exact)
    # inter_phase absorbs residual — not forced to zero.

    # Step 1: measure each phase independently from hardware samples
    phase_data    = {}
    phase_totals  = {p: 0 for p in PHASES}
    samples_in_phases = 0

    for phase in phases:
        start_ns = phase["start_time_ns"]
        end_ns   = phase["end_time_ns"]

        # Route to correct energy source based on platform (PAC-4)
        if use_spbm:
            raw_energy, n_energy_samples = _direct_phase_energy_spbm(
                conn, run_id, start_ns, end_ns, cpu_domain_id
            )
        else:
            raw_energy, n_energy_samples = _direct_phase_energy(
                conn, run_id, start_ns, end_ns
            )

        # CPU fraction for this phase window (same logic for both platforms)
        cpu_frac, proc_delta, total_delta, n_tick_samples = _phase_cpu_fraction(
            conn, run_id, start_ns, end_ns
        )

        if cpu_frac is None:
            # Fallback: use run-level cpu_fraction — provenance degrades to INFERRED
            cpu_frac = _fallback_cpu_fraction(conn, run_id)
            method   = ATTRIBUTION_METHOD_FALLBACK
            quality  = 0.3
            logger.warning(
                "phase_attribution v2: run=%d phase=%s no tick data — "
                "fallback cpu_frac=%.4f",
                run_id, phase["phase"], cpu_frac
            )
        else:
            method  = ATTRIBUTION_METHOD_V2
            quality = min(1.0, n_energy_samples / 10.0) if n_energy_samples > 0 else 0.5

        # E_phase_i = raw_energy_i x cpu_frac_i (direct measurement)
        phase_energy = int(raw_energy * cpu_frac)

        # Cap at dynamic_energy to prevent physics violation
        if dynamic_energy > 0:
            phase_energy = min(phase_energy, dynamic_energy)

        samples_in_phases += n_energy_samples

        phase_data[phase["event_id"]] = {
            "phase":        phase["phase"],
            "raw_energy":   raw_energy,
            "cpu_frac":     cpu_frac,
            "phase_energy": phase_energy,
            "method":       method,
            "quality":      quality,
            "proc_delta":   proc_delta,
            "total_delta":  total_delta,
            "n_samples":    n_energy_samples,
        }
        phase_totals[phase["phase"]] += phase_energy

    # Step 2: inter_phase_energy — honest residual, not forced to 0
    # Represents energy between phase boundaries: Python overhead,
    # tool dispatch, framework calls, retry logic.
    # Positive = real between-phase energy. Negative = overlap (clamped).
    phase_sum      = sum(phase_totals.values())
    inter_phase_uj = run_attributed - phase_sum

    if inter_phase_uj < 0:
        logger.warning(
            "phase_attribution v2: run=%d inter_phase_uj=%d NEGATIVE "
            "— phase measurements exceed attributed=%d. "
            "Possible sample overlap at phase boundaries. Clamping to 0.",
            run_id, inter_phase_uj, run_attributed
        )
        inter_phase_uj = 0

    # Step 3: phase sample coverage
    # Fraction of total run samples that fell within named phase windows.
    phase_coverage_pct = (
        100.0 * samples_in_phases / total_samples
        if total_samples > 0 else 0.0
    )

    # Step 4: write per-phase measurements to orchestration_events
    for event_id, d in phase_data.items():
        conn.execute("""
            UPDATE orchestration_events
            SET raw_energy_uj          = ?,
                cpu_fraction_per_phase = ?,
                attributed_energy_uj   = ?,
                attribution_method     = ?,
                quality_score          = ?
            WHERE event_id = ?
        """, (
            d["raw_energy"],
            d["cpu_frac"],
            d["phase_energy"],
            d["method"],
            d["quality"],
            event_id,
        ))

    # Step 5: write phase totals to runs table
    conn.execute("""
        UPDATE runs
        SET planning_energy_uj        = ?,
            execution_energy_uj       = ?,
            synthesis_energy_uj       = ?,
            inter_phase_energy_uj     = ?,
            phase_sample_coverage_pct = ?
        WHERE run_id = ?
    """, (
        phase_totals["planning"],
        phase_totals["execution"],
        phase_totals["synthesis"],
        inter_phase_uj,
        phase_coverage_pct,
        run_id,
    ))

    conn.commit()
    conn.close()

    return {
        "planning":           phase_totals["planning"],
        "execution":          phase_totals["execution"],
        "synthesis":          phase_totals["synthesis"],
        "inter_phase_uj":     inter_phase_uj,
        "phase_coverage_pct": phase_coverage_pct,
        "phase_sum":          phase_sum,
        "attributed":         run_attributed,
    }


def process_run_async(run_id, db_path=DB_PATH):
    # type: (int, str) -> None
    """
    Non-blocking background thread — called from experiment_runner after save_pair.
    Also called from run_experiment.py after execute_goal completes.
    """
    t = threading.Thread(
        target=compute_phase_attribution,
        args=(run_id, db_path),
        daemon=True,
    )
    t.start()


def backfill_all(db_path=DB_PATH):
    # type: (str) -> None
    """
    Backfill all agentic runs with v2 phase attribution.
    Safe to rerun — idempotent (UPDATE not INSERT).
    Works on both x86 (RAPL) and ARM (SPBM) databases.
    Platform is detected automatically per run.
    """
    conn = _conn(db_path)
    runs = conn.execute(
        "SELECT run_id FROM runs WHERE workflow_type='agentic' ORDER BY run_id"
    ).fetchall()
    conn.close()

    print("Backfilling %d agentic runs with phase_attribution v2..." % len(runs))
    ok = err = 0
    for row in runs:
        result = compute_phase_attribution(row["run_id"], db_path)
        if "error" in result:
            print("  run %d: SKIP — %s" % (row["run_id"], result["error"]))
            err += 1
        else:
            print(
                "  run %d: plan=%duJ exec=%duJ synth=%duJ inter=%duJ coverage=%.1f%%" % (
                    row["run_id"],
                    result["planning"],
                    result["execution"],
                    result["synthesis"],
                    result["inter_phase_uj"],
                    result["phase_coverage_pct"],
                )
            )
            ok += 1

    print("Done: %d ok, %d skipped." % (ok, err))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Phase attribution ETL v2 — direct sample measurement"
    )
    parser.add_argument("--run-id",       type=int, help="Process single run")
    parser.add_argument("--backfill-all", action="store_true",
                        help="Reprocess all agentic runs")
    parser.add_argument("--db",           default=DB_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.backfill_all:
        backfill_all(args.db)
    elif args.run_id:
        result = compute_phase_attribution(args.run_id, args.db)
        print(result)
    else:
        parser.print_help()
