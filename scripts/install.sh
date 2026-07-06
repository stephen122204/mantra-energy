#!/usr/bin/env bash
# A-LEMS Unified Installer
# One script, all platforms. Platform-specific logic in scripts/platforms/.
#
# Usage:
#   bash scripts/install.sh
#
# Sequencing is critical. Do not reorder steps.
# schema_version must exist before detect_environment.py reads it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Step 0: Detect platform ──────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"

case "${OS}_${ARCH}" in
    Linux_x86_64)   PLATFORM="intel_x86"  ;;
    Linux_aarch64)  PLATFORM="linux_arm"   ;;
    Darwin_arm64)   PLATFORM="apple_m1"    ;;
    Darwin_x86_64)  PLATFORM="intel_mac"   ;;
    *)
        echo "ERROR: Unsupported platform: ${OS} ${ARCH}"
        echo "Supported: Linux x86_64, Linux aarch64, Darwin arm64"
        exit 1
        ;;
esac

PLATFORM_DIR="${SCRIPT_DIR}/platforms/${PLATFORM}"
if [ ! -d "$PLATFORM_DIR" ]; then
    echo "ERROR: No platform directory at ${PLATFORM_DIR}"
    echo "Create it with provision.sh and verify.sh before running install."
    exit 1
fi

echo "A-LEMS Installer"
echo "  Platform: ${PLATFORM} (${OS} ${ARCH})"
echo "  Project:  ${PROJECT_ROOT}"
echo ""

# ── Step 1: Python venv ──────────────────────────────────────────────
echo "[1/12] Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  Created venv/"
else
    echo "  venv/ already exists, reusing"
fi
# shellcheck disable=SC1091
source venv/bin/activate

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "  Base dependencies installed"

# ── Step 2: Platform-specific dependencies ───────────────────────────
echo "[2/12] Platform-specific dependencies..."
if [ -f "${PLATFORM_DIR}/provision.sh" ]; then
    bash "${PLATFORM_DIR}/provision.sh" deps
else
    echo "  No platform deps script, skipping"
fi

# ── Step 3: Permissions ──────────────────────────────────────────────
echo "[3/12] Permissions..."
if [ -f "${PLATFORM_DIR}/provision.sh" ]; then
    bash "${PLATFORM_DIR}/provision.sh" permissions
else
    echo "  No platform permissions script, skipping"
fi

# ── Step 4: Hardware detection ───────────────────────────────────────
echo "[4/12] Hardware detection..."
python3 scripts/detect_hardware.py
echo "  hw_config.json written"

# ── Step 5: ~/.alemsrc setup ─────────────────────────────────────────
echo "[5/12] Data directory setup..."
ALEMSRC="$HOME/.alemsrc"
HOSTNAME_LOWER="$(hostname | tr '[:upper:]' '[:lower:]')"

if [ -f "$ALEMSRC" ] && grep -q "ALEMS_DATA_ROOT" "$ALEMSRC"; then
    echo "  ~/.alemsrc already configured"
    # shellcheck disable=SC1090
    source "$ALEMSRC"
else
    echo ""
    echo "  A-LEMS stores experiment data outside the repo."
    echo "  Default: /mnt/alems-data"
    echo ""
    read -rp "  Data root [/mnt/alems-data]: " DATA_ROOT
    DATA_ROOT="${DATA_ROOT:-/mnt/alems-data}"

    MACHINE_DIR="${DATA_ROOT}/${HOSTNAME_LOWER}"
    mkdir -p "$MACHINE_DIR"

    # Write or append to ~/.alemsrc
    if [ ! -f "$ALEMSRC" ]; then
        echo "# A-LEMS environment (sourced by path_loader.py)" > "$ALEMSRC"
    fi
    echo "export ALEMS_DATA_ROOT=${DATA_ROOT}" >> "$ALEMSRC"
    export ALEMS_DATA_ROOT="${DATA_ROOT}"
    echo "  ~/.alemsrc written: ALEMS_DATA_ROOT=${DATA_ROOT}"
    echo "  Machine data dir:   ${MACHINE_DIR}/"
fi

# Resolve actual DB path via path_loader
DB_PATH=$(python3 -c "from scripts.tools.path_loader import get_alems_db_path; print(get_alems_db_path())")
DB_DIR="$(dirname "$DB_PATH")"
mkdir -p "$DB_DIR"
echo "  DB path: ${DB_PATH}"

# ── Step 6: Database init ────────────────────────────────────────────
echo "[6/12] Database initialization..."
python3 -c "
from core.database.sqlite_adapter import SQLiteAdapter
db = SQLiteAdapter('${DB_PATH}')
db.create_tables()
print('  Tables created')
"

# ── Step 7: Universal seed data ──────────────────────────────────────
echo "[7/12] Universal seed data..."
SEED_DIR="migrations/seed"
if [ -d "$SEED_DIR" ]; then
    for f in "$SEED_DIR"/s*.sql; do
        [ -f "$f" ] || continue
        sqlite3 "$DB_PATH" < "$f"
        echo "  Applied $(basename "$f")"
    done
else
    echo "  WARNING: ${SEED_DIR}/ not found, skipping seed data"
fi

# ── Step 8: Schema migrations ────────────────────────────────────────
echo "[8/12] Schema migrations..."
python3 scripts/tools/alems_migrate.py
echo "  Migrations applied"

# ── Step 9: Platform-specific seed data ──────────────────────────────
echo "[9/12] Platform seed data..."
PLATFORM_SEED="migrations/platform/${PLATFORM}"
if [ -d "$PLATFORM_SEED" ]; then
    for f in "$PLATFORM_SEED"/*.sql; do
        [ -f "$f" ] || continue
        sqlite3 "$DB_PATH" < "$f"
        echo "  Applied $(basename "$f")"
    done
else
    echo "  No platform-specific seed data for ${PLATFORM}"
fi

# ── Step 10: Environment detection ───────────────────────────────────
echo "[10/12] Environment detection..."
python3 scripts/detect_environment.py
echo "  Environment detected"

# ── Step 11: Methodology seeding ─────────────────────────────────────
echo "[11/12] Methodology seeding..."
python3 scripts/seed_methodology.py
echo "  Methodology registry populated"

# ── Step 12: Model/API setup ─────────────────────────────────────────
echo "[12/12] Model and API setup..."
if [ -f "${PLATFORM_DIR}/provision.sh" ]; then
    bash "${PLATFORM_DIR}/provision.sh" models
else
    echo "  No platform model setup, skipping"
fi

# ── Verification ─────────────────────────────────────────────────────
echo ""
echo "Running verification..."
if [ -f "${PLATFORM_DIR}/verify.sh" ]; then
    bash "${PLATFORM_DIR}/verify.sh" "$DB_PATH"
fi

echo ""
echo "A-LEMS installation complete."
echo "  Platform: ${PLATFORM}"
echo "  Database: ${DB_PATH}"
echo ""
echo "Next steps:"
echo "  source venv/bin/activate"
echo "  python -m core.execution.tests.test_llm_setup --provider all --verbose"
echo "  python -m core.execution.tests.test_harness --task-id gsm8k_basic --repetitions 1 --save-db"
