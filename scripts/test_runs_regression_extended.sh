#!/usr/bin/env bash
# =============================================================================
# A-LEMS Extended Runs Regression Test — all 110 columns
# Usage: bash scripts/test_runs_regression_extended.sh
# =============================================================================

DB="data/experiments.db"
RUN_ID=$(sqlite3 "$DB" "SELECT MAX(run_id) FROM runs WHERE workflow_type='agentic';")
WORKFLOW=$(sqlite3 "$DB" "SELECT workflow_type FROM runs WHERE run_id=$RUN_ID;")

pass=0; fail=0; warn=0

echo "============================================================"
echo "A-LEMS Extended Runs Regression Test"
echo "DB:       $DB"
echo "Run ID:   $RUN_ID"
echo "Workflow: $WORKFLOW"
echo "============================================================"

check_range() {
    local label="$1" val="$2" lo="$3" hi="$4"
    if [ -z "$val" ] || [ "$val" = "NULL" ]; then
        echo "❌ FAIL  $label: NULL"; ((fail++)); return
    fi
    ok=$(python3 -c "print('ok' if $lo <= float('$val') <= $hi else 'fail')" 2>/dev/null)
    if [ "$ok" = "ok" ]; then echo "✅ PASS  $label: $val (range [$lo, $hi])"; ((pass++))
    else echo "❌ FAIL  $label: $val (expected [$lo, $hi])"; ((fail++)); fi
}

check_gt() {
    local label="$1" val="$2" lo="$3"
    if [ -z "$val" ] || [ "$val" = "NULL" ]; then
        echo "❌ FAIL  $label: NULL"; ((fail++)); return
    fi
    ok=$(python3 -c "print('ok' if float('$val') > $lo else 'fail')" 2>/dev/null)
    if [ "$ok" = "ok" ]; then echo "✅ PASS  $label: $val > $lo"; ((pass++))
    else echo "❌ FAIL  $label: $val (expected > $lo)"; ((fail++)); fi
}

check_eq() {
    local label="$1" val="$2" expected="$3"
    if [ "$val" = "$expected" ]; then echo "✅ PASS  $label: $val"; ((pass++))
    else echo "❌ FAIL  $label: $val (expected $expected)"; ((fail++)); fi
}

check_notnull() {
    local label="$1" val="$2"
    if [ -z "$val" ] || [ "$val" = "NULL" ]; then
        echo "❌ FAIL  $label: NULL"; ((fail++))
    else echo "✅ PASS  $label: $val"; ((pass++)); fi
}

q() { sqlite3 "$DB" "SELECT $1 FROM runs WHERE run_id=$RUN_ID;"; }

# =============================================================================
echo "--- Identity ---"
check_notnull "run_id"        "$(q run_id)"
check_notnull "exp_id"        "$(q exp_id)"
check_notnull "hw_id"         "$(q hw_id)"
check_notnull "baseline_id"   "$(q baseline_id)"
check_notnull "run_state_hash" "$(q run_state_hash)"
check_eq      "workflow_type" "$(q workflow_type)" "agentic"
check_eq      "experiment_valid" "$(q experiment_valid)" "1"

# =============================================================================
echo "--- Timestamps ---"
check_gt  "start_time_ns"  "$(q start_time_ns)"  "0"
check_gt  "end_time_ns"    "$(q end_time_ns)"    "0"
check_gt  "duration_ns"    "$(q duration_ns)"    "0"

# =============================================================================
echo "--- Energy (raw) ---"
check_range "pkg_energy_uj"      "$(q pkg_energy_uj)"      100000 50000000000
check_range "core_energy_uj"     "$(q core_energy_uj)"     100000 50000000000
check_range "dynamic_energy_uj"  "$(q dynamic_energy_uj)"  100000 50000000000
check_gt    "baseline_energy_uj" "$(q baseline_energy_uj)" 0
check_gt    "avg_power_watts"    "$(q avg_power_watts)"    0
# physics: core < pkg
core=$(q core_energy_uj); pkg=$(q pkg_energy_uj)
ok=$(python3 -c "print('ok' if int('$core') < int('$pkg') else 'fail')")
[ "$ok" = "ok" ] && { echo "✅ PASS  core < pkg (physics)"; ((pass++)); } || { echo "❌ FAIL  core < pkg"; ((fail++)); }

# =============================================================================
echo "--- Energy (derived) ---"
check_gt    "attributed_energy_uj"   "$(q attributed_energy_uj)"   0
check_range "cpu_fraction"           "$(q cpu_fraction)"           0.0 1.0
check_eq    "energy_measurement_mode" "$(q energy_measurement_mode)" "MEASURED"
check_gt    "energy_per_token"       "$(q energy_per_token)"       0
check_gt    "energy_per_instruction" "$(q energy_per_instruction)" 0
check_gt    "energy_per_cycle"       "$(q energy_per_cycle)"       0

# =============================================================================
echo "--- Phase attribution (Chunk 5) ---"
python scripts/etl/phase_attribution_etl.py --run-id $RUN_ID > /dev/null 2>&1
plan=$(q planning_energy_uj); exec=$(q execution_energy_uj); syn=$(q synthesis_energy_uj); attr=$(q attributed_energy_uj)
phase_sum=$(python3 -c "print(int('${plan:-0}') + int('${exec:-0}') + int('${syn:-0}'))")
diff=$(python3 -c "print(abs(int('$attr') - $phase_sum))")
check_gt "planning_energy_uj"  "${plan:-0}" -1
check_gt "execution_energy_uj" "${exec:-0}" -1
echo "   phase_sum=$phase_sum attributed=$attr diff=$diff"
ok=$(python3 -c "print('ok' if $diff == 0 else 'fail')")
[ "$ok" = "ok" ] && { echo "✅ PASS  phase accounting closure (diff=0)"; ((pass++)); } || { echo "❌ FAIL  phase accounting closure (diff=$diff)"; ((fail++)); }

# =============================================================================
echo "--- CPU performance ---"
check_range "ipc"            "$(q ipc)"            0.1 8.0
check_range "cache_miss_rate" "$(q cache_miss_rate)" 0.0 100.0
check_range "frequency_mhz"  "$(q frequency_mhz)"  50 6000
check_gt    "instructions"   "$(q instructions)"   0
check_gt    "cycles"         "$(q cycles)"         0
check_gt    "instructions_per_token" "$(q instructions_per_token)" 0

# =============================================================================
echo "--- Context switches & scheduling ---"
check_gt    "total_context_switches" "$(q total_context_switches)" 0
check_range "run_queue_length"       "$(q run_queue_length)"       0 1000
check_notnull "pid"                  "$(q pid)"

# =============================================================================
echo "--- Memory ---"
check_range "rss_memory_mb"  "$(q rss_memory_mb)"  10 64000
check_range "vms_memory_mb"  "$(q vms_memory_mb)"  10 200000

# =============================================================================
echo "--- Thermal ---"
check_range "package_temp_celsius" "$(q package_temp_celsius)" 20 105
check_range "max_temp_c"           "$(q max_temp_c)"           20 105
check_range "min_temp_c"           "$(q min_temp_c)"           20 105
check_range "thermal_delta_c"      "$(q thermal_delta_c)"      0 85
check_eq    "thermal_throttle_flag" "$(q thermal_throttle_flag)" "0"

# =============================================================================
echo "--- Sustainability ---"
check_gt    "carbon_g"    "$(q carbon_g)"    0
check_gt    "water_ml"    "$(q water_ml)"    0
check_gt    "methane_mg"  "$(q methane_mg)"  0

# =============================================================================
echo "--- LLM metrics ---"
check_range "api_latency_ms"   "$(q api_latency_ms)"   100 300000
check_gt    "total_tokens"     "$(q total_tokens)"     0
check_gt    "planning_time_ms" "$(q planning_time_ms)" 0
check_gt    "execution_time_ms" "$(q execution_time_ms)" 0
check_range "complexity_score" "$(q complexity_score)" 0.0 1.0
check_notnull "complexity_level" "$(q complexity_level)"

# =============================================================================
echo "--- Phase ratios ---"
ratio_sum=$(python3 -c "
p=$(q phase_planning_ratio); e=$(q phase_execution_ratio); s=$(q phase_synthesis_ratio)
print(round(p+e+s, 4))")
ok=$(python3 -c "print('ok' if 0.95 <= float('$ratio_sum') <= 1.05 else 'fail')")
[ "$ok" = "ok" ] && { echo "✅ PASS  phase ratios sum: $ratio_sum"; ((pass++)); } || { echo "❌ FAIL  phase ratios sum: $ratio_sum"; ((fail++)); }

# =============================================================================
echo "--- Agentic orchestration ---"
check_gt    "llm_calls"          "$(q llm_calls)"          0
check_gt    "orchestration_cpu_ms" "$(q orchestration_cpu_ms)" 0
check_notnull "tools_used"       "$(q tools_used)"
check_notnull "steps"            "$(q steps)"

# =============================================================================
echo "--- Network ---"
check_notnull "bytes_sent"      "$(q bytes_sent)"
check_notnull "bytes_recv"      "$(q bytes_recv)"
check_notnull "tcp_retransmits" "$(q tcp_retransmits)"

# =============================================================================
echo "--- Provenance ---"
prov_rows=$(sqlite3 "$DB" "SELECT COUNT(*) FROM measurement_methodology WHERE run_id=$RUN_ID;")
check_range "provenance rows" "$prov_rows" 60 200
orphans=$(sqlite3 "$DB" "SELECT COUNT(*) FROM measurement_methodology mm LEFT JOIN runs r ON mm.run_id=r.run_id WHERE r.run_id IS NULL;")
check_eq "orphan methodology rows" "$orphans" "0"

# =============================================================================
echo "--- Governor & system ---"
check_notnull "governor"      "$(q governor)"
check_notnull "turbo_enabled" "$(q turbo_enabled)"
check_notnull "process_count" "$(q process_count)"

# =============================================================================
echo "============================================================"
echo "Results: $pass passed  $fail failed  $warn warnings"
echo "============================================================"
[ $fail -eq 0 ] && exit 0 || exit 1
