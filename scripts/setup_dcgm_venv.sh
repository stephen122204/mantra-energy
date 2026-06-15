#!/bin/bash
# Adds DCGM Python bindings to the active venv via .pth file.
# Run on GN100 only after activating venv.
# Safe to rerun — idempotent.

DCGM_PATH="/usr/local/dcgm/bindings/python3"
PTH_FILE="$(python3 -c 'import site; print(site.getsitepackages()[0])')/dcgm_bindings.pth"

if [ ! -d "$DCGM_PATH" ]; then
    echo "DCGM bindings not found at $DCGM_PATH — skipping (not a GN100 machine)"
    exit 0
fi

echo "$DCGM_PATH" > "$PTH_FILE"
echo "✅ DCGM bindings registered at $PTH_FILE"
python3 -c "import pydcgm; print('✅ pydcgm import OK')"
