# System Measurement Methodology

This document describes the methodology for all system-level measurements
in A-LEMS — performance counters, thermal sensors, CPU frequency, C-states,
scheduler statistics, memory, network, and wall clock timing.

---

## Performance Counter Methodology

### Overview

A-LEMS reads hardware performance counters via the Linux `perf_event_open`
syscall (syscall number 298 on x86_64). This provides cycle-accurate
instruction and cache statistics without process perturbation.

### Interface

```c
// Kernel interface
syscall(SYS_perf_event_open, &attr, pid, cpu, group_fd, flags)
```

A-LEMS wraps this via the `perf stat` command and the Python `perf_reader.py`
module. Counters are collected for the workload PID only, not system-wide.

### Metrics Captured

| Metric | Hardware Event | Description |
|--------|---------------|-------------|
| `instructions` | `PERF_COUNT_HW_INSTRUCTIONS` | Retired CPU instructions |
| `cycles` | `PERF_COUNT_HW_CPU_CYCLES` | CPU clock cycles |
| `cache_misses` | `PERF_COUNT_HW_CACHE_MISSES` | LLC load misses |
| `cache_references` | `PERF_COUNT_HW_CACHE_REFERENCES` | LLC load accesses |
| `page_faults` | Software event | Total page faults |
| `context_switches` | Software event | Process preemptions |
| `thread_migrations` | Software event | CPU migrations |

### Derived Metrics

$$IPC = \frac{N_{instructions}}{N_{cycles}}$$

$$\%_{miss} = \frac{N_{LLC\_miss}}{N_{LLC\_ref}} \times 100$$

### Platform Availability

| Platform | Available | Notes |
|----------|-----------|-------|
| Linux x86_64 | ✅ Yes | Requires `perf_event_paranoid` ≤ 1 |
| Linux aarch64 | ✅ Yes | ARM PMU events |
| macOS | ❌ No | kperf not exposed |

### Provenance

- **Provenance**: `MEASURED`
- **Method ID**: `perf_counters`
- **Confidence**: `1.0`

---

## Thermal Measurement

### Overview

CPU temperatures are read from the Linux sysfs thermal subsystem at 1Hz
by a dedicated thermal sampling thread running alongside the 100Hz energy
sampler.

### Interface

```
/sys/class/thermal/
    thermal_zone0/temp    ← millicelsius integer
    thermal_zone1/temp
    thermal_zoneN/temp
```

Temperature in Celsius:

$$T = \frac{\text{sysfs\_millicelsius}}{1000}$$

### Metrics Captured

| Metric | Description | Provenance |
|--------|-------------|------------|
| `package_temp_celsius` | CPU package temperature | MEASURED |
| `start_temp_c` | Temperature at experiment start | MEASURED |
| `max_temp_c` | Peak temperature during experiment | CALCULATED |
| `min_temp_c` | Minimum temperature during experiment | CALCULATED |
| `thermal_delta_c` | max - start temperature | CALCULATED |
| `baseline_temp_celsius` | Temperature during idle baseline | MEASURED |
| `thermal_during_experiment` | 1 if throttling occurred | CALCULATED |
| `thermal_now_active` | 1 if throttling active at end | CALCULATED |
| `thermal_since_boot` | 1 if any throttling since boot | CALCULATED |

### Throttling Detection

Thermal throttling is detected via MSR `0x19C` (IA32_THERM_STATUS):

```python
thermal_during_experiment = 1 if (
    end_pkg_throttle == 1 or end_core_throttle == 1
) else 0
```

### Provenance

- **Provenance**: `MEASURED` (raw temps) / `CALCULATED` (derived flags)
- **Method ID**: `thermal_sensor`
- **Confidence**: `1.0`

---

## C-State Measurement

### Overview

CPU C-states represent power-saving idle states. A-LEMS reads C-state
residency counters from MSRs to quantify time spent in each idle state.

### Interface

C-state counters are read via the `msr` kernel module:

| C-State | MSR Address | Description |
|---------|-------------|-------------|
| C2 | `0x60D` | Light sleep, fast wake |
| C3 | `0x3FC` | Deeper sleep |
| C6 | `0x3FD` | Deep power down |
| C7 | `0x3FE` | Enhanced deep power down |

### Calculation

$$C_x\text{\_time} = \frac{\Delta MSR_{C_x}}{TSC_{freq}}$$

Where $TSC_{freq}$ is the Time Stamp Counter frequency in Hz.

### Why C-States Matter

High C-state residency indicates the CPU is frequently idle between LLM
inference steps in agentic workflows — a signature of orchestration overhead.
Comparing C-state residency between linear and agentic runs quantifies
idle time introduced by agent coordination.

### Provenance

- **Provenance**: `MEASURED`
- **Method ID**: `msr_reader`
- **Confidence**: `1.0`

---

## Turbostat CPU Frequency Reader

### Overview

CPU frequency and utilisation are captured via Intel's `turbostat` tool,
which reads MSR registers for per-core frequency data at the configured
sampling interval.

### Interface

```bash
turbostat --interval 0.1 --show Avg_MHz,Busy%,Bzy_MHz,CoreTmp
```

A-LEMS runs turbostat as a subprocess at the same interval as RAPL sampling
(100ms = 10Hz) and parses the output into a DataFrame.

### Metrics Captured

| Metric | turbostat Column | Description |
|--------|-----------------|-------------|
| `frequency_mhz` | `Avg_MHz` | Average frequency across all cores |
| `cpu_busy_mhz` | `Bzy_MHz` | Frequency when CPU is busy |
| `cpu_avg_mhz` | `Avg_MHz` | Average frequency (same as above) |
| `ring_bus_freq_mhz` | `Ring_MHz` | Ring bus frequency |

### Provenance

- **Provenance**: `MEASURED` (raw) / `CALCULATED` (averages)
- **Method ID**: `turbostat_reader`
- **Confidence**: `1.0`

---

## OS Scheduler Measurement

### Overview

Scheduler statistics are captured from the Linux `/proc` filesystem at
experiment start and end. Delta values represent scheduler activity during
the measurement window.

### Interface

```
/proc/[pid]/status    ← per-process scheduler stats
    voluntary_ctxt_switches
    nonvoluntary_ctxt_switches

/proc/[pid]/stat      ← process timing
    utime (user mode ticks)
    stime (kernel mode ticks)
```

A-LEMS uses `psutil.Process(pid)` which wraps these interfaces.

### Metrics Captured

| Metric | Source | Provenance |
|--------|--------|------------|
| `context_switches_voluntary` | `/proc/[pid]/status` | MEASURED |
| `context_switches_involuntary` | `/proc/[pid]/status` | MEASURED |
| `total_context_switches` | voluntary + involuntary | CALCULATED |
| `kernel_time_ms` | `stime × tick_duration` | MEASURED |
| `user_time_ms` | `utime × tick_duration` | MEASURED |
| `run_queue_length` | `psutil.getloadavg()` | MEASURED |
| `wakeup_latency_us` | scheduler delay | MEASURED |
| `background_cpu_percent` | system CPU excluding PID | MEASURED |
| `process_count` | `psutil.pids()` | MEASURED |
| `interrupt_rate` | `/proc/interrupts` delta | MEASURED |
| `interrupts_per_second` | interrupt_rate / duration | MEASURED |
| `thread_migrations` | perf SW event | MEASURED |

### Why Scheduler Stats Matter

High involuntary context switches indicate CPU contention from background
processes. A-LEMS records these to flag noisy experiments (`experiment_valid`
flag) where background interference may inflate energy measurements.

### Provenance

- **Provenance**: `MEASURED` (raw) / `CALCULATED` (derived)
- **Method ID**: `os_scheduler_reader`
- **Confidence**: `1.0`

---

## OS Memory Measurement

### Overview

Memory statistics are captured from Linux `/proc` and `psutil` interfaces
at experiment boundaries to detect memory pressure effects on energy.

### Interface

```
/proc/[pid]/status    ← VmRSS, VmSize
/proc/swaps           ← swap usage
psutil.virtual_memory() ← system memory
psutil.swap_memory()    ← swap details
```

### Metrics Captured

| Metric | Formula | Provenance |
|--------|---------|------------|
| `rss_memory_mb` | $M_{RSS} = VmRSS / 1024$ | MEASURED |
| `vms_memory_mb` | $M_{VMS} = VmSize / 1024$ | MEASURED |
| `swap_total_mb` | Total swap space | MEASURED |
| `swap_end_free_mb` | Free swap at end | MEASURED |
| `swap_start_used_mb` | Used swap at start | CALCULATED |
| `swap_end_used_mb` | Used swap at end | CALCULATED |
| `swap_end_percent` | Swap usage % | MEASURED |

### Why Memory Matters

DRAM accesses consume energy. High RSS indicates active working set pressure.
Swap activity dramatically increases energy due to storage I/O. A-LEMS
records memory state to correlate memory pressure with energy measurement
quality and flag memory-constrained runs.

### Provenance

- **Provenance**: `MEASURED` (raw) / `CALCULATED` (derived)
- **Method ID**: `os_memory_reader`
- **Confidence**: `1.0`

---

## Network Measurement

### Overview

Network I/O is measured as delta counters between experiment start and end,
capturing bytes transferred and TCP errors during the measurement window.

### Interface

```python
psutil.net_io_counters()  # wraps /proc/net/dev
```

### Formula

$$\Delta B = B_{end} - B_{start}$$

### Metrics Captured

| Metric | Description | Provenance |
|--------|-------------|------------|
| `bytes_sent` | Total bytes transmitted | MEASURED |
| `bytes_recv` | Total bytes received | MEASURED |
| `tcp_retransmits` | TCP retransmission count | MEASURED |
| `dns_latency_ms` | DNS resolution time | MEASURED |

### Why Network Matters

Cloud LLM API calls generate network traffic. Network wait time is a
significant component of agentic workflow latency. A-LEMS separates
network wait time (`non_local_ms`) from compute time to accurately
attribute orchestration overhead.

### Provenance

- **Provenance**: `MEASURED`
- **Method ID**: `network_measurement`
- **Confidence**: `1.0`

---

## System Wall Clock

### Overview

High-precision wall clock timestamps are captured using Python's
`time.time_ns()` which wraps the POSIX `clock_gettime(CLOCK_REALTIME)`
syscall with nanosecond resolution.

### Formula

$$\Delta t = t_{end} - t_{start}$$

### Metrics Captured

| Metric | Description | Provenance |
|--------|-------------|------------|
| `start_time_ns` | Experiment start (nanoseconds) | MEASURED |
| `end_time_ns` | Experiment end (nanoseconds) | MEASURED |
| `duration_ns` | Elapsed nanoseconds | CALCULATED |

### Precision

`time.time_ns()` provides nanosecond resolution on Linux. Actual precision
is limited by kernel timer resolution (typically 1-4ms on standard kernels,
<1µs on `CONFIG_HZ=1000` kernels). A-LEMS pins measurements to dedicated
CPU cores to minimise timer jitter.

### Provenance

- **Provenance**: `MEASURED` (timestamps) / `CALCULATED` (duration)
- **Method ID**: `system_clock`
- **Confidence**: `1.0`
