#!/bin/bash
# =============================================================================
# scripts/test_provenance.sh
# =============================================================================
# Regression test for Chunk 9 provenance integrity.
# Run after any code change that touches energy measurement, harness,
# or experiment_runner.
#
# Usage:
#   bash scripts/test_provenance.sh
#   bash scripts/test_provenance.sh --run-id 1833
# =============================================================================

set -euo pipefail

DB="${DB:-data/experiments.db}"
PASS=0
FAIL=0

# ── Get run_id ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--run-id" ]]; then
    RUN_ID="$2"
else
    RUN_ID=$(sqlite3 "$DB" "SELECT MAX(run_id) FROM measurement_methodology;")
fi

echo "============================================================"
echo "A-LEMS Provenance Regression Test"
echo "DB:     $DB"
echo "Run ID: $RUN_ID"
echo "============================================================"
echo ""

# ── Helper ────────────────────────────────────────────────────────────────────
check() {
    local name="$1"
    local actual="$2"
    local expected_op="$3"
    local expected_val="$4"
    local result

    case "$expected_op" in
        "eq")  [ "$actual" -eq "$expected_val" ] && result="PASS" || result="FAIL" ;;
        "gt")  [ "$actual" -gt "$expected_val" ] && result="PASS" || result="FAIL" ;;
        "ge")  [ "$actual" -ge "$expected_val" ] && result="PASS" || result="FAIL" ;;
        "lt")  [ "$actual" -lt "$expected_val" ] && result="PASS" || result="FAIL" ;;
    esac

    if [ "$result" == "PASS" ]; then
        echo "✅ PASS  $name: $actual"
        PASS=$((PASS + 1))
    else
        echo "❌ FAIL  $name: $actual (expected $expected_op $expected_val)"
        FAIL=$((FAIL + 1))
    fi
}

# ── T1: Row count per run ─────────────────────────────────────────────────────
echo "--- measurement_methodology ---"
COUNT=$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM measurement_methodology
    WHERE run_id = $RUN_ID;")
check "Row count (expect >60)" "$COUNT" "gt" 60

# ── T2: No NULL method_ids ────────────────────────────────────────────────────
NULL_METHODS=$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM measurement_methodology
    WHERE run_id = $RUN_ID
      AND method_id IS NULL;")
check "NULL method_ids (expect 0)" "$NULL_METHODS" "eq" 0

# ── T3: Key PhD metrics present ───────────────────────────────────────────────
echo ""
echo "--- Key metrics ---"
for metric in pkg_energy_uj core_energy_uj ipc carbon_g api_latency_ms \
              bytes_sent bytes_recv cache_miss_rate thermal_delta_c \
              complexity_score orchestration_cpu_ms; do
    EXISTS=$(sqlite3 "$DB" "
        SELECT COUNT(*)
        FROM measurement_methodology
        WHERE run_id = $RUN_ID
          AND metric_id = '$metric';")
    check "$metric present" "$EXISTS" "gt" 0
done

# ── T4: JOIN works — formula available ───────────────────────────────────────
echo ""
echo "--- Formula coverage ---"
NO_FORMULA=$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM measurement_methodology mm
    JOIN measurement_method_registry mmr ON mm.method_id = mmr.id
    WHERE mm.run_id = $RUN_ID
      AND (mmr.formula_latex IS NULL OR mmr.formula_latex = '');")
check "Rows without formula (expect 0)" "$NO_FORMULA" "eq" 0

# ── T5: INFERRED metrics have confidence < 1.0 ───────────────────────────────
echo ""
echo "--- Confidence levels ---"
INFERRED_HIGH=$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM measurement_methodology
    WHERE run_id     = $RUN_ID
      AND provenance = 'INFERRED'
      AND confidence >= 1.0;")
check "INFERRED at confidence=1.0 (expect 0)" "$INFERRED_HIGH" "eq" 0

# carbon and water should be at 0.7
CARBON_CONF=$(sqlite3 "$DB" "
    SELECT CAST(confidence * 10 AS INTEGER)
    FROM measurement_methodology
    WHERE run_id = $RUN_ID AND metric_id = 'carbon_g';")
check "carbon_g confidence=0.7 (×10=7)" "$CARBON_CONF" "eq" 7

# ── T6: Method registry completeness ─────────────────────────────────────────
echo ""
echo "--- Method registry ---"
METHOD_COUNT=$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM measurement_method_registry;")
check "Method registry rows (expect ≥22)" "$METHOD_COUNT" "ge" 22

# All methods have descriptions
NO_DESC=$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM measurement_method_registry
    WHERE description IS NULL OR LENGTH(description) < 50;")
check "Methods missing description (expect 0)" "$NO_DESC" "eq" 0

# All methods have formulas
NO_FORM=$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM measurement_method_registry
    WHERE formula_latex IS NULL OR formula_latex = '';")
check "Methods missing formula (expect 0)" "$NO_FORM" "eq" 0

# ── T7: References present ────────────────────────────────────────────────────
echo ""
echo "--- References ---"
REF_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM method_references;")
check "Reference rows (expect >4)" "$REF_COUNT" "gt" 4

# RAPL has Intel SDM reference
RAPL_REFS=$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM method_references
    WHERE method_id = 'rapl_msr_pkg_energy';")
check "RAPL references (expect ≥2)" "$RAPL_REFS" "ge" 2

# ── T8: metric_display_registry method_id links ───────────────────────────────
echo ""
echo "--- Display registry ---"
MDR_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM metric_display_registry;")
check "Display registry rows (expect ≥90)" "$MDR_COUNT" "ge" 90
# ── T9: Chunk 6 — Energy Attribution ─────────────────────────────────────────
echo ""
echo "--- Energy Attribution (Chunk 6) ---"
 
ATTR_TABLE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='energy_attribution';")
check "energy_attribution table exists (expect 1)" "$ATTR_TABLE" "eq" 1
 
ATTR_ROWS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM energy_attribution;" 2>/dev/null || echo "0")
check "energy_attribution rows (expect >0)" "$ATTR_ROWS" "gt" 0
 
ATTR_COVERAGE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM energy_attribution WHERE attribution_coverage_pct IS NOT NULL;" 2>/dev/null || echo "0")
check "attribution_coverage_pct populated (expect >0)" "$ATTR_COVERAGE" "gt" 0
 
NORM_TABLE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='normalization_factors';")
check "normalization_factors table exists (expect 1)" "$NORM_TABLE" "eq" 1
 
V_NORM=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name='v_energy_normalized';")
check "v_energy_normalized view exists (expect 1)" "$V_NORM" "eq" 1
 
V_ATTR=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name='v_attribution_summary';")
check "v_attribution_summary view exists (expect 1)" "$V_ATTR" "eq" 1
# ── T10: v9 Duration Fix ──────────────────────────────────────────────────────
echo ""
echo "--- Duration Fix (v9) ---"
 
TASK_DUR=$(sqlite3 "$DB" "SELECT COUNT(*) FROM runs WHERE task_duration_ns IS NOT NULL;" 2>/dev/null || echo "0")
check "task_duration_ns populated (expect >0)" "$TASK_DUR" "gt" 0
 
FW_COL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('runs') WHERE name='framework_overhead_ns';")
check "framework_overhead_ns column exists (expect 1)" "$FW_COL" "eq" 1
 
COV_COL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('runs') WHERE name='energy_sample_coverage_pct';")
check "energy_sample_coverage_pct column exists (expect 1)" "$COV_COL" "eq" 1
 
POWER_COL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('runs') WHERE name='avg_task_power_watts';")
check "avg_task_power_watts column exists (expect 1)" "$POWER_COL" "eq" 1
 
# Verify coverage values are populated and reasonable (between 0 and 100)
COV_VALID=$(sqlite3 "$DB" "SELECT COUNT(*) FROM runs WHERE energy_sample_coverage_pct BETWEEN 0 AND 100;" 2>/dev/null || echo "0")
check "coverage_pct values in valid range (expect >0)" "$COV_VALID" "gt" 0
 
# Verify avg_task_power_watts is populated
POWER_POP=$(sqlite3 "$DB" "SELECT COUNT(*) FROM runs WHERE avg_task_power_watts IS NOT NULL AND avg_task_power_watts > 0;" 2>/dev/null || echo "0")
check "avg_task_power_watts populated (expect >0)" "$POWER_POP" "gt" 0

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "Results: $PASS passed, $FAIL failed"
echo "============================================================"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
