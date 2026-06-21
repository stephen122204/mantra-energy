# Energy Reader Methodology

This document describes the measurement methodology for all energy reader
implementations in A-LEMS. Each reader implements `EnergyReaderABC` and
is selected automatically by `ReaderFactory` based on platform capabilities
detected at startup.

---

## RAPL Energy Measurement

### Overview

Intel RAPL (Running Average Power Limit) is a hardware interface that exposes
cumulative energy consumption counters via Model Specific Registers (MSRs)
and the Linux sysfs powercap interface. A-LEMS reads these counters at
100Hz to produce high-resolution energy time series.

### Hardware Interface

RAPL exposes energy counters through the Linux kernel's powercap subsystem:

```
/sys/class/powercap/intel-rapl/
    intel-rapl:0/           ← Package 0
        energy_uj           ← Cumulative package energy in µJ
        intel-rapl:0:0/     ← Core power plane (PP0)
            energy_uj
        intel-rapl:0:1/     ← Uncore power plane (PP1)
            energy_uj
    intel-rapl:1/           ← Package 1 (dual-socket systems)
```

The primary register is `MSR_PKG_ENERGY_STATUS` (MSR address `0x611`),
which accumulates energy consumed by the entire CPU package including
cores, cache, memory controller, and integrated GPU.

### Energy Calculation

Energy is computed as a delta between two counter readings:

$$E_{pkg} = R_{end} - R_{start}$$

Where:
- $E_{pkg}$ = Package energy consumed in µJ
- $R_{end}$ = RAPL counter value at measurement end
- $R_{start}$ = RAPL counter value at measurement start

**Counter wrap-around handling:**

RAPL counters are 32-bit and wrap at approximately $2^{32}$ µJ (≈70 minutes
at 1000W TDP). A-LEMS detects and corrects wrap-around:

$$E_{pkg} = \begin{cases} R_{end} - R_{start} & \text{if } R_{end} \geq R_{start} \\ (2^{32}-1 - R_{start}) + R_{end} & \text{wrap-around} \end{cases}$$

### Sampling Architecture

A-LEMS samples RAPL at 100Hz using a dedicated high-frequency sampling thread:

```
EnergyEngine._sampling_loop()
    ├── t=0ms:   read start counter
    ├── t=10ms:  read end counter → compute delta → enqueue
    ├── t=10ms:  read start counter
    ├── t=20ms:  read end counter → compute delta → enqueue
    └── ...
```

Each sample records:
- `sample_start_ns` — nanosecond timestamp at counter read start
- `sample_end_ns` — nanosecond timestamp at counter read end
- `pkg_start_uj`, `pkg_end_uj` — raw counter values
- `interval_ns` — actual elapsed time between reads

### Domains

A-LEMS captures four energy domains when available:

| Domain | MSR | Description |
|--------|-----|-------------|
| `package-0` | `0x611` | Entire CPU package (primary metric) |
| `core` | `0x639` | CPU cores only (excludes uncore) |
| `uncore` | `0x641` | Cache, memory controller, ring bus |
| `dram` | `0x61B` | DRAM controller (server CPUs only) |

### Platform Availability

| Platform | Available | Confidence |
|----------|-----------|------------|
| Linux x86_64 bare metal | ✅ Yes | 1.0 |
| Linux x86_64 VM (RAPL passthrough) | ✅ Yes | 1.0 |
| Linux aarch64 (ARM VM) | ❌ No | 0.0 |
| macOS | ❌ No | 0.0 |

### Provenance

- **Provenance**: `MEASURED`
- **Method ID**: `rapl_msr_pkg_energy`
- **Confidence**: `1.0`
- **Fallback**: `ml_energy_estimator`

### References

- Intel Corporation. *Intel 64 and IA-32 Architectures Software Developer
  Manual*, Volume 3B, Section 14.9. 2023.
- Sangha, A. et al. *A-LEMS: Agent vs Linear Energy Measurement Platform*.
  arXiv:2509.09991, 2025.

---

## IOKit Power Reader

### Overview

On macOS, hardware power sensors are accessible via Apple's IOKit framework.
A-LEMS reads instantaneous power (watts) from IOKit HID services and
integrates over time to produce cumulative energy values:

$$E_{pkg} = \sum_{i} P_i \cdot \Delta t_i \times 10^6$$

Where:
- $P_i$ = Instantaneous power in watts from IOKit sensor
- $\Delta t_i$ = Elapsed seconds since last read
- Result in µJ (multiply by $10^6$)

### Hardware Interface

**Intel Macs**: System Management Controller (SMC) via IOKit HID
**Apple Silicon**: Power Management Unit (PMGR) via IOKit

### Current Status

**Stub implementation** — returns zeros pending full IOKit integration
(planned for Chunk 1.1 when Mac hardware is available for testing).

### Platform Availability

| Platform | Available | Confidence |
|----------|-----------|------------|
| macOS Intel | ✅ Real hardware | 0.5 (stub) → 1.0 (Chunk 1.1) |
| macOS Apple Silicon | ✅ Real hardware | 0.5 (stub) → 1.0 (Chunk 1.1) |
| Linux | ❌ No | 0.0 |

### Provenance

- **Provenance**: `MEASURED`
- **Method ID**: `iokit_power_reader`
- **Confidence**: `0.5` (stub) → `1.0` (post Chunk 1.1)
- **Fallback**: `ml_energy_estimator`

### References

- Apple Inc. *IOKit Power Management Programming Guide*. 2022.
  https://developer.apple.com/documentation/iokit

---

## Estimator (ML-Based Energy Estimation)

### Overview

On ARM VMs and platforms without RAPL access, A-LEMS uses a trained
XGBoost model to estimate package energy from observable system metrics:

$$\hat{E}_{pkg} = f_{\theta}(\text{cpu\_util}, \text{freq\_mhz}, \text{instructions}, \text{task\_type})$$

Where $f_{\theta}$ is a trained regression model with parameters $\theta$.

### Feature Vector

| Feature | Source | Unit |
|---------|--------|------|
| `cpu_util_pct` | `/proc/stat` | % |
| `freq_mhz` | turbostat | MHz |
| `instructions` | perf counters | count |
| `task_type` | experiment config | categorical |

### Current Status

**Stub implementation** — returns zeros pending model training
(planned for Chunk 7 when training data is available from UBUNTU2505
bare metal runs).

### Platform Availability

| Platform | Available | Confidence |
|----------|-----------|------------|
| Linux aarch64 (ARM VM) | Model pending | 0.0 (stub) → TBD (Chunk 7) |
| Any platform without RAPL | Model pending | 0.0 (stub) |

### Provenance

- **Provenance**: `INFERRED`
- **Method ID**: `ml_energy_estimator`
- **Confidence**: `0.0` (stub) → validated score (Chunk 7)
- **Fallback**: None (last resort)

### References

- Sangha, A. et al. *Data-Driven Energy Estimation for Virtual Servers*.
  arXiv:2509.09991, Section 4. 2025.

---

## Dummy Energy Reader

### Overview

Safe fallback for completely unsupported platforms (Windows, WSL, unknown OS).
Returns zero for all energy domains. Never raises exceptions — system
stability is guaranteed on any platform.

$$E_{pkg} = 0 \quad \text{(platform not supported)}$$

### Purpose

The dummy reader ensures A-LEMS never crashes due to missing hardware support.
All results from dummy reader runs are marked `LIMITED` with `confidence=0.0`
and should be excluded from any energy analysis.

### Platform Availability

| Platform | Available | Confidence |
|----------|-----------|------------|
| Windows | ✅ (returns zeros) | 0.0 |
| WSL | ✅ (returns zeros) | 0.0 |
| Unknown OS | ✅ (returns zeros) | 0.0 |

### Provenance

- **Provenance**: `LIMITED`
- **Method ID**: `dummy_energy_reader`
- **Confidence**: `0.0`
- **Fallback**: None

---

## Reader Selection Logic

`ReaderFactory` selects the appropriate reader automatically:

```
PlatformDetector detects:
    OS + architecture + hardware capabilities
        ↓
ReaderFactory dispatches:
    MEASURED + Linux   → RAPLReader
    MEASURED + macOS   → IOKitPowerReader
    INFERRED           → EnergyEstimator
    LIMITED            → DummyEnergyReader
```

The selected reader's `METHOD_PROVENANCE` is stored in every run's
`measurement_methodology` rows via `reader_mode` parameter, ensuring
full audit trail of which reader was active for each experiment.
## GPU PP1 Energy Measurement

### Method ID: `gpu_rapl_pp1_v1`

**Platform:** UBUNTU2505 (Intel i7-1165G7, Tiger Lake, Iris Xe 96EU)  
**Provenance:** MEASURED  
**Confidence:** 0.95  
**Layer:** silicon

#### Background

Intel Tiger Lake exposes GPU energy via MSR_PP1_ENERGY_STATUS (MSR 0x641). This is a
package-level cumulative counter — no per-process GPU split is possible. Attribution
uses baseline subtraction, identical to the CPU dynamic energy methodology.

**Important:** The sysfs powercap path `intel-rapl:0/intel-rapl:0:1` is named `uncore`
on Tiger Lake and measures the uncore domain (L3 cache, memory controller, ring bus),
NOT the GPU. GPU energy is only accessible via MSR 0x641 directly.

#### Read Mechanism

GPU energy is read via the `msr_read` C binary (`core/msr_helper/msr_read.c`):

```
./msr_read 0 0x641   → raw 64-bit counter value
```

Energy unit from MSR 0x606 bits[12:8] = 14:

```
E_unit = 0.5^14 J = 61.0352 µJ per LSB
```

Formula:

$$E_{gpu} = (R_{end} - R_{start}) \times 61.0352\,\mu J$$

#### Cross-Validation

MSR 0x641 readings were cross-validated against the Linux perf PMU event
`power/energy-gpu/` over 5-second windows. Agreement within 7% confirms
the MSR read is correct.

#### Platform Availability

| Platform | Available | Method |
|----------|-----------|--------|
| UBUNTU2505 (Tiger Lake) | Yes | MSR 0x641 via msr_read |
| GN100 (ARM GB10) | No | No MSR interface |
| macOS | No | No /dev/cpu/N/msr |
| Other Linux x86 | Conditional | Detection via `_detect_gpu_pp1()` |

On unavailable platforms, all GPU columns store NULL. ETL skips GPU computation
when `gpu_total_energy_uj IS NULL`.

---

### Method ID: `gpu_dynamic_baseline_v1`
 
**Provenance:** CALCULATED  
**Confidence:** 0.90  
**Layer:** silicon  
**Status:** Secondary method as of 2026-06-21. Used only as fallback when a
run has zero idle-classified GPU samples for `gpu_dynamic_run_local_v1`
(below) to build a local reference from.
 
#### Formula
 
$$E_{gpu,dyn} = E_{gpu,total} - \dot{E}_{gpu,base} \cdot t$$
 
### Method ID: `gpu_dynamic_run_local_v1`
 
**Provenance:** CALCULATED  
**Confidence:** 0.90  
**Layer:** silicon  
**Status:** Primary method as of 2026-06-21.
 
#### Formula
 
$$P_{idle} = \operatorname{median}(P_i \mid \text{sample classified idle in this run})$$
 
$$E_{gpu,dyn} = \sum_i \max(P_i - P_{idle}, 0)\,\Delta t_i$$
 
#### Description
 
Idle power is estimated from the run's own idle-classified GPU samples,
not a separately-measured external calibration baseline. This removes
thermal drift, clock drift, and background load differences between
calibration time and run time. Median is used instead of mean because
idle samples occasionally contain scheduler noise or telemetry jitter;
median gives a robust estimator of steady-state idle power. Dynamic
energy is the sum of the positive residual above that local idle
reference, integrated across every sample in the run.
 
A sample is classified idle using whatever GPU activity signal is
actually available on the current platform, not a hardcoded universal
rule. On GN100 today, DCGM exposes only `util_gpu_pct`, so idle is
`util_gpu_pct == 0`. A future platform or backend reporting additional
signals gets its own classification rule without changing this formula.
 
Falls back to `gpu_dynamic_baseline_v1` only when a run has zero
idle-classified samples, GPU active the entire run, no local idle
reference available. Every run records which method was actually used
(`runs.gpu_dynamic_method`) and the literal idle power value applied
(`runs.gpu_idle_power_w_used`), so the split between the two methods
across any set of runs is a direct query, not an estimate.
 
#### Validated against
 
Confirmed on GN100 in two real same-experiment runs: external
calibration, measured once and separately, produced baseline-exceeds-
total in opposite directions depending on run duration and idle-time
fraction within the run, the wrong run looked correct and the right run
looked like zero. Run-local estimation resolved both by referencing
each run's own conditions instead of one fixed external number.
 

Where:
- $E_{gpu,total}$ = SUM of gpu_energy_uj across all energy_samples for the run
- $\dot{E}_{gpu,base}$ = `idle_baselines.gpu_power_watts` (mean - 2*std, 2nd percentile)
- $t$ = run duration in seconds

#### Baseline Measurement

GPU baseline is measured during `measure_idle_baseline()` when `measure_gpu: true`
in `app_settings.yaml`. Each idle sample reads MSR 0x641 at start and end of the
sample window, computing GPU power in Watts. Mean and std are stored in
`idle_baselines.gpu_power_watts` and `idle_baselines.gpu_std`.

#### Columns Populated

| Column | Table | Description |
|--------|-------|-------------|
| `gpu_total_energy_uj` | `runs` | SUM(gpu_energy_uj) over all energy_samples |
| `gpu_baseline_energy_uj` | `runs` | idle GPU rate * run_duration_ns |
| `gpu_dynamic_energy_uj` | `runs` | gpu_total - gpu_baseline |
| `gpu_pct_of_pkg` | `runs` | gpu_dynamic / dynamic_energy_uj * 100 |
| `gpu_energy_uj` | `goal_attempt` | gpu_dynamic_energy_uj for this attempt |
| `gpu_total_energy_uj` | `goal_execution` | SUM across attempts |
| `gpu_pct_of_pkg` | `goal_execution` | GPU share of goal energy |

#### Paper Finding

Integrated GPU energy (Intel Iris Xe, MSR PP1) accounts for a higher percentage
of dynamic package energy during agentic workflows than linear workflows. This
increase is driven by orchestration overhead — not ML compute, since no CUDA or
local GPU inference is used in any experiment.

---

## Device Telemetry

Device telemetry captures instantaneous device state at 10 Hz alongside energy
sampling. It is distinct from energy measurement: power is instantaneous (mW),
energy is cumulative (µJ). They have different conservation properties and
different consumers.

### What Device Telemetry Captures

| Field | Unit | Description |
|-------|------|-------------|
| power_mw | mW | Instantaneous device power draw |
| energy_uj | µJ | Cumulative energy delta (nullable) |
| util_pct | % | Device utilization 0 to 100 |
| temp_c | °C | Device temperature |
| clock_mhz | MHz | Device clock frequency |
| dc_input_mw | mW | Wall input power (SPBM dc_input, SOC only) |
| mem_util_pct | % | Memory utilization (GPU only) |

### Device Types

```
GPU      discrete or integrated GPU (NVML, DCGM, IOKit)
SOC      full SoC telemetry (SPBM dc_input channel, GN100)
CPU      CPU frequency and C-state telemetry (future)
NETWORK  network device telemetry (future RDMA)
STORAGE  storage device telemetry (future NVMe)
```

### energy_uj Nullability

`energy_uj` is present when the backend provides a cumulative counter:

- NVML: `nvmlDeviceGetTotalEnergyConsumption()` returns cumulative mJ
- DCGM: field 156 returns cumulative mJ
- IOKit: integrated power sensor

`energy_uj` is NULL for `SMI_INTEG` (nvidia-smi power integration). In that
case power_mw is recorded and ETL integrates W x dt at run completion.

### dc_input_mw (GN100 SOC)

SPBM exposes a `dc_input` power channel giving wall input power to the SoC.
This is stored in `device_telemetry` with `device_type='SOC'`. It is the
closest equivalent to a wall power meter on the GN100 platform and is used
for total system energy accounting in the NVLink-C2C paper.

### Sampling Rate

Device telemetry is sampled at 10 Hz, aligned with `energy_samples_v2` timestamps.
This allows per-sample correlation between energy domain values and device state.

### method_id

`device_telemetry_v1` — confidence 1.0 (MEASURED: direct hardware interface reads)

---

## ARM PMU Reader (arm_pmu_v1)

**Platform:** GN100 (NVIDIA Grace, Neoverse V2, aarch64)
**method_id:** `arm_pmu_v1`
**Confidence:** 0.95
**Provenance:** MEASURED
**Layer:** silicon

### What It Measures

ARM Neoverse V2 performance counters via Linux `perf stat`. Attaches to the
target process PID during the measurement window. Uses generic event names
(`instructions`, `cycles`) for core IPC metrics and `armv8_pmuv3/` prefixed
events for cache hierarchy where no generic alias exists on ARM Linux.

### Column Mapping

| runs column | ARM PMU event | Notes |
|---|---|---|
| instructions | `instructions` | retired instruction count |
| cycles | `cycles` | CPU cycle count |
| ipc | derived | instructions / cycles |
| cache_misses | `armv8_pmuv3/l1d_cache_refill/` | L1D refill count |
| cache_references | `armv8_pmuv3/l1d_cache/` | L1D access count |
| l1d_cache_misses_total | `armv8_pmuv3/l1d_cache_refill/` | same as cache_misses |
| l2_cache_misses_total | `armv8_pmuv3/l2d_cache_refill/` | L2D refill count |
| l3_cache_hits_total | `armv8_pmuv3/l3d_cache/` | L3D hit count |
| l3_cache_misses_total | `armv8_pmuv3/l3d_cache_refill/` | L3D refill count |

### Confidence Note

0.95 not 1.0: ARM PMU event multiplexing may cause minor undercounting when
more events are requested than hardware PMU registers available on the core.
Neoverse V2 has 6 programmable counters. Seven events are requested — one
counter slot is time-multiplexed, introducing small statistical error.

### x86 Equivalent

`PerfReader` on UBUNTU2505 and Alex AMD machine. Factory dispatches
`ARMPMUReader` only when `caps.arch == 'aarch64'` and `caps.has_arm_pmu`.

---

## ARM cpufreq Reader (arm_cpufreq_v1)

**Platform:** GN100 (NVIDIA Grace, Neoverse V2, aarch64)
**method_id:** `arm_cpufreq_v1`
**Confidence:** 0.90
**Provenance:** MEASURED
**Layer:** os

### What It Measures

CPU operating frequency via Linux cpufreq sysfs at 10 Hz during the
measurement window. Reads `/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq`
(kHz, converted to MHz) for all online CPUs and returns the time-averaged
frequency across all cores and all sample points.

### Column Mapping

| runs column | Source | Notes |
|---|---|---|
| frequency_mhz | cpufreq sysfs avg | mean across all CPUs and window |
| cpu_avg_mhz | cpufreq sysfs avg | same value |
| c2_time | NULL | ARM WFI/WFE not equivalent to x86 c-states |
| c3_time | NULL | ARM WFI/WFE not equivalent to x86 c-states |
| c6_time | NULL | ARM WFI/WFE not equivalent to x86 c-states |
| c7_time | NULL | ARM WFI/WFE not equivalent to x86 c-states |
| ring_bus_freq_mhz | NULL | no turbostat on ARM |
| voltage_vcore_avg | NULL | no MSR on ARM |

### NULL is Correct for C-states

ARM uses WFI (Wait For Interrupt) and WFE (Wait For Event) idle states.
These are not equivalent to x86 C2/C3/C6/C7 residency states. Storing NULL
per MIC-1 is scientifically correct — do not estimate or map to zero.

### Confidence Note

0.90 not 1.0: sysfs polling at 10 Hz has ~100ms granularity. TurbostatReader
on x86 uses MSR timestamps at ~10ms resolution. Frequency transitions faster
than 100ms are averaged out. On Grace under LLM inference load, frequency is
typically stable at or near maximum, so the practical impact is small.

### x86 Equivalent

`TurbostatReader` on UBUNTU2505 and Alex AMD machine. Factory dispatches
`ARMCPUFreqReader` only when `caps.os == 'Linux'` and `caps.arch == 'aarch64'`.
# ============================================================
# docs-src/mkdocs/source/research/07-energy-readers-methodology.md
# APPEND this block at the end of the file (after line 501)
# ============================================================

---

## ARM Thermal Reader (arm_thermal_sysfs_v1)

### Overview

**method_id:** `arm_thermal_sysfs_v1`
**confidence:** 0.90
**platform:** GN100 (aarch64, NVIDIA Grace)
**reader class:** `ARMThermalReader`

Reads thermal zone temperatures via `/sys/class/thermal/thermal_zone*/temp` on ARM
Linux. Used on GN100 where `SensorReader` returns empty results because it requires
x86-specific hwmon paths from `hw_config["thermal"]["paths"]` that are absent on Grace.

### GN100 Thermal Zones (Verified 2026-06-18)

| Zone | Type | Idle Temp |
|------|------|-----------|
| thermal_zone0 | acpitz | 44.8°C |
| thermal_zone1 | acpitz | 43.8°C |
| thermal_zone2 | acpitz | 43.7°C |
| thermal_zone3 | acpitz | 43.8°C |
| thermal_zone4 | acpitz | 43.7°C |
| thermal_zone5 | acpitz | 43.8°C |
| thermal_zone6 | acpitz | 44.8°C |

All 7 zones report `type=acpitz` (ACPI thermal zone). No MSR or hwmon thermal
interface is available on the Grace SoC.

### Column Mapping

| runs column | Source | Notes |
|-------------|--------|-------|
| package_temp_celsius | avg(all 7 acpitz zones) | averaged for stability |
| start_temp_c | first sample in run | from thermal_samples ETL |
| max_temp_c | max across run | from thermal_samples ETL |
| min_temp_c | min across run | from thermal_samples ETL |
| thermal_delta_c | max_temp_c - start_temp_c | derived |

### Why Average 7 Zones

All zones report ACPI package-level temperature derived from the same SoC thermal
diode network. Averaging gives a stable value robust to per-zone ACPI polling jitter.

### Confidence Note

0.90 not 1.0: ACPI thermal zones have a polling interval of 100-200ms, introducing
lag relative to true silicon temperature. Under sustained LLM inference this averages
out. Peak temperature excursions shorter than 200ms may be missed.

### NULL is Correct for GPU Temperature

GPU temperature on GN100 is available via `nvidia-smi` and DCGM. `ARMThermalReader`
does not populate `gpu_celsius` — it returns 0.0 per the ABC contract. GPU temperature
attribution is handled separately by the DCGM backend.

### x86 Equivalent

`SensorReader` on UBUNTU2505 and Alex AMD machine. Factory dispatches
`ARMThermalReader` only when `caps.os == 'Linux'` and `caps.arch == 'aarch64'`
and `caps.has_thermal`.
