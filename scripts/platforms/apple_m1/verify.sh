#!/usr/bin/env bash
# A-LEMS platform verification: Apple Silicon (M1/M2/M3)
# Called by install.sh with DB_PATH as $1
# Verifies all seed tables, detection, and reader availability.
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

echo "A-LEMS Verification: Apple Silicon"
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
check "power_rails (empty on Mac)" "0" "$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM power_rails;")"

echo ""

# ── Apple-specific seed rows ─────────────────────────────────────────
echo "Apple-specific domain/source rows:"
IOKIT_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM energy_sources WHERE name='IOKIT';")
check "IOKIT source row"         "1"   "$IOKIT_COUNT"
UNIFIED_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM energy_domains WHERE name='UNIFIED';")
check "UNIFIED domain row"       "1"   "$UNIFIED_COUNT"
CPU_APPLE_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM energy_domains WHERE name='CPU_APPLE';")
check "CPU_APPLE domain row"     "1"   "$CPU_APPLE_COUNT"
GPU_APPLE_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM energy_domains WHERE name='GPU_APPLE';")
check "GPU_APPLE domain row"     "1"   "$GPU_APPLE_COUNT"

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
check "hw_config.json cpu_vendor" "apple" "$HW_CONFIG"

CAPS=$(python3 -c "
from core.utils.platform import get_platform_capabilities
c = get_platform_capabilities()
print(f'{c.os}_{c.arch}_{c.measurement_mode}')
" 2>/dev/null || echo "IMPORT_FAIL")
check "PlatformCapabilities"     "Darwin_arm64_MEASURED" "$CAPS"

echo ""

# ── Methodology ──────────────────────────────────────────────────────
echo "Methodology:"
MMR_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM measurement_method_registry;" 2>/dev/null || echo "0")
check "measurement_method_registry > 0" "true" "$([ "$MMR_COUNT" -gt 0 ] && echo true || echo false)"

IOKIT_METHODS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM measurement_method_registry WHERE method_id LIKE 'iokit%';" 2>/dev/null || echo "0")
check "IOKit methods registered" "true" "$([ "$IOKIT_METHODS" -gt 0 ] && echo true || echo false)"

echo ""

# ── Reader availability ──────────────────────────────────────────────
echo "Reader availability:"
POWER_AVAIL=$(python3 -c "
from core.readers.darwin.iokit_power_reader import IOKitPowerReader
r = IOKitPowerReader({})
print('true' if r.is_available() else 'false')
" 2>/dev/null || echo "IMPORT_FAIL")
check "IOKitPowerReader available" "true" "$POWER_AVAIL"

echo ""

# ── Empty tables (correct on this platform) ──────────────────────────
echo "Tables empty by design on Mac:"
for t in power_rail_samples run_power_limits power_limit_events; do
    count=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM $t;" 2>/dev/null || echo "MISSING")
    check "$t" "0" "$count"
done

echo ""

# ── Schema completeness ─────────────────────────────────────────────
echo "Schema completeness:"
TABLE_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';")
check "table count >= 70" "true" "$([ "$TABLE_COUNT" -ge 70 ] && echo true || echo false)"

# Verify reader_keys column exists in energy_domains
RK_EXISTS=$(sqlite3 "$DB_PATH" "PRAGMA table_info(energy_domains);" | grep -c "reader_keys" || echo "0")
check "energy_domains.reader_keys column" "1" "$RK_EXISTS"

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
if [ "$FAIL" -gt 0 ]; then
    echo "VERIFICATION FAILED"
    exit 1
fi
echo "VERIFICATION PASSED"
