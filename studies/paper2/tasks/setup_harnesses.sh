#!/usr/bin/env bash
# Node setup for the benchmark harnesses at the pinned commits (run by a person on the GPU node).
# NOT YET RUN. Each harness's own README is authoritative for its install; check before the first live run.
# Usage: bash setup_harnesses.sh [DIR]   (default ~/paper2-bench)
set -euo pipefail
W="${1:-$HOME/paper2-bench}"; mkdir -p "$W"; cd "$W"
pin() { [ -d "$2" ] || git clone -q "https://github.com/$1.git" "$2"; git -C "$2" checkout -q "$3"; echo "$1 $(git -C "$2" rev-parse HEAD)" >> pins.txt; }
: > pins.txt
pin sierra-research/tau2-bench      tau2-bench          96a3ef92329baf908ffe9dfe188cea34e8701d2a
pin harbor-framework/terminal-bench-2 terminal-bench-2  2fd12b88aafdd04a52c298e3940bcb189f9766d6
pin Aider-AI/polyglot-benchmark     polyglot-benchmark  7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -e tau2-bench          # tau2 CLI (needs a separate user-simulator model endpoint)
venv/bin/pip install -q swebench               # SWE-bench evaluation harness (Docker required)
venv/bin/pip freeze > pip-freeze.txt
cat pins.txt
echo "SWE-bench images: pull only the instances in manifests/pilot_selection.json (about 85), not all 500."
