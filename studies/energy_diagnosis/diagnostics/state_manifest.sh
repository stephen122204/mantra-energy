#!/usr/bin/env bash
# Read-only host and GPU state for a measurement block: CPU frequency policy per CPU (governor,
# driver, EPP, boost, idle-state flags), NUMA layout, GPU power limit, persistence mode, clocks,
# PCIe link, and IRQ counts per CPU. Prints JSON-ish sections; run before and after each block.
set -u
echo "## time_utc $(date -u +%FT%TZ)"
echo "## kernel $(uname -r)"
echo "## numa"; lscpu | grep -i -E "^NUMA|Socket|Model name|Thread|Core"
bus=$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader | head -1 | tr 'A-F' 'a-f'); bus="0000:${bus: -7}"
echo "## gpu_pci $bus numa_node $(cat /sys/bus/pci/devices/$bus/numa_node 2>/dev/null || echo NA)"
echo "## cpufreq (value: cpus)"
for f in scaling_driver scaling_governor energy_performance_preference scaling_min_freq scaling_max_freq; do
  for c in /sys/devices/system/cpu/cpu[0-9]*; do printf '%s %s\n' "$(cat $c/cpufreq/$f 2>/dev/null || echo NA)" "${c##*cpu}"; done |
    sort -k1,1 -k2,2n | awk -v f=$f '{a[$1]=a[$1]","$2} END{for(k in a) print f": "k" -> "substr(a[k],2)}'
done
echo "## boost $(cat /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || echo NA)"
echo "## cpuidle_disabled_states"
for c in /sys/devices/system/cpu/cpu[0-9]*; do for s in $c/cpuidle/state*; do [ "$(cat $s/disable 2>/dev/null)" = 1 ] && echo "${c##*cpu} $(cat $s/name)"; done; done | head -50
echo "## gpu"
nvidia-smi --query-gpu=name,uuid,driver_version,persistence_mode,power.limit,power.default_limit,enforced.power.limit,clocks.sm,clocks.mem,clocks.max.sm,clocks_event_reasons.active,pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max,temperature.gpu,power.draw --format=csv
echo "## irq_per_cpu_total"
awk 'NR==1{n=NF; next} {for(i=2;i<=n+1;i++) if($i ~ /^[0-9]+$/) s[i-2]+=$i} END{for(i=0;i<n;i++) printf "%d:%d ", i, s[i]; print ""}' /proc/interrupts
echo "## meminfo"; grep -E "MemTotal|MemAvailable|Cached|HugePages_Total|Shmem:" /proc/meminfo
echo "## numastat"; numastat -m 2>/dev/null | grep -E "MemFree|FilePages|Shmem" || true
