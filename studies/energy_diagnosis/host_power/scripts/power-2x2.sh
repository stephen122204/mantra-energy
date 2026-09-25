#!/usr/bin/env bash
# LIQID05 only. Stephen runs this with sudo; Claude does not.
#   sudo bash power-2x2.sh status | apply | restore
# One root setup for a 2x2 of {idle cap} x {frequency policy} on four CCDs of the GPU-local socket (NUMA 1):
#   CCD-D  72-79  +200-207 : default (control)
#   CCD-I  64-71  +192-199 : C2 (deepest idle state) disabled, governor unchanged
#   CCD-F  80-87  +208-215 : performance governor, idle states unchanged
#   CCD-IF 88-95  +216-223 : both
# Saves every touched value to /root and restores exactly (with readback). Touches nothing else.
set -euo pipefail
I="64 65 66 67 68 69 70 71 192 193 194 195 196 197 198 199"
F="80 81 82 83 84 85 86 87 208 209 210 211 212 213 214 215"
IF="88 89 90 91 92 93 94 95 216 217 218 219 220 221 222 223"
D="72 73 74 75 76 77 78 79 200 201 202 203 204 205 206 207"
SAVE=/root/alems-power2x2-restore.txt
idle() { echo /sys/devices/system/cpu/cpu$1/cpuidle/state2; }
gov() { echo /sys/devices/system/cpu/cpu$1/cpufreq/scaling_governor; }
case "${1:-status}" in
  status)
    echo "idle_driver=$(cat /sys/devices/system/cpu/cpuidle/current_driver) freq_driver=$(cat /sys/devices/system/cpu/cpu64/cpufreq/scaling_driver) govs=$(cat /sys/devices/system/cpu/cpu64/cpufreq/scaling_available_governors)"
    for c in $D $I $F $IF; do echo "cpu$c $(cat $(idle $c)/name) disable=$(cat $(idle $c)/disable) gov=$(cat $(gov $c))"; done ;;
  apply)
    [ -e "$SAVE" ] && { echo "restore file exists; run restore first"; exit 1; }
    ls /root/alems-idle-restore-*.txt >/dev/null 2>&1 && { echo "host-idle-check limit still applied; run its idle-limit.sh restore first"; exit 1; }
    ls /root/alems-freq-restore-*.txt >/dev/null 2>&1 && { echo "freq-limit.sh still applied; restore it first"; exit 1; }
    for c in $I $F $IF $D; do [ "$(cat $(idle $c)/disable)" = 0 ] || { echo "cpu$c C2 already disabled; refusing"; exit 1; }; done
    [ "$(cat /sys/devices/system/cpu/cpuidle/current_driver)" = acpi_idle ] || { echo "unexpected idle driver"; exit 1; }
    grep -qw performance /sys/devices/system/cpu/cpu80/cpufreq/scaling_available_governors || { echo "no performance governor"; exit 1; }
    for c in $I $IF; do [ "$(cat $(idle $c)/name)" = C2 ] || { echo "cpu$c state2 not C2"; exit 1; }; done
    for c in $I $F $IF $D; do echo "$c $(cat $(idle $c)/disable) $(cat $(gov $c))" >> "$SAVE"; done
    for c in $I $IF; do echo 1 > $(idle $c)/disable; done
    for c in $F $IF; do echo performance > $(gov $c); done
    for c in $I $IF; do [ "$(cat $(idle $c)/disable)" = 1 ] || { echo "idle readback failed cpu$c"; exit 1; }; done
    for c in $F $IF; do [ "$(cat $(gov $c))" = performance ] || { echo "gov readback failed cpu$c"; exit 1; }; done
    echo "applied; saved prior values in $SAVE" ;;
  restore)
    while read -r c v g; do echo "$v" > $(idle $c)/disable; echo "$g" > $(gov $c); done < "$SAVE"
    while read -r c v g; do [ "$(cat $(idle $c)/disable)" = "$v" ] && [ "$(cat $(gov $c))" = "$g" ] || { echo "restore readback failed cpu$c"; exit 1; }; done < "$SAVE"
    mv "$SAVE" "$SAVE.restored.$(date +%s)"; echo "restored" ;;
  *) echo "usage: status|apply|restore"; exit 2 ;;
esac
