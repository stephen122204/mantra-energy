#!/usr/bin/env bash
# G0 gate block (host-power study). Runs on LIQID05 as cc, no root. Precondition: Stephen ran
# `sudo bash power-2x2.sh apply` (D 72-79 default | I 64-71 C2 off | F 80-87 performance | X=IF 88-95 both).
# W1: MoE-Infinity, C1 stage protocol unchanged (stage.py + moe.run native demand, same task/config/backend,
#     checkout affinity-repo-20260924), only --cpu-affinity differs: D 72-79, F 80-87, X 88-95. Latin square.
# W2: llama-server Qwen3-1.7B Q8_0 (GPU) and OLMoE-1B-7B Q4_K_M (--n-cpu-moe 99 -t 8 --poll 50), whole server +
#     client pinned to the condition's CCD, warm-up 64 + 3 x 512 forced tokens. Latin square.
# Nobody logs in while this runs. Launch: setsid nohup bash g0.sh > g0.log 2>&1 &
set -u
BASE=/home/cc/alems-work; S=$BASE/stock-stacks; HP=$BASE/hostpower; OUT=$HP/g0
REPO=$BASE/affinity-repo-20260924; ART=$BASE/artifacts/resume-preparation-20260924; PY=$BASE/study-env/bin/python
mkdir -p "$OUT/w1" "$OUT/w2"
# Re-run of the invalid slots F1 and D3 (guard aborted both at start: background CPU budget, from sampler.py /proc scan).
declare -A SET=([D]=72-79 [F]=80-87 [X]=88-95)
check() {  # $1 = start|end
  local bad=0
  for c in $(seq 80 95) $(seq 208 223); do [ "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor)" = performance ] || { echo "GOV_WRONG cpu$c"; bad=1; }; done
  for c in $(seq 72 79) $(seq 200 207) $(seq 64 71) $(seq 192 199); do [ "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor)" = schedutil ] || { echo "GOV_WRONG cpu$c"; bad=1; }; done
  for c in $(seq 64 71) $(seq 192 199) $(seq 88 95) $(seq 216 223); do [ "$(cat /sys/devices/system/cpu/cpu$c/cpuidle/state2/disable)" = 1 ] || { echo "IDLE_WRONG cpu$c"; bad=1; }; done
  for c in $(seq 72 87) $(seq 200 215); do [ "$(cat /sys/devices/system/cpu/cpu$c/cpuidle/state2/disable)" = 0 ] || { echo "IDLE_WRONG cpu$c"; bad=1; }; done
  echo "KNOBS_$1 bad=$bad"; return $bad
}
check start || exit 4
cd "$REPO" || exit 2; export PYTHONPATH="$REPO"
{ git rev-parse HEAD; git status --porcelain; } > "$OUT/revision.txt"
taskset -c 30 python3 "$HP/sampler.py" "$OUT/sampler-rerun.jsonl" --cpus 64-95,192-223 &
SAMP=$!
COMMON=(--mode native --config "$ART/config.json" --backend-python "$BASE/backend-eviction-env/bin/python"
  --allocation-id alems-team-liqid05-20260920 --isolation 'Host power G0: governor x idle per CCD (D 72-79 default, F 80-87 performance, X 88-95 both); warmed page cache protocol; not evaluation'
  --deadline 1500 --max-turns 12 --max-tool-calls 24 --max-total-output-tokens 8192 --max-tokens 2048
  --max-runs 1 --repeats 1 --task-pack "$ART/etl-dev.json" --task etl-latest-v2-n1000000-s103)
warm() { find $BASE/qwen3-30b-a3b-instruct-2507 $BASE/moe-offload -type f -print0 | xargs -0 cat > /dev/null; }
stage() {  # NAME COND
  local NAME=$1 C=$2 W=$OUT/w1
  warm
  bash "$HP/snapshot.sh" > "$W/$NAME.snap-before.txt" 2>&1
  "$PY" "$BASE/prefetch-controls-tools/stage.py" "$W/$NAME" 1700 "$PY" -m studies.energy_diagnosis.moe.run "${COMMON[@]}" \
    --output "$W/$NAME/campaign" --policies demand --byte-budget 0 --preparation-timing during --cpu-affinity "${SET[$C]}"
  local RC=$?
  bash "$HP/snapshot.sh" > "$W/$NAME.snap-after.txt" 2>&1
  "$PY" -m studies.energy_diagnosis.moe.audit_pilot "$W/$NAME" --prefix-mode exact_prefix --require-token-timing \
    --required-domain PACKAGE_SOCKET_0 --required-domain PACKAGE_SOCKET_1 --required-domain GPU_BOARD_0 \
    --output "$W/$NAME-acceptance.json" > /dev/null 2>&1
  echo "STAGE_DONE $NAME rc=$RC acceptance=$("$PY" -c "import json;print(json.load(open('$W/$NAME-acceptance.json'))['smoke_passed'])" 2>/dev/null) $(date -u +%T)"
}
w2run() {  # STACK COND REP
  local STACK=$1 C=$2 R=$3 O=$OUT/w2/$1/$2$3
  mkdir -p "$O"
  local PIN=(taskset -c "${SET[$C]}")
  local ARGS
  case $STACK in
    llama) ARGS=(-m "$S/models/Qwen3-1.7B-Q8_0.gguf" -ngl 99 -c 4096 -np 1 --port 8199 --alias m) ;;
    llamamoe) ARGS=(-m "$S/models/OLMoE-1B-7B-0125-Instruct-Q4_K_M.gguf" -ngl 99 --n-cpu-moe 99 -t 8 --poll 50 -c 4096 -np 1 --port 8199 --alias m) ;;
  esac
  bash "$HP/snapshot.sh" > "$O/snap-before.txt" 2>&1
  setsid "${PIN[@]}" "$S/llama.cpp/build/bin/llama-server" "${ARGS[@]}" > "$O/server.log" 2>&1 &
  local SRV=$! i
  for i in $(seq 1 300); do curl -sf http://127.0.0.1:8199/health > /dev/null && break; sleep 1; done
  echo "ready_after_s $i" > "$O/ready.txt"
  "${PIN[@]}" python3 "$HP/serve_client.py" "$STACK" http://127.0.0.1:8199 m "$HP/prompt.txt" "$O/result.json" > "$O/client.log" 2>&1
  echo "client_rc $?" >> "$O/ready.txt"
  kill -TERM -- "-$SRV"; wait "$SRV" 2>/dev/null
  for i in $(seq 1 60); do [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ] && break; sleep 1; done
  bash "$HP/snapshot.sh" > "$O/snap-after.txt" 2>&1
  echo "RUN_DONE $STACK $C$R $(date -u +%T)"
}
for SL in "F1r F" "D3r D"; do
  set -- $SL
  for a in 1 2 3; do
    stage "$1a$a" "$2"
    grep -q '"smoke_passed": true' "$OUT/w1/$1a$a-acceptance.json" 2>/dev/null && break
  done
done
kill "$SAMP"; wait "$SAMP" 2>/dev/null
check end
echo RERUN_DONE $(date -u +%T)
