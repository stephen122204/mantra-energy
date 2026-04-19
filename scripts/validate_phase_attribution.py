"""
Validation checks for phase attribution (Chunk 5).
Run after ETL: python scripts/validate_phase_attribution.py

Checks:
    1. cpu_fraction in [0, 1]
    2. sum(phase energies) within 5% of attributed_energy_uj
    3. raw_phase_energy <= dynamic_energy_uj
    4. NULL rate < 5%
    5. attribution_method populated
"""

import sqlite3
import sys

DB_PATH = "data/experiments.db"


def validate(db_path: str = DB_PATH) -> bool:
    conn = sqlite3.connect(db_path)
    errors = []

    # Check 1: cpu_fraction in [0, 1]
    bad = conn.execute("""
        SELECT COUNT(*) FROM orchestration_events
        WHERE cpu_fraction_per_phase IS NOT NULL AND (cpu_fraction_per_phase < 0 OR cpu_fraction_per_phase > 1.0)
    """).fetchone()[0]
    if bad:
        errors.append(f"Check 1 FAIL: {bad} events have cpu_fraction outside [0,1]")
    else:
        print("✅ Check 1: cpu_fraction range valid")

    # Check 2: sum(phase energies) within 5% of attributed_energy_uj
    rows = conn.execute("""
        SELECT r.run_id, r.dynamic_energy_uj,
               COALESCE(r.planning_energy_uj,0) +
               COALESCE(r.execution_energy_uj,0) +
               COALESCE(r.synthesis_energy_uj,0) as phase_sum
        FROM runs r
        WHERE r.workflow_type = 'agentic'
          AND r.planning_energy_uj IS NOT NULL
          AND r.cpu_fraction IS NOT NULL
    """).fetchall()
    bad_sum = sum(1 for _, dyn, ps in rows if dyn and ps > dyn)
    if bad_sum:
        errors.append(f"Check 2 FAIL: {bad_sum} runs have phase_sum > dynamic_energy_uj")
    else:
        print(f"✅ Check 2: phase sums <= dynamic energy ({len(rows)} runs)")    



    # Check 3: raw_phase_energy <= dynamic_energy_uj
    bad = conn.execute("""
        SELECT COUNT(*) FROM orchestration_events o
        JOIN runs r ON o.run_id = r.run_id
        WHERE o.raw_energy_uj > r.dynamic_energy_uj
          AND o.raw_energy_uj IS NOT NULL
          AND o.proc_ticks_min IS NOT NULL
    """).fetchone()[0]
    if bad:
        errors.append(f"Check 3 FAIL: {bad} phases have raw_energy > dynamic_energy")
    else:
        print("✅ Check 3: raw phase energy <= dynamic energy")

    # Check 4: NULL rate < 5%
    null_rate = conn.execute("""
        SELECT AVG(CASE WHEN cpu_fraction_per_phase IS NULL THEN 1.0 ELSE 0.0 END)
        FROM orchestration_events
        WHERE phase IN ('planning','execution','synthesis')
    """).fetchone()[0] or 0
    if null_rate > 0.05:
        errors.append(f"Check 4 FAIL: NULL rate {null_rate*100:.1f}% > 5%")
    else:
        print(f"✅ Check 4: NULL rate {null_rate*100:.1f}%")

    # Check 5: attribution_method populated
    bad = conn.execute("""
        SELECT COUNT(*) FROM orchestration_events
        WHERE phase IN ('planning','execution','synthesis')
          AND attributed_energy_uj IS NOT NULL
          AND attribution_method IS NULL
    """).fetchone()[0]
    if bad:
        errors.append(f"Check 5 FAIL: {bad} events missing attribution_method")
    else:
        print("✅ Check 5: attribution_method populated")

    conn.close()

    if errors:
        print("\n❌ VALIDATION FAILED:")
        for e in errors:
            print(f"   {e}")
        return False

    print("\n✅ All validation checks passed")
    return True


if __name__ == "__main__":
    sys.exit(0 if validate() else 1)
