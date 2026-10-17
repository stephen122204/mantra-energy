#!/usr/bin/env bash
# Mac side: copy the tested commit and public SWE-bench rows to the node, then run setup there.
# Usage: bash studies/paper2/cohort/node/launch.sh <node-ip> [swev-raw-dir]
set -euo pipefail
IP="${1:?usage: launch.sh <node-ip> [swev-raw-dir]}"
RAW="${2:-}"
ROOT="$(git rev-parse --show-toplevel)"
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
test -z "$(git -C "$ROOT" status --porcelain)" || { echo "commit or stash changes first"; exit 1; }
TMP="$(mktemp -d)"
git -C "$ROOT" bundle create "$TMP/repo.bundle" HEAD "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
ssh -o StrictHostKeyChecking=accept-new "cc@$IP" 'mkdir -p ~/paper2/swev-raw'
scp -q "$TMP/repo.bundle" "$ROOT/studies/paper2/cohort/node/setup_node.sh" "cc@$IP:paper2/"
if [ -n "$RAW" ]; then scp -q "$RAW"/swev_*.json "cc@$IP:paper2/swev-raw/"; fi
ssh "cc@$IP" "cd ~/paper2 && nohup bash setup_node.sh $COMMIT ~/paper2/repo.bundle > ~/paper2/setup.log 2>&1 &"
echo "setup started for $COMMIT; follow: ssh cc@$IP tail -f ~/paper2/setup.log"
