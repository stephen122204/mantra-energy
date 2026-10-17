#!/usr/bin/env bash
# Node side: run every bound round of this node's shard, in order, resumable.
# Usage: bash run_campaign.sh <bound-dir> <lease-end-utc>      (W=$HOME/paper2 by default)
# A round whose result directory finished (SHA256SUMS written) is skipped. An interrupted round is
# rerun only with RETRY_REASON='infra: <cause>' (lost node, ssh, lease) into a new directory that
# records --retry-of; the interrupted directory is kept. Server start failures, server deaths,
# out-of-memory, timeouts and failed tasks are recorded inside a finished round and never rerun.
set -euo pipefail
BOUND="${1:?usage: run_campaign.sh <bound-dir> <lease-end-utc>}"
CUTOFF="${2:?usage: run_campaign.sh <bound-dir> <lease-end-utc>}"
W="${W:-$HOME/paper2}"
RR="${RETRY_REASON:-}"
END="$(date -u -d "$CUTOFF" +%s)" || { echo "cannot parse lease end '$CUTOFF' (GNU date)"; exit 1; }
RES="$W/campaign-results"
mkdir -p "$RES"
cd "$W/repo"
test -z "$(git status --porcelain)" || { echo "repo checkout is dirty"; exit 1; }
for plan in "$BOUND"/round-*.json; do
  r="$(basename "$plan" .json)"
  done_dir=""
  for d in "$RES/$r"-*; do [ -f "$d/SHA256SUMS" ] && done_dir="$d"; done
  if [ -n "$done_dir" ]; then echo "$r: done in $done_dir"; continue; fi
  prev="$(ls -d "$RES/$r"-* 2>/dev/null | grep -v '\.log$' | tail -1 || true)"
  if [ -n "$prev" ] && [ "$RR" = "${RR#infra:}" ]; then
    echo "$r was interrupted ($prev). Rerun only for an infrastructure cause: RETRY_REASON='infra: <cause>' bash $0 $*"
    exit 3
  fi
  out="$RES/$r-$(date -u +%Y%m%dT%H%M%SZ)"
  left=$(( END - $(date -u +%s) ))
  [ "$left" -gt 1800 ] || { echo "less than 30 min to lease end; stopping before $r"; exit 0; }
  echo "$r -> $out (${left}s to lease end)"
  "$W/venv/bin/python" -m studies.paper2.cohort.pilot --plan "$plan" --out "$out" --budget-s "$left" \
    --cutoff-utc "$CUTOFF" ${prev:+--retry-of "$prev" --retry-reason "$RR"} 2>&1 | tee "$out.log"
done
