#!/bin/bash
# ============================================================================
# setup_darwin.sh — one-shot A-LEMS setup for a fresh Apple Silicon Mac
#
# Replicates every manual step from the 2026-07-02 M1 Pro onboarding
# session in one script: repo clone check, venv, dependencies, permission
# fix, hardware detection, vendored thermal helper build, verification.
#
# Run from the repo root after cloning:
#   bash scripts/setup_darwin.sh
# ============================================================================

set -e

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This script is for macOS only."
    exit 1
fi

echo "================================================================="
echo "A-LEMS Apple Silicon Setup"
echo "================================================================="

echo -e "\n[1/7] Checking Xcode command line tools..."
if ! xcode-select -p > /dev/null 2>&1; then
    echo "  Xcode command line tools not found, installing..."
    xcode-select --install
    echo "  ⚠️  Complete the Xcode install dialog, then re-run this script."
    exit 1
fi
echo "  ✅ Xcode command line tools present"

echo -e "\n[2/7] Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
echo "  ✅ venv ready"

echo -e "\n[3/7] Python dependencies..."
pip install -q -r requirements.txt
echo "  ✅ requirements installed"

echo -e "\n[4/7] Permission setup (sudoers rule for powermetrics, one time password prompt)..."
sudo ./scripts/fix_permissions.sh

echo -e "\n[5/7] Hardware detection..."
python3 scripts/detect_hardware.py --output config/hw_config.json --merge
CPU_VENDOR=$(python3 -c "import json; print(json.load(open('config/hw_config.json'))['cpu_vendor'])")
if [ "$CPU_VENDOR" != "apple" ]; then
    echo "  ⚠️  cpu_vendor detected as '$CPU_VENDOR', expected 'apple'."
    echo "     Check detect_hardware.py Darwin branch, see IMPL_16F1.md"
    exit 1
fi
echo "  ✅ Hardware detected correctly: cpu_vendor=apple"

echo -e "\n[6/7] Building vendored thermal sensor helper (Koan-Sin Tan, BSD 3-Clause)..."
VENDOR_DIR="core/readers/darwin/vendor"
if [ ! -f "$VENDOR_DIR/sensors.m" ] || [ ! -f "$VENDOR_DIR/LICENSE" ]; then
    echo "  ❌ Vendored sensors.m/LICENSE missing from repo at $VENDOR_DIR"
    echo "     These are committed source files, not fetched at setup time."
    echo "     Check the repo checkout, git pull may be needed."
    exit 1
fi
echo "  ✅ sensors.m and LICENSE present (vendored in repo)"
clang -Wall -O2 -g -c -o "$VENDOR_DIR/sensors.o" "$VENDOR_DIR/sensors.m"
clang -o "$VENDOR_DIR/sensors" "$VENDOR_DIR/sensors.o" -framework Foundation -framework IOKit
rm -f "$VENDOR_DIR/sensors.o"
chmod +x "$VENDOR_DIR/sensors"
"$VENDOR_DIR/sensors" -o > /dev/null 2>&1 && echo "  ✅ Sensor helper compiled and runs correctly" \
    || { echo "  ❌ Sensor helper compiled but failed to run"; exit 1; }

echo -e "\n[7/7] Verifying readers..."
python3 -c "
from core.readers.darwin.iokit_power_reader import IOKitPowerReader
from core.readers.darwin.iokit_thermal_reader import IOKitThermalReader
p = IOKitPowerReader({})
t = IOKitThermalReader({})
print('  IOKitPowerReader available:', p.is_available())
print('  IOKitThermalReader available:', t.is_available())
print('  IOKitThermalReader read_all_thermal():', t.read_all_thermal())
"

echo -e "\n================================================================="
echo "✅ A-LEMS Apple Silicon setup complete"
echo "================================================================="
echo ""
echo "Next: python3 scripts/detect_environment.py --verbose"
echo "================================================================="
