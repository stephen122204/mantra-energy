#!/usr/bin/env bash
# A-LEMS platform verification: Intel x86_64 (UBUNTU2505)
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

echo "A-LEMS Verification: Intel x86_64"
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
check "power_rails (empty on x86)" "0" "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM power_rails;")"

echo ""

# ── Intel-specific checks ────────────────────────────────────────────
echo "Intel-specific:"
RAPL_DOMAINS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM energy_domains WHERE name IN ('PACKAGE','CORE','UNCORE','DRAM');")
check "RAPL domains present"    "4"   "$RAPL_DOMAINS"

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
check "hw_config.json cpu_vendor" "intel" "$HW_CONFIG"

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
