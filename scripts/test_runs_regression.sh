#!/bin/bash
# =============================================================================
# scripts/test_runs_regression.sh
# =============================================================================
# Statistical regression test for runs table.
# Compares recent run values against known good ranges from validated runs.
# Fails if any metric falls outside expected range — catches regressions.
#
# Usage:
#   bash scripts/test_runs_regression.sh
#   bash scripts/test_runs_regression.sh --run-id 1835
#   bash scripts/test_runs_regression.sh --update-baseline   # save new baseline
# =============================================================================

set -euo pipefail

DB="${DB:-data/experiments.db}"
PASS=0
FAIL=0
WARN=0

# ── Get run_id ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--run-id" ]]; then
    RUN_ID="$2"
else
    RUN_ID=$(sqlite3 "$DB" "SELECT MAX(run_id) FROM runs WHERE experiment_valid=1;")
fi

WORKFLOW=$(sqlite3 "$DB" "SELECT workflow_type FROM runs WHERE run_id=$RUN_ID;")

echo "============================================================"
echo "A-LEMS Runs Regression Test"
echo "DB:       $DB"
echo "Run ID:   $RUN_ID"
echo "Workflow: $WORKFLOW"
echo "============================================================"
echo ""

# ── Helpers ───────────────────────────────────────────────────────────────────
check_range() {
    local name="$1"
    local actual="$2"
    local min="$3"
    local max="$4"

    # Use awk for float comparison
    IN_RANGE=$(awk -v a="$actual" -v mn="$min" -v mx="$max" \
        'BEGIN { print (a >= mn && a <= mx) ? "1" : "0" }')

    if [ "$IN_RANGE" == "1" ]; then
        echo "✅ PASS  $name: $actual (range [$min, $max])"
        PASS=$((PASS + 1))
    else
        echo "❌ FAIL  $name: $actual (expected [$min, $max])"
        FAIL=$((FAIL + 1))
    fi
}

check_positive() {
    local name="$1"
    local actual="$2"
    local positive=$(awk -v a="$actual" 'BEGIN { print (a > 0) ? "1" : "0" }')
    if [ "$positive" == "1" ]; then
        echo "✅ PASS  $name: $actual > 0"
        PASS=$((PASS + 1))
    else
        echo "❌ FAIL  $name: $actual (expected > 0)"
        FAIL=$((FAIL + 1))
    fi
}

check_not_null() {
    local name="$1"
    local actual="$2"
    if [ -n "$actual" ] && [ "$actual" != "NULL" ] && [ "$actual" != "" ]; then
        echo "✅ PASS  $name: $actual (not null)"
        PASS=$((PASS + 1))
    else
        echo "❌ FAIL  $name: NULL or empty"
        FAIL=$((FAIL + 1))
    fi
}

get_val() {
    sqlite3 "$DB" "SELECT COALESCE($1, 'NULL') FROM runs WHERE run_id=$RUN_ID;"
}

# ── T1: Run exists and is valid ───────────────────────────────────────────────
echo "--- Run validity ---"
VALID=$(sqlite3 "$DB" "SELECT experiment_valid FROM runs WHERE run_id=$RUN_ID;")
[ "$VALID" == "1" ] && { echo "✅ PASS  experiment_valid: 1"; PASS=$((PASS+1)); } \
    || { echo "❌ FAIL  experiment_valid: $VALID (expected 1)"; FAIL=$((FAIL+1)); }

# ── T2: Energy values — physical plausibility ─────────────────────────────────
echo ""
echo "--- Energy plausibility ---"
PKG=$(get_val "pkg_energy_uj")
CORE=$(get_val "core_energy_uj")
DYNAMIC=$(get_val "dynamic_energy_uj")

check_range "pkg_energy_uj (µJ)" "$PKG" "100000" "50000000000"
check_range "core_energy_uj (µJ)" "$CORE" "100000" "50000000000"
check_positive "dynamic_energy_uj" "$DYNAMIC"

# core must be less than pkg (physics)
CORE_LT_PKG=$(awk -v c="$CORE" -v p="$PKG" 'BEGIN { print (c < p) ? "1" : "0" }')
[ "$CORE_LT_PKG" == "1" ] && { echo "✅ PASS  core < pkg (physics check)"; PASS=$((PASS+1)); } \
    || { echo "❌ FAIL  core >= pkg — RAPL domain error"; FAIL=$((FAIL+1)); }

# ── T3: CPU performance — sanity ranges ──────────────────────────────────────
echo ""
echo "--- CPU performance ---"
IPC=$(get_val "ipc")
CACHE_MISS=$(get_val "cache_miss_rate")
FREQ=$(get_val "frequency_mhz")

check_range "ipc" "$IPC" "0.1" "8.0"
check_range "cache_miss_rate (%)" "$CACHE_MISS" "0.0" "100.0"
check_range "frequency_mhz" "$FREQ" "400" "6000"

# ── T4: Sustainability — carbon must be positive ──────────────────────────────
echo ""
echo "--- Sustainability ---"
CARBON=$(get_val "carbon_g")
WATER=$(get_val "water_ml")
check_positive "carbon_g" "$CARBON"
check_positive "water_ml" "$WATER"

# ── T5: Thermal — physical bounds ────────────────────────────────────────────
echo ""
echo "--- Thermal ---"
TEMP=$(get_val "package_temp_celsius")
check_range "package_temp_celsius" "$TEMP" "20" "105"

# ── T6: LLM metrics — agentic only ───────────────────────────────────────────
if [ "$WORKFLOW" == "agentic" ]; then
    echo ""
    echo "--- LLM metrics (agentic) ---"
    API_LAT=$(get_val "api_latency_ms")
    TOKENS=$(get_val "total_tokens")
    PLAN=$(get_val "planning_time_ms")
    EXEC=$(get_val "execution_time_ms")
    SYNTH=$(get_val "synthesis_time_ms")

    check_range "api_latency_ms" "$API_LAT" "100" "300000"
    check_positive "total_tokens" "$TOKENS"
    check_positive "planning_time_ms" "$PLAN"
    check_positive "execution_time_ms" "$EXEC"

    # Phase ratios must sum to ~1.0
    RATIO_SUM=$(sqlite3 "$DB" "
        SELECT ROUND(
            phase_planning_ratio + phase_execution_ratio + phase_synthesis_ratio
        , 2)
        FROM runs WHERE run_id=$RUN_ID;")
    check_range "phase ratios sum" "$RATIO_SUM" "0.95" "1.05"

    # Complexity score 0-1
    COMPLEX=$(get_val "complexity_score")
    check_range "complexity_score" "$COMPLEX" "0.0" "1.0"
fi

# ── T7: Linear metrics ────────────────────────────────────────────────────────
if [ "$WORKFLOW" == "linear" ]; then
    echo ""
    echo "--- LLM metrics (linear) ---"
    API_LAT=$(get_val "api_latency_ms")
    check_range "api_latency_ms" "$API_LAT" "100" "300000"
fi

# ── T8: Memory — physical bounds ─────────────────────────────────────────────
echo ""
echo "--- Memory ---"
RSS=$(get_val "rss_memory_mb")
check_range "rss_memory_mb" "$RSS" "10" "64000"

# ── T9: Provenance rows match ─────────────────────────────────────────────────
echo ""
echo "--- Provenance coverage ---"
PROV_COUNT=$(sqlite3 "$DB" "
    SELECT COUNT(*) FROM measurement_methodology WHERE run_id=$RUN_ID;")
check_range "provenance rows" "$PROV_COUNT" "60" "200"

# ── T10: No orphan methodology rows ──────────────────────────────────────────
echo ""
echo "--- Data integrity ---"
ORPHAN=$(sqlite3 "$DB" "
    SELECT COUNT(*) FROM measurement_methodology mm
    LEFT JOIN measurement_method_registry mmr ON mm.method_id = mmr.id
    WHERE mm.run_id = $RUN_ID AND mmr.id IS NULL;")
[ "$ORPHAN" -eq 0 ] && { echo "✅ PASS  No orphan methodology rows: 0"; PASS=$((PASS+1)); } \
    || { echo "❌ FAIL  Orphan methodology rows: $ORPHAN"; FAIL=$((FAIL+1)); }

# ── T11: Compare with previous run ───────────────────────────────────────────
echo ""
echo "--- Trend check (vs previous run) ---"
PREV_RUN=$(sqlite3 "$DB" "
    SELECT run_id FROM runs
    WHERE run_id < $RUN_ID
      AND workflow_type = '$WORKFLOW'
      AND experiment_valid = 1
    ORDER BY run_id DESC LIMIT 1;")

if [ -n "$PREV_RUN" ]; then
    PREV_PKG=$(sqlite3 "$DB" "SELECT pkg_energy_uj FROM runs WHERE run_id=$PREV_RUN;")
    CURR_PKG=$(get_val "pkg_energy_uj")

    # Energy should not change by more than 10x between similar runs
    RATIO=$(awk -v c="$CURR_PKG" -v p="$PREV_PKG" \
        'BEGIN { if (p>0) print c/p; else print 1 }')
    CHECK=$(awk -v r="$RATIO" 'BEGIN { print (r > 0.1 && r < 10) ? "1" : "0" }')

    [ "$CHECK" == "1" ] && \
        { echo "✅ PASS  pkg_energy ratio vs run $PREV_RUN: ${RATIO}x"; PASS=$((PASS+1)); } || \
        { echo "⚠️  WARN  pkg_energy ratio vs run $PREV_RUN: ${RATIO}x (>10x change)"; WARN=$((WARN+1)); }
else
    echo "  (no previous $WORKFLOW run to compare)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "Results: $PASS passed  $FAIL failed  $WARN warnings"
echo "============================================================"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
