#!/usr/bin/env bash
# A-LEMS platform verification: AMD x86_64 (Ryzen + NVIDIA discrete GPU)
# Called by install.sh with DB_PATH as $1
set -euo pipefail

DB_PATH="${1:-data/experiments.db}"
PASS=0
FAIL=0

check() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    if [ "$actual" = "$expected" ]; then
        echo "  OK  $label ($actual)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL $label (expected $expected, got $actual)"
        FAIL=$((FAIL + 1))
    fi
}

echo "A-LEMS Verification: AMD x86_64"
echo "  DB: ${DB_PATH}"
echo ""

# ── Seed data row counts ─────────────────────────────────────────────
echo "Seed data:"
check "energy_sources"           "9"   "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM energy_sources;")"
check "energy_domains"           "29"  "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM energy_domains;")"
check "retry_policy"             "3"   "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM retry_policy;")"
check "outlier_detection_config" "11"  "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM outlier_detection_config;")"
check "analysis_domain_config"   "10"  "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM analysis_domain_config;")"
check "analysis_view_config"     "8"   "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM analysis_view_config;")"
check "metric_analysis_domains"  "132" "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM metric_analysis_domains;")"
check "power_limits"             "4"   "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM power_limits;")"
check "power_rails (empty on AMD)" "0" "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM power_rails;")"

echo ""

# ── AMD-specific checks ──────────────────────────────────────────────
echo "AMD-specific:"

# RAPL readable
RAPL_OK="false"
if cat /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj > /dev/null 2>&1; then
    RAPL_OK="true"
fi
check "RAPL energy_uj readable" "true" "$RAPL_OK"

# RAPL domains in DB
RAPL_DOMAINS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM energy_domains WHERE name IN ('PACKAGE','CORE');")
check "PACKAGE+CORE domains"   "2"    "$RAPL_DOMAINS"

# k10temp hwmon available (search by name, not number)
K10_OK="false"
for h in /sys/class/hwmon/hwmon*/; do
    [ "$(cat ${h}name 2>/dev/null)" = "k10temp" ] && K10_OK="true"
done
check "k10temp hwmon"          "true"  "$K10_OK"

# cpuidle sysfs (for cpu_idle_states fallback since turbostat crashes)
CPUIDLE_OK="false"
[ -d "/sys/devices/system/cpu/cpu0/cpuidle/state0" ] && CPUIDLE_OK="true"
check "cpuidle sysfs"          "true"  "$CPUIDLE_OK"

# NVML
NVML_OK=$(python3 -c "
import pynvml
pynvml.nvmlInit()
print('true')
" 2>/dev/null || echo "false")
check "pynvml/NVML"            "true"  "$NVML_OK"

echo ""

# ── Detection ────────────────────────────────────────────────────────
echo "Detection:"
HW_CONFIG=$(python3 -c "
import json, os
p = 'hw_config.json'
if os.path.exists(p):
    d = json.load(open(p))
    print(d.get('cpu_vendor','MISSING'))
else:
    print('NO_FILE')
" 2>/dev/null)
check "hw_config.json cpu_vendor" "amd" "$HW_CONFIG"

# Python version check (3.14 breaks pinned deps, need 3.9-3.12)
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PY_OK="false"
[ "$PY_MINOR" -ge 9 ] && [ "$PY_MINOR" -le 12 ] && PY_OK="true"
check "Python 3.9-3.12"       "true"  "$PY_OK"

echo ""

# ── Methodology ──────────────────────────────────────────────────────
echo "Methodology:"
MMR_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM measurement_method_registry;" 2>/dev/null || echo "0")
check "measurement_method_registry > 0" "true" "$([ "$MMR_COUNT" -gt 0 ] && echo true || echo false)"

echo ""

# ── Schema completeness ─────────────────────────────────────────────
echo "Schema completeness:"
TABLE_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';")
check "table count >= 70" "true" "$([ "$TABLE_COUNT" -ge 70 ] && echo true || echo false)"

RK_EXISTS=$(sqlite3 "$DB_PATH" "PRAGMA table_info(energy_domains);" | grep -c "reader_keys" || echo "0")
check "energy_domains.reader_keys column" "1" "$RK_EXISTS"

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
if [ "$FAIL" -gt 0 ]; then
    echo "VERIFICATION FAILED"
    exit 1
fi
echo "VERIFICATION PASSED"
