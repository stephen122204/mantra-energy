#!/usr/bin/env bash
# Read-only node state snapshot (no root). Recorded before/after every run and block.
date -u +%FT%T.%NZ; echo "monotonic_ns $(python3 -c 'import time;print(time.monotonic_ns())')"
echo "## who"; who
echo "## uptime"; uptime
echo "## df"; df -h / "$HOME"
echo "## nvidia-smi"; nvidia-smi --query-gpu=name,memory.used,utilization.gpu,power.draw,pstate --format=csv
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
echo "## governor 72-103"; for c in $(seq 72 103); do printf "%s " "$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_governor 2>/dev/null)"; done; echo
echo "## cpuidle state2 (C2) cpu name disable usage time_us"
for c in $(seq 72 87) $(seq 96 103) $(seq 200 215) $(seq 224 231) 0 1 2 30; do
  d=/sys/devices/system/cpu/cpu$c/cpuidle/state2
  echo "cpu$c $(cat $d/name) $(cat $d/disable) $(cat $d/usage) $(cat $d/time)"
done
echo "## top processes by cpu"; ps -eo pid,user,psr,pcpu,etimes,comm --sort=-pcpu | head -15
