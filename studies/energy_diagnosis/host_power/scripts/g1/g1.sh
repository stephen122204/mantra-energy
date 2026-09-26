#!/usr/bin/env bash
# G1 block (design and analysis fixed before data collection). LIQID05, user cc, no root. Precondition: Stephen ran `sudo bash power-swap.sh apply`.
# F' = CCD 72-79 performance | D' = CCD 80-87 default | N = CCD 96-103 default (null).
# Launch: setsid -f bash g1.sh > g1.log 2>&1 < /dev/null   -- and nobody logs in during W1.
set -u
BASE=/home/cc/alems-work; S=$BASE/stock-stacks; HP=$BASE/hostpower; OUT=$HP/g1; V=/dev/shm/hp-venv
REPO=$BASE/affinity-repo-20260924; ART=$BASE/artifacts/resume-preparation-20260924; PY=$BASE/study-env/bin/python
export VLLM_CACHE_ROOT=/dev/shm/hp-vllm-cache HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
mkdir -p "$OUT/w1" "$OUT/w2" "$OUT/w3"
declare -A SET=([F]=72-79 [D]=80-87 [N]=96-103)
check() {
  local bad=0
  for c in $(seq 72 79) $(seq 200 207); do [ "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor)" = performance ] || { echo "GOV_WRONG cpu$c"; bad=1; }; done
  for c in $(seq 80 87) $(seq 208 215) $(seq 96 103) $(seq 224 231); do [ "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor)" = schedutil ] || { echo "GOV_WRONG cpu$c"; bad=1; }; done
  for c in $(seq 72 87) $(seq 96 103) $(seq 200 215) $(seq 224 231); do [ "$(cat /sys/devices/system/cpu/cpu$c/cpuidle/state2/disable)" = 0 ] || { echo "IDLE_WRONG cpu$c"; bad=1; }; done
  echo "KNOBS_$1 bad=$bad $(date -u +%T)"; return $bad
}
check start || exit 4
# ---------------- W1: MoE-Infinity, guarded, no external sampler ----------------
cd "$REPO" || exit 2; export PYTHONPATH="$REPO"
{ git rev-parse HEAD; git status --porcelain; } > "$OUT/revision.txt"
COMMON=(--mode native --config "$ART/config.json" --backend-python "$BASE/backend-eviction-env/bin/python"
  --allocation-id alems-team-liqid05-20260920 --isolation "Host power G1: CCD swap (F' 72-79 performance, D' 80-87 default); warmed page cache protocol; not evaluation"
  --deadline 1500 --max-turns 12 --max-tool-calls 24 --max-total-output-tokens 8192 --max-tokens 2048
  --max-runs 1 --repeats 1 --task-pack "$ART/etl-dev.json" --task etl-latest-v2-n1000000-s103)
warm() { find $BASE/qwen3-30b-a3b-instruct-2507 $BASE/moe-offload -type f -print0 | xargs -0 cat > /dev/null; }
stage() {  # NAME COND
  local NAME=$1 C=$2 W=$OUT/w1
  warm; bash "$HP/g1/snapshot.sh" > "$W/$NAME.snap-before.txt" 2>&1
  env -u PYTHONPATH PYTHONPATH="$REPO" "$PY" "$BASE/prefetch-controls-tools/stage.py" "$W/$NAME" 1700 "$PY" -m studies.energy_diagnosis.moe.run "${COMMON[@]}" \
    --output "$W/$NAME/campaign" --policies demand --byte-budget 0 --preparation-timing during --cpu-affinity "${SET[$C]}"
  local RC=$?
  bash "$HP/g1/snapshot.sh" > "$W/$NAME.snap-after.txt" 2>&1
  "$PY" -m studies.energy_diagnosis.moe.audit_pilot "$W/$NAME" --prefix-mode exact_prefix --require-token-timing \
    --required-domain PACKAGE_SOCKET_0 --required-domain PACKAGE_SOCKET_1 --required-domain GPU_BOARD_0 --output "$W/$NAME-acceptance.json" > /dev/null 2>&1
  echo "STAGE_DONE $NAME rc=$RC acceptance=$(grep -o '"smoke_passed": *[a-z]*' "$W/$NAME-acceptance.json" 2>/dev/null) $(date -u +%T)"
}
slot() { local a; for a in 1 2; do stage "$1a$a" "$2"; grep -q '"smoke_passed": true' "$OUT/w1/$1a$a-acceptance.json" 2>/dev/null && return; done; }
slot F1 F; slot D1 D; slot D2 D; slot F2 F; slot F3 F; slot D3 D
echo "W1_DONE $(date -u +%T)"
# ---------------- W2/W3: stock stacks, sampler on ----------------
cd "$HP" || exit 2
exec 9>"$BASE/gpu.lock"; flock -n 9 || echo "GPU_LOCK_BUSY"
taskset -c 30 "$V/bin/python" "$HP/g1/sampler.py" "$OUT/sampler.jsonl" --cpus 72-87,96-103,200-215,224-231 &
SAMP=$!
Q30=$BASE/qwen3-30b-a3b-instruct-2507; Q17=$S/models/Qwen3-1.7B
serve_run() {  # STACK COND REP N WARM READY_S -- server argv...
  local STACK=$1 C=$2 R=$3 N=$4 WM=$5 RS=$6; shift 6
  local O=$OUT/w2/$STACK/$C$R PIN=(taskset -c "${SET[$C]}") i; mkdir -p "$O"
  bash "$HP/g1/snapshot.sh" > "$O/snap-before.txt" 2>&1
  setsid "${PIN[@]}" "$@" > "$O/server.log" 2>&1 &
  local SRV=$!
  for i in $(seq 1 "$RS"); do curl -sf http://127.0.0.1:8199/v1/models > /dev/null && break; kill -0 $SRV 2>/dev/null || break; sleep 1; done
  echo "ready_after_s $i" > "$O/ready.txt"
  local CL=llama; case $STACK in vllm*) CL=vllm ;; esac
  "${PIN[@]}" python3 "$HP/g1/serve_client.py" "$CL" http://127.0.0.1:8199 m "$HP/g1/prompt.txt" "$O/result.json" --n "$N" --warm "$WM" > "$O/client.log" 2>&1
  echo "client_rc $?" >> "$O/ready.txt"
  kill -TERM -- "-$SRV"; wait "$SRV" 2>/dev/null
  for i in $(seq 1 120); do [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ] && break; sleep 1; done
  bash "$HP/g1/snapshot.sh" > "$O/snap-after.txt" 2>&1
  echo "RUN_DONE $STACK $C$R $(date -u +%T) $(tail -1 "$O/client.log" | cut -c1-80)"
}
hf_run() {  # COND REP
  local O=$OUT/w2/hf_eager/$1$2; mkdir -p "$O"
  bash "$HP/g1/snapshot.sh" > "$O/snap-before.txt" 2>&1
  taskset -c "${SET[$1]}" "$V/bin/python" "$HP/g1/hf_decode.py" "$Q17" "$HP/g1/prompt.txt" "$O/result.json" > "$O/log.txt" 2>&1; echo "rc $?" >> "$O/log.txt"
  bash "$HP/g1/snapshot.sh" > "$O/snap-after.txt" 2>&1
  echo "RUN_DONE hf_eager $1$2 $(date -u +%T) $(tail -2 "$O/log.txt" | tr '\n' ' ' | cut -c1-80)"
}
VL=("$V/bin/vllm" serve)
three() { local f=$1; $f F 1; $f D 1; $f N 1; $f D 2; $f N 2; $f F 2; $f N 3; $f F 3; $f D 3; }
two() { local f=$1; $f F 1; $f D 1; $f D 2; $f F 2; $f F 3; $f D 3; }
s_llamamoe_default() { serve_run llamamoe_default $1 $2 512 64 300 "$S/llama.cpp/build/bin/llama-server" -m "$S/models/OLMoE-1B-7B-0125-Instruct-Q4_K_M.gguf" -ngl 99 --n-cpu-moe 99 -t 8 --poll 50 -c 4096 -np 1 --port 8199 --alias m; }
s_llamamoe_passive() { serve_run llamamoe_passive $1 $2 512 64 300 env OMP_WAIT_POLICY=PASSIVE "$S/llama.cpp/build/bin/llama-server" -m "$S/models/OLMoE-1B-7B-0125-Instruct-Q4_K_M.gguf" -ngl 99 --n-cpu-moe 99 -t 8 -c 4096 -np 1 --port 8199 --alias m; }
s_llama_gpu()    { serve_run llama_gpu $1 $2 512 64 300 "$S/llama.cpp/build/bin/llama-server" -m "$S/models/Qwen3-1.7B-Q8_0.gguf" -ngl 99 -t 8 -c 4096 -np 1 --port 8199 --alias m; }
s_vllm_mem()     { serve_run vllm_mem $1 $2 512 64 900 "${VL[@]}" "$Q17" --port 8199 --served-model-name m --max-model-len 4096 --gpu-memory-utilization 0.85 --max-num-seqs 1; }
s_vllm_offload() { serve_run vllm_offload $1 $2 128 16 1500 "${VL[@]}" "$Q30" --port 8199 --served-model-name m --max-model-len 4096 --gpu-memory-utilization 0.90 --max-num-seqs 1 --cpu-offload-gb 24; }
s_hf_eager()     { hf_run $1 $2; }
three s_llamamoe_passive; three s_llamamoe_default; three s_hf_eager
two s_llama_gpu; two s_vllm_mem; two s_vllm_offload
# W3
for r in 1 2 3; do for m in spin1 block1 chain2 chain4; do for C in F D; do
  taskset -c "${SET[$C]}" "$V/bin/python" "$HP/g1/handoff_bench.py" --mode $m --tokens 200 --warmup 20 --out "$OUT/w3/$m-$C-r$r.json" > "$OUT/w3/$m-$C-r$r.log" 2>&1
  echo "BENCH_DONE $m $C r$r rc=$? $(date -u +%T)"
done; done; done
kill "$SAMP"; wait "$SAMP" 2>/dev/null
check end
echo G1_DONE $(date -u +%T)
