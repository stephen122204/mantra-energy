#!/usr/bin/env bash
# vLLM CPU-offload comparison block. LIQID05, default governor, no knobs. vLLM engine via adapter checkout 7180f77.
#   bash run_block.sh smoke    -> one feasibility goal (excluded from analysis)
#   bash run_block.sh block    -> n=3 guarded goals + 1 profiled goal
set -u
BASE=/home/cc/alems-work; HP=$BASE/hostpower; CA=$HP/ca; OUT=$CA/${1:-smoke}
REPO=$HP/vllm-repo; ART=$BASE/artifacts/resume-preparation-20260924; PY=$BASE/study-env/bin/python; V=/dev/shm/hp-venv
export VLLM_CACHE_ROOT=/dev/shm/hp-vllm-cache HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
mkdir -p "$OUT"
for c in $(seq 0 255); do [ "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor)" = schedutil ] && [ "$(cat /sys/devices/system/cpu/cpu$c/cpuidle/state2/disable)" = 0 ] || { echo "KNOB_NOT_DEFAULT cpu$c"; exit 4; }; done
echo "KNOBS_default_verified $(date -u +%T)"
cd "$REPO" || exit 2; export PYTHONPATH="$REPO"
{ git rev-parse HEAD; git status --porcelain; } > "$OUT/revision.txt"
warm() { find $BASE/qwen3-30b-a3b-instruct-2507 -type f -print0 | xargs -0 cat > /dev/null; }
stage() {  # NAME CONFIG
  local NAME=$1 CFG=$2
  warm; bash "$HP/g1/snapshot.sh" > "$OUT/$NAME.snap-before.txt" 2>&1
  "$PY" "$BASE/prefetch-controls-tools/stage.py" "$OUT/$NAME" 1700 "$PY" -m studies.energy_diagnosis.moe.run --mode native \
    --config "$CFG" --backend-python "$V/bin/python" --allocation-id alems-team-liqid05-20260920 \
    --isolation "vLLM CPU-offload comparison engine on the G1 ETL task (default governor, CCD 80-87); warmed page cache protocol; not evaluation" \
    --deadline 1500 --max-turns 12 --max-tool-calls 24 --max-total-output-tokens 8192 --max-tokens 2048 --max-runs 1 --repeats 1 \
    --task-pack "$ART/etl-dev.json" --task etl-latest-v2-n1000000-s103 --output "$OUT/$NAME/campaign" --policies demand \
    --byte-budget 0 --preparation-timing during --cpu-affinity 80-87
  local RC=$?
  bash "$HP/g1/snapshot.sh" > "$OUT/$NAME.snap-after.txt" 2>&1
  "$PY" -m studies.energy_diagnosis.moe.audit_pilot "$OUT/$NAME" --prefix-mode exact_prefix --require-token-timing \
    --required-domain PACKAGE_SOCKET_0 --required-domain PACKAGE_SOCKET_1 --required-domain GPU_BOARD_0 --output "$OUT/$NAME-acceptance.json" > /dev/null 2>&1
  echo "STAGE_DONE $NAME rc=$RC acceptance=$(grep -o '"smoke_passed": *[a-z]*' "$OUT/$NAME-acceptance.json" 2>/dev/null) $(date -u +%T)"
}
case "${1:-smoke}" in
  smoke) stage S1 "$CA/config-vllm.json" ;;
  block) stage V1 "$CA/config-vllm.json"; stage V2 "$CA/config-vllm.json"; stage V3 "$CA/config-vllm.json"; stage P1 "$CA/config-vllm-profile.json" ;;
esac
echo "GA_DONE ${1:-smoke} $(date -u +%T)"
