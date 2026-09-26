#!/usr/bin/env bash
# LIQID05 only. Stephen runs with sudo; Claude does not.   sudo bash power-swap.sh status|apply|restore
# CCD-swap control for G0: performance governor on CCD 72-79 (+200-207), which was G0's default group.
# CCD 80-87 (+208-215; G0's performance group) and CCD 96-103 (+224-231; null control) stay default.
# Idle states are not touched. Saves prior governors to /root; restores with readback; refuses if any save exists.
set -euo pipefail
F="72 73 74 75 76 77 78 79 200 201 202 203 204 205 206 207"
CHECK="$F 80 81 82 83 84 85 86 87 208 209 210 211 212 213 214 215 96 97 98 99 100 101 102 103 224 225 226 227 228 229 230 231"
SAVE=/root/alems-powerswap-restore.txt
gov() { echo /sys/devices/system/cpu/cpu$1/cpufreq/scaling_governor; }
idl() { echo /sys/devices/system/cpu/cpu$1/cpuidle/state2/disable; }
case "${1:-status}" in
  status) for c in $CHECK; do echo "cpu$c gov=$(cat $(gov $c)) c2disable=$(cat $(idl $c))"; done ;;
  apply)
    ls /root/alems-*restore*.txt 2>/dev/null | grep -v '\.restored' | grep -q . && { echo "a restore file exists; restore first"; exit 1; }
    for c in $CHECK; do [ "$(cat $(gov $c))" = schedutil ] && [ "$(cat $(idl $c))" = 0 ] || { echo "cpu$c not at default; refusing"; exit 1; }; done
    for c in $F; do echo "$c $(cat $(gov $c))" >> "$SAVE"; done
    for c in $F; do echo performance > $(gov $c); done
    for c in $F; do [ "$(cat $(gov $c))" = performance ] || { echo "readback failed cpu$c"; exit 1; }; done
    echo "applied; saved in $SAVE" ;;
  restore)
    while read -r c g; do echo "$g" > $(gov $c); done < "$SAVE"
    while read -r c g; do [ "$(cat $(gov $c))" = "$g" ] || { echo "restore readback failed cpu$c"; exit 1; }; done < "$SAVE"
    mv "$SAVE" "$SAVE.restored.$(date +%s)"; echo restored ;;
  *) echo "usage: status|apply|restore"; exit 2 ;;
esac
