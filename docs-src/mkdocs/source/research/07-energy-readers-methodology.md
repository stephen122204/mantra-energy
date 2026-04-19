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
