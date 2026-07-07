#!/usr/bin/env bash
# A-LEMS platform provisioning: AMD x86_64 (Ryzen + NVIDIA discrete GPU)
# Called by install.sh with a subcommand: deps, permissions, models
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SUBCOMMAND="${1:-all}"

case "$SUBCOMMAND" in
    deps)
        echo "  AMD x86: installing system build dependencies..."
        sudo apt install -y libjpeg-dev zlib1g-dev libfreetype-dev \
            liblcms2-dev libwebp-dev libxml2-dev libxslt1-dev \
            python3-dev build-essential sqlite3 2>/dev/null || true

        echo "  Installing Python dependencies..."
        pip install --upgrade pip --quiet
        pip install -r "${PROJECT_ROOT}/requirements.txt" --quiet

        echo "  Installing NVML Python bindings..."
        pip install pynvml --quiet
        python3 -c "import pynvml; pynvml.nvmlInit(); print('  pynvml OK')" || \
            echo "  WARNING: pynvml install failed, GPU energy will be unavailable"

        # AMD-specific requirements if present
        if [ -f "${PROJECT_ROOT}/requirements-amd.txt" ]; then
            pip install -r "${PROJECT_ROOT}/requirements-amd.txt" --quiet
            echo "  AMD-specific requirements installed"
        fi
        ;;

    permissions)
        echo "  Setting up RAPL permissions for AMD..."
        if [ -f "${PROJECT_ROOT}/scripts/fix_permissions.sh" ]; then
            sudo bash "${PROJECT_ROOT}/scripts/fix_permissions.sh"
            echo "  Permissions configured"
        else
            echo "  WARNING: fix_permissions.sh not found"
        fi

        # Verify RAPL readable after permissions fix
        if cat /sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj > /dev/null 2>&1; then
            echo "  RAPL energy_uj readable: OK"
        else
            echo "  WARNING: RAPL energy_uj still not readable"
            echo "  Try: sudo chmod -R a+r /sys/class/powercap/intel-rapl/"
        fi
        ;;

    models)
        echo "  Model setup for AMD x86..."
        echo ""
        echo "  This machine has an RTX 2070 Super (8GB VRAM)."
        echo "  For local inference with GPU acceleration:"
        echo "    pip install llama-cpp-python  (CUDA build)"
        echo "    mkdir -p ~/models"
        echo "    # Download a GGUF model that fits in 8GB VRAM"
        echo ""
        echo "  For cloud inference (nvidia_nim):"
        echo "    Set API key in core/.env:"
        echo "    NVIDIA_NIM_API_KEY=your-key-here"
        echo ""
        echo "  Test with:"
        echo "    python -m core.execution.tests.test_llm_setup --provider all --verbose"
        ;;

    all)
        bash "$0" deps
        bash "$0" permissions
        bash "$0" models
        ;;

    *)
        echo "Usage: provision.sh {deps|permissions|models|all}"
        exit 1
        ;;
esac
