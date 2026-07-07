#!/usr/bin/env bash
# A-LEMS platform provisioning: Linux ARM (GN100, NVIDIA Grace GB10)
# Called by install.sh with a subcommand: deps, permissions, models
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SUBCOMMAND="${1:-all}"

case "$SUBCOMMAND" in
    deps)
        echo "  GN100 ARM: installing system build dependencies..."
        sudo apt install -y libjpeg-dev zlib1g-dev libfreetype-dev \
            liblcms2-dev libwebp-dev libxml2-dev libxslt1-dev \
            python3-dev build-essential sqlite3 2>/dev/null || true

        echo "  Installing Python dependencies..."
        pip install --upgrade pip --quiet
        pip install -r requirements.txt --quiet

        echo "  GN100 ARM: checking CUDA/vLLM dependencies..."
        # vllm_local is the primary local provider on GN100
        if python3 -c "import vllm" 2>/dev/null; then
            echo "  vLLM already installed"
        else
            echo "  NOTE: vLLM requires CUDA toolkit and GPU drivers."
            echo "  Install manually if needed: pip install vllm"
        fi
        # GN100-specific requirements file if it exists
        if [ -f "${PROJECT_ROOT}/requirements-gn100.txt" ]; then
            pip install -r "${PROJECT_ROOT}/requirements-gn100.txt" --quiet
            echo "  GN100-specific requirements installed"
        fi
        ;;

    permissions)
        echo "  Setting up RAPL/hwmon permissions..."
        if [ -f "${PROJECT_ROOT}/scripts/fix_permissions.sh" ]; then
            sudo bash "${PROJECT_ROOT}/scripts/fix_permissions.sh"
            echo "  Permissions configured"
        else
            echo "  WARNING: fix_permissions.sh not found"
        fi
        ;;

    models)
        echo "  Model setup for GN100..."
        echo ""
        echo "  GN100 uses vllm_local as primary provider."
        echo "  Ensure a model is downloaded to the models/ directory."
        echo "  Cloud provider (nvidia_nim) needs API key in core/.env"
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
