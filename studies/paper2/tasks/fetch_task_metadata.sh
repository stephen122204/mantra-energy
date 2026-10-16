#!/usr/bin/env bash
# Download the public task metadata that build_manifests.py reads (no harnesses, no Docker images).
# Usage: bash fetch_task_metadata.sh OUT_DIR   then   python3 -I build_manifests.py OUT_DIR manifests
# Needs curl and gh (GitHub CLI, for the Terminal-Bench 2 file tree).
set -euo pipefail
out="${1:?usage: fetch_task_metadata.sh OUT_DIR}"; mkdir -p "$out/tb2_toml"; cd "$out"
TAU2=96a3ef92329baf908ffe9dfe188cea34e8701d2a
TB2=2fd12b88aafdd04a52c298e3940bcb189f9766d6
AIDER=7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f
SWEV_SHA=c104f840cc67f8b6eec6f759ebc8b2693d585d4a
hf="https://datasets-server.huggingface.co/rows"

# The rows API serves the current dataset revision; refuse silently changed data.
now=$(curl -sf https://huggingface.co/api/datasets/princeton-nlp/SWE-bench_Verified | python3 -I -c 'import json,sys;print(json.load(sys.stdin)["sha"])')
[ "$now" = "$SWEV_SHA" ] || { echo "SWE-bench Verified revision changed: $now (manifest built at $SWEV_SHA)"; exit 1; }
for off in 0 100 200 300 400; do
  curl -sf "$hf?dataset=princeton-nlp/SWE-bench_Verified&config=default&split=test&offset=$off&length=100" -o "swev_$off.json"
done
for ds in MathArena/aime_2025 MathArena/hmmt_feb_2025; do
  curl -sf "$hf?dataset=$ds&config=default&split=train&offset=0&length=100" -o "$(echo "$ds" | tr / _).json"
done
for dom in airline retail telecom; do for f in tasks.json split_tasks.json; do
  curl -sf "https://raw.githubusercontent.com/sierra-research/tau2-bench/$TAU2/data/tau2/domains/$dom/$f" -o "tau2_${dom}_$f"
done; done
gh api "repos/harbor-framework/terminal-bench-2/git/trees/$TB2?recursive=1" \
  | python3 -I -c 'import json,sys;print("\n".join(x["path"] for x in json.load(sys.stdin)["tree"] if x["path"].endswith("/task.toml")))' \
  | while read -r p; do curl -sf "https://raw.githubusercontent.com/harbor-framework/terminal-bench-2/$TB2/$p" -o "tb2_toml/${p%/task.toml}.toml"; done
gh api "repos/Aider-AI/polyglot-benchmark/git/trees/$AIDER?recursive=1" -q '.tree[].path' \
  | grep -E '^[a-z]+/exercises/practice/[^/]+$' > aider_exercises.txt
echo "metadata in $out"
