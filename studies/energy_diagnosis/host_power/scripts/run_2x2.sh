#!/usr/bin/env bash
# Runs on LIQID05 as cc (no root). Precondition: Stephen has run `sudo bash power-2x2.sh apply` and
# the status readback was checked. Usage: bash run_2x2.sh PYTHON OUTDIR [REPS]
# Conditions (placement = the knob): D 72-79 default | I 64-71 C2 off | F 80-87 performance | IF 88-95 both | U unpinned
set -uo pipefail
PY=$1; OUT=$2; REPS=${3:-3}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
declare -A CPUS=([D]=72-79 [I]=64-71 [F]=80-87 [IF]=88-95 [U]=)
MODES="spin1 block1 chain1 chain2 chain4"
# External 0.5 s frequency sampler on socket 0 (CPU 30), away from the measured CCDs.
taskset -c 30 bash -c 'while true; do printf "%s" "$(date +%s.%N)"; for c in $(seq 64 95); do printf " %s" "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_cur_freq)"; done; echo; sleep 0.5; done' > "$OUT/freq.txt" &
SAMP=$!
trap 'kill $SAMP 2>/dev/null' EXIT
{ date -u; who; uptime; nvidia-smi --query-gpu=name,utilization.gpu,memory.used --format=csv; } > "$OUT/snapshot-start.txt" 2>&1
ORDERS=("D I F IF U" "I F IF U D" "F IF U D I" "IF U D I F" "U D I F IF")
for r in $(seq 1 "$REPS"); do
  for m in $MODES; do
    for c in ${ORDERS[$(( (r - 1) % 5 ))]}; do
      name="$m-$c-r$r"
      if [ -n "${CPUS[$c]}" ]; then PIN="taskset -c ${CPUS[$c]}"; else PIN=""; fi
      $PIN "$PY" "$HERE/handoff_bench.py" --mode "$m" --tokens 200 --warmup 20 --out "$OUT/$name.json" > "$OUT/$name.log" 2>&1
      echo "$name rc=$? $(tail -c 300 "$OUT/$name.log" | tr '\n' ' ' | cut -c1-200)" >> "$OUT/progress.txt"
    done
  done
done
{ date -u; who; uptime; } > "$OUT/snapshot-end.txt" 2>&1
echo DONE >> "$OUT/progress.txt"
