#!/usr/bin/env bash
# LIQID05 only. Stephen runs this with sudo; Claude does not.
#   sudo bash freq-limit.sh status     # read-only
#   sudo bash freq-limit.sh apply      # performance governor on the worker CCD only
#   sudo bash freq-limit.sh restore    # put back exactly the saved governors
# Purpose: controlled intervention for explanation X2 (utilization-driven frequency policy), with
# C-states untouched, so it can be crossed with idle-limit.sh (X1) in a 2x2.
# Scope: cpufreq policies of CPUs 64-71 and SMT siblings 192-199 (one CCD). Nothing else is changed.
# Persists until restore or reboot. Refuses to apply if a save file already exists.
set -euo pipefail
CPUS="64 65 66 67 68 69 70 71 192 193 194 195 196 197 198 199"
SAVE=/root/alems-freq-restore-$(date +%Y%m%d).txt
pol() { echo /sys/devices/system/cpu/cpu$1/cpufreq; }
case "${1:-status}" in
  status)
    echo "driver=$(cat $(pol 64)/scaling_driver) boost=$(cat /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || echo n/a)"
    for c in $CPUS; do echo "cpu$c gov=$(cat $(pol $c)/scaling_governor) min=$(cat $(pol $c)/scaling_min_freq) max=$(cat $(pol $c)/scaling_max_freq) cur=$(cat $(pol $c)/scaling_cur_freq)"; done ;;
  apply)
    ls /root/alems-freq-restore-*.txt >/dev/null 2>&1 && { echo "restore file exists; run restore first"; exit 1; }
    grep -qw performance $(pol 64)/scaling_available_governors || { echo "performance governor unavailable"; exit 1; }
    for c in $CPUS; do echo "$c $(cat $(pol $c)/scaling_governor)" >> "$SAVE"; done
    for c in $CPUS; do echo performance > $(pol $c)/scaling_governor; done
    for c in $CPUS; do [ "$(cat $(pol $c)/scaling_governor)" = performance ] || { echo "readback failed cpu$c"; exit 1; }; done
    echo "applied; saved prior governors in $SAVE" ;;
  restore)
    F=$(ls /root/alems-freq-restore-*.txt | head -1)
    while read -r c g; do echo "$g" > $(pol $c)/scaling_governor; done < "$F"
    while read -r c g; do [ "$(cat $(pol $c)/scaling_governor)" = "$g" ] || { echo "restore readback failed cpu$c"; exit 1; }; done < "$F"
    mv "$F" "$F.restored"; echo "restored from $F" ;;
  *) echo "usage: status|apply|restore"; exit 2 ;;
esac
