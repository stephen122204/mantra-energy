#!/usr/bin/env bash
# A-LEMS platform provisioning: Intel x86_64 (UBUNTU2505, Lenovo)
# Called by install.sh with a subcommand: deps, permissions, models
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SUBCOMMAND="${1:-all}"

case "$SUBCOMMAND" in
    deps)
        echo "  Intel x86: no extra pip dependencies required"
        # Intel-specific requirements file if it exists
        if [ -f "${PROJECT_ROOT}/requirements-intel.txt" ]; then
            pip install -r "${PROJECT_ROOT}/requirements-intel.txt" --quiet
            echo "  Intel-specific requirements installed"
        fi
        ;;

    permissions)
        echo "  Setting up RAPL permissions..."
        if [ -f "${PROJECT_ROOT}/scripts/fix_permissions.sh" ]; then
            sudo bash "${PROJECT_ROOT}/scripts/fix_permissions.sh"
            echo "  Permissions configured"
        else
            echo "  WARNING: fix_permissions.sh not found"
        fi
        ;;

    models)
        echo "  Model setup for Intel x86..."
        echo ""
        echo "  UBUNTU2505 uses nvidia_nim (cloud) as primary provider."
        echo "  Set API key in core/.env:"
        echo "    NVIDIA_NIM_API_KEY=your-key-here"
        echo ""
        echo "  Test with:"
        echo "    python -m core.execution.tests.test_llm_setup --provider cloud --verbose"
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
