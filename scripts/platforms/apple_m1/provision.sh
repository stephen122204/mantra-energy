#!/usr/bin/env bash
# A-LEMS platform provisioning: Apple Silicon (M1/M2/M3)
# Called by install.sh with a subcommand: deps, permissions, models
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SUBCOMMAND="${1:-all}"

case "$SUBCOMMAND" in
    deps)
        echo "  Apple Silicon: installing system build dependencies..."
        if command -v brew &>/dev/null; then
            brew install libjpeg libxml2 libxslt freetype lcms2 webp 2>/dev/null || true
        else
            echo "  WARNING: Homebrew not found. Install from https://brew.sh"
            echo "  Then re-run: bash scripts/platforms/apple_m1/provision.sh deps"
            exit 1
        fi

        echo "  Installing Python dependencies..."
        pip install --upgrade pip --quiet
        pip install -r requirements.txt --quiet

        echo "  Installing llama-cpp-python with Metal backend..."
        CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python \
            --force-reinstall --no-cache-dir --quiet 2>&1 | tail -3
        python3 -c "from llama_cpp import Llama; print('  llama_cpp imported OK')" || \
            echo "  WARNING: llama_cpp import failed, Metal build may need Xcode CLI tools"
        ;;

    permissions)
        echo "  Setting up powermetrics sudoers rule..."
        if [ -f "${PROJECT_ROOT}/scripts/fix_permissions.sh" ]; then
            sudo bash "${PROJECT_ROOT}/scripts/fix_permissions.sh"
            # Verify non-interactive sudo works
            if sudo -n powermetrics --samplers cpu_power -n 1 -i 100 > /dev/null 2>&1; then
                echo "  Sudoers rule verified (non-interactive powermetrics OK)"
            else
                echo "  WARNING: sudoers rule may not be active, reopen terminal and retry"
            fi
        else
            echo "  WARNING: fix_permissions.sh not found"
        fi
        ;;

    models)
        echo "  Model setup for Apple Silicon..."
        echo ""
        echo "  Options:"
        echo "    A) Download a GGUF model (recommended for local inference):"
        echo "       mkdir -p ~/models"
        echo "       cd ~/models"
        echo "       wget https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
        echo ""
        echo "    B) Copy from another A-LEMS machine via scp"
        echo ""
        echo "    C) Cloud only (nvidia_nim): set API key in core/.env"
        echo ""
        echo "  After obtaining a model, update config/models.yaml local section"
        echo "  with the model path, then run:"
        echo "    python -m core.execution.tests.test_llm_setup --provider local --verbose"
        echo "  Look for 'ggml_metal_init' in output to confirm Metal backend."
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
