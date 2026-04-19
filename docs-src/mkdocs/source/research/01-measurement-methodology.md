# Measurement Methodology

This document describes the core measurement principles and methodologies used in A-LEMS.

---

## 🎯 Core Principles

### 1. Immutable Raw Data

All raw measurements are **never modified**. This ensures:
- **Reproducibility** - Original data always available
- **Auditability** - Calculations can be verified
- **Flexibility** - New analysis methods can be applied retrospectively

### 2. Three-Layer Architecture

```
Raw Measurements (immutable)
        │
        ▼
Baseline Subtraction
        │
        ▼
Derived Metrics (workload, tax, etc.)
```

### 3. Timestamp Precision

All samples have **nanosecond-precision timestamps** for:
- Exact correlation with AI workflow phases
- Accurate power calculation
- Precise energy attribution

---

## ⚡ RAPL Energy Measurement

### How RAPL Works

Intel's Running Average Power Limit (RAPL) provides energy counters for different CPU domains:

| Domain | Description | Energy Counter |
|--------|-------------|----------------|
| **Package** | Entire CPU package (cores + uncore) | `package_energy_uj` |
| **Core** | All CPU cores combined | `core_energy_uj` |
| **Uncore** | Cache, memory controller, I/O | `uncore_energy_uj` |
| **DRAM** | Memory subsystem | `dram_energy_uj` |

Each domain has a cumulative energy counter in **microjoules (µJ)**:

$$E_{domain}(t) = \text{counter}_t$$

### Energy Calculation

Energy consumed during measurement interval:

$$\Delta E_{domain} = E_{domain}(t_2) - E_{domain}(t_1)$$

Average power:

$$P_{avg} = \frac{\Delta E_{domain}}{\Delta t} = \frac{E_{domain}(t_2) - E_{domain}(t_1)}{t_2 - t_1}$$

### 100Hz Sampling

The sampling thread runs at 100Hz (configurable):

$$\text{sampling interval} = \frac{1}{f_s} = 10\text{ ms}$$

This captures energy dynamics at:
- 50Hz Nyquist frequency
- Transient spikes down to 20ms duration
- Sub-milliwatt power resolution

---

## 📏 Idle Baseline Methodology

### Why Baseline Matters

Total measured energy includes both workload and system overhead:

$$E_{total} = E_{workload} + E_{idle}$$

To isolate workload energy, we measure idle power:

$$E_{workload} = E_{total} - P_{idle} \cdot \Delta t$$

### Baseline Measurement Protocol

1. **Core pinning**: Pin measurement thread to dedicated core
2. **Pre-wait**: Allow system to enter deep idle (5-10 seconds)
3. **Multiple samples**: 3-10 samples of 10-30 seconds each
4. **Statistical processing**: Mean and standard deviation per domain

### Confidence Interval Approach

Rather than using mean power, we use the **lower bound of 95% confidence interval**:

$$P_{idle,min} = \mu - 2\sigma$$

This prevents over-subtraction of idle energy.

---

## 🧮 Derived Metrics

### Workload Energy

$$E_{workload} = E_{package} - P_{idle,package} \cdot \Delta t$$

### Reasoning Energy

$$E_{reasoning} = E_{core} - P_{idle,core} \cdot \Delta t$$

### Orchestration Tax (Mathematical Proof)

$$
\begin{aligned}
E_{tax} &= E_{workload} - E_{reasoning} \\
&= (E_{pkg} - P_{idle,pkg}\Delta t) - (E_{core} - P_{idle,core}\Delta t) \\
&= (E_{pkg} - E_{core}) - (P_{idle,pkg} - P_{idle,core})\Delta t \\
&= E_{uncore} - P_{idle,uncore}\Delta t
\end{aligned}
$$

**Conclusion:** Orchestration tax equals uncore energy minus idle uncore energy. This is where cache, memory controller, and I/O overhead appear.

---

## 🌡️ Thermal Measurement

### Temperature Sampling

Thermal zones sampled at 1Hz:

$$T_i = \text{temperature at time } t_i$$

### Thermal Gradient

Rate of temperature change:

$$\nabla T = \frac{T_{max} - T_{start}}{t_{rise}}$$

### Thermal-Energy Coupling

At high temperatures, leakage current increases:

$$P_{leak} \propto T^2 e^{-E_a/kT}$$

Total power:

$$P_{total} = P_{dynamic} + P_{leak}(T)$$

---

## 📊 Performance Counter Methodology

### Instructions Per Cycle

$$IPC = \frac{\text{instructions}}{\text{cycles}}$$

IPC indicates CPU efficiency:
- **< 1.0**: Memory-bound or stalled
- **1.0 - 2.0**: Mixed workload
- **> 2.0**: Compute-bound, efficient

### Cache Miss Rate

$$\text{MissRate} = \frac{\text{cache\_misses}}{\text{cache\_references}} \times 100\%$$

High miss rates indicate:
- Poor data locality
- Random access patterns
- Working set exceeds cache size

---

## 🔄 C-State Measurement

### C-State Residency

Time spent in each C-state:

$$t_{Cx} = \sum_{i} \Delta t_i \cdot \mathbb{1}_{state=Cx}$$

Residency percentage:

$$\%Cx = \frac{t_{Cx}}{t_{total}} \times 100\%$$

### Power Savings

Energy saved by entering deep C-states:

$$E_{saved} = \sum_{x} (P_{C0} - P_{Cx}) \cdot t_{Cx}$$

---

## 📈 Statistical Methodology

### Sample Size Determination

For desired effect size $\delta$, power $1-\beta$, and significance $\alpha$:

$$n = \frac{(z_{1-\alpha/2} + z_{1-\beta})^2 \sigma^2}{\delta^2}$$

### Confidence Intervals

95% confidence interval for mean:

$$CI = \bar{x} \pm 1.96 \cdot \frac{\sigma}{\sqrt{n}}$$

### Outlier Detection

Values outside $\mu \pm 3\sigma$ are flagged for review.

---

## 🎯 Measurement Validation

### Repeatability

Coefficient of variation across identical runs:

$$CV = \frac{\sigma}{\mu} \times 100\%$$

Acceptable: < 5%

### Accuracy Validation

Comparison with external power meter:

$$\text{error} = \frac{|E_{RAPL} - E_{meter}|}{E_{meter}} \times 100\%$$

Acceptable: < 2%

---

## 📚 References

1. Intel Corporation. (2012). "Intel® 64 and IA-32 Architectures Software Developer's Manual"
2. Hähnel, M., et al. (2012). "Measuring Energy Consumption for Short Code Paths Using RAPL"
3. Khan, K. N., et al. (2018). "Energy Profiling Using RAPL"
---

## ⚙️ Measurement Modes (Added: Chunk 1)

A-LEMS supports three measurement modes depending on available hardware.
The mode is determined automatically at startup by `PlatformDetector`
and affects how energy values in the database should be interpreted.

### Mode Definitions

**`MEASURED`** — Energy from real hardware sensor.

All energy values in microjoules come directly from a hardware counter
with no estimation or modelling involved. The counter may be:

- RAPL sysfs register (Linux x86_64) — cumulative µJ, read directly
- IOKit power sensor (macOS) — instantaneous watts, integrated to µJ by the reader

Both are `MEASURED` because the underlying measurement is hardware.
The reader may do arithmetic (W×s→µJ) but does not estimate.

**`INFERRED`** — Energy predicted by ML model.

No hardware energy counter is accessible (ARM VM, blocked container).
`EnergyEstimator` uses CPU performance counters (utilisation, frequency,
instruction count, task type) as features to predict package energy.

!!! warning
    `INFERRED` values are estimates. They are stored in the database
    with `measurement_mode = 'INFERRED'` so they can be filtered out
    of accuracy-sensitive analyses. Do not mix MEASURED and INFERRED
    runs in the same comparison without flagging the difference.

**`LIMITED`** — No measurement possible.

Platform has no supported energy interface. All energy values are zero.
Runs are stored with `measurement_mode = 'LIMITED'` and should be
excluded from energy analysis. Useful for functional testing only.

### Mode × Data Quality Matrix

| Mode | Energy Values | Use in Research | Use for Functional Test |
|------|--------------|-----------------|------------------------|
| MEASURED | Real hardware µJ | ✅ Yes | ✅ Yes |
| INFERRED | ML prediction | ⚠️ With caveat | ✅ Yes |
| LIMITED | Zeros | ❌ No | ✅ Yes |

### How Mode is Stored

Every row in the `runs` table includes:

```sql
measurement_mode  TEXT    -- 'MEASURED' / 'INFERRED' / 'LIMITED'
env_hash          TEXT    -- links to environment.json fingerprint
```

Filter for research-grade runs:

```sql
SELECT * FROM runs
WHERE measurement_mode = 'MEASURED'
  AND experiment_valid = 1;
```

## 🔧 OS Scheduler Measurement

### What Is Measured

The Linux kernel exposes per-process scheduler statistics via `/proc/[pid]/status`
and system-wide statistics via `/proc/stat`. A-LEMS reads these at experiment
start and end to capture the scheduling overhead imposed by the workload.

Metrics captured:
- `voluntary_ctxt_switches` — process yielded CPU willingly (e.g. waiting for I/O)
- `nonvoluntary_ctxt_switches` — process preempted by scheduler
- `run_queue_length` — number of processes waiting for CPU
- `kernel_time_ms` — time spent in kernel mode
- `user_time_ms` — time spent in user mode
- `wakeup_latency_us` — time from wake request to actual CPU acquisition

### Why This Matters

High involuntary context switches indicate CPU contention — other processes
are competing for the same cores. This inflates wall-clock duration without
adding computational work, artificially increasing energy measurements.
A-LEMS records these to allow filtering of high-contention runs.

### Implementation

```python
# Reads via psutil — wraps /proc/[pid]/status
proc = psutil.Process(pid)
ctx = proc.num_ctx_switches()
voluntary   = ctx.voluntary
involuntary = ctx.involuntary
```

### Provenance

| Column | Provenance | Confidence |
|--------|-----------|------------|
| `context_switches_voluntary` | MEASURED | 1.0 |
| `context_switches_involuntary` | MEASURED | 1.0 |
| `total_context_switches` | CALCULATED | 1.0 |
| `kernel_time_ms` | MEASURED | 1.0 |
| `user_time_ms` | MEASURED | 1.0 |
| `run_queue_length` | MEASURED | 1.0 |
| `wakeup_latency_us` | MEASURED | 1.0 |

---

## 💾 OS Memory Measurement

### What Is Measured

Memory consumption is captured at experiment boundaries using the Linux
`/proc/[pid]/status` virtual memory statistics and system-wide swap
statistics from `/proc/swaps`.

Metrics captured:
- `rss_memory_mb` — Resident Set Size: physical RAM actually used
- `vms_memory_mb` — Virtual Memory Size: total virtual address space
- `swap_*_mb` — Swap usage at start/end of experiment

### Why Memory Matters for Energy

DRAM access is a significant energy consumer. High RSS indicates active
memory pressure. Swap activity (if any) dramatically increases energy
consumption due to disk I/O. A-LEMS records memory state to allow
correlation between memory pressure and energy measurement quality.

### Formula

$$M_{RSS} = \frac{\text{VmRSS from /proc/[pid]/status}}{1024} \text{ MB}$$

### Implementation

```python
# Via psutil — wraps /proc/[pid]/status
proc = psutil.Process(pid)
mem  = proc.memory_info()
rss_mb = mem.rss / (1024 * 1024)
vms_mb = mem.vms / (1024 * 1024)
```

### Provenance

| Column | Provenance | Confidence |
|--------|-----------|------------|
| `rss_memory_mb` | MEASURED | 1.0 |
| `vms_memory_mb` | MEASURED | 1.0 |
| `swap_total_mb` | MEASURED | 1.0 |
| `swap_end_free_mb` | MEASURED | 1.0 |
| `swap_start_used_mb` | CALCULATED | 1.0 |
| `swap_end_used_mb` | CALCULATED | 1.0 |
| `swap_end_percent` | MEASURED | 1.0 |
