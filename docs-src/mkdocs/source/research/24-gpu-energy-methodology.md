# GPU Energy Measurement Methodology

**Chunk 15 — A-LEMS Platform**
**Status:** 15-A complete (MSR PP1 backend). 15-B pending (NVML/DCGM/IOKit/ROCm).

---

## Overview

A-LEMS measures GPU energy alongside CPU energy to produce a complete system
energy picture for agentic AI workloads. GPU energy is collected at 10 Hz via
a backend-abstracted `GPUCollector` that automatically selects the appropriate
measurement source for each platform.

GPU and CPU energy are **disjoint physical quantities** — no conservation
relationship exists between them. Each domain has its own attribution chain
and its own conservation invariants (D5–D8 for GPU, D1–D4 for CPU).

---

## Physical Model

On Intel x86 platforms, the package energy domain decomposes as:

```
PKG = core + uncore + remainder
```

Where:
- `core` — CPU cores (measured via intel-rapl:0:0)
- `uncore` — L3 cache and ring bus (measured via intel-rapl:0:1, named "uncore" in sysfs)
- `remainder` — everything else (~36% of PKG on UBUNTU2505 i7-1165G7)

**Critical:** `intel-rapl:0:1` sysfs domain is named "uncore" but refers to the
L3/ring bus, NOT the GPU. GPU energy is NOT available via sysfs powercap on
Intel Tiger Lake. It must be read via MSR 0x641 (MSR_PP1_ENERGY_STATUS).

GPU is a sub-component of `remainder`:

```
PKG >= core + GPU    (D4-extended invariant — always holds)
GPU ⊂ remainder      (GPU never overlaps core or uncore)
```

---

## Per-Platform Backend Matrix

| Platform | Hardware | Backend | Energy Source | Confidence |
|----------|----------|---------|---------------|-----------|
| UBUNTU2505 | Intel i7-1165G7 + Iris Xe | `msr_pp1` | MSR 0x641 | 1.0 |
| GN100 | NVIDIA GB10 Superchip (ARM) | `dcgm` | DCGM field 156 | 1.0 |
| Alex machine | AMD Ryzen + RTX 2070 Super | `nvml` | NVML totalEnergyConsumption | 1.0 |
| Stephen M1 | Apple M1 Pro | `iokit` | powermetrics gpu_power | 0.90 |
| AMD GPU (future) | AMD discrete | `rocm_smi` | rsmi_dev_energy_count_get | 0.85 |
| Unknown | Any | `none` | Not available | N/A |

Backend detection runs once at `GPUCollector.__init__()`. Detection order:
DCGM → NVML → MSR PP1 → ROCm → IOKit → None. First available wins.
The `source` column in `gpu_samples` records which backend produced each sample.

---

## MSR PP1 Backend (UBUNTU2505)

**MSR address:** 0x641 (MSR_PP1_ENERGY_STATUS)

**Energy unit:** 61.0352 µJ per LSB

Derived from MSR 0x606 (MSR_RAPL_POWER_UNIT) bits[12:8] = 14:

```
energy_unit = 2^(-14) J = 61.0352 µJ/LSB
```

**Verification:**
```bash
~/mydrive/alems-platform/core/msr_helper/msr_read 0 0x641
# Returns raw counter, e.g. 123689383
# Idle GPU: ~50 mW (0.10 J over 2 seconds)
```

Cross-validated against `perf stat -e power/energy-gpu/` with 7% agreement.
No sudo required on UBUNTU2505 (msr module loaded, group permissions set).

**Limitation:** MSR PP1 exposes energy only. No utilization, clock, memory,
or temperature signals via this backend. Those `gpu_samples` columns are NULL
for `source = 'msr_pp1'`.

---

## DCGM Backend (GN100)

**DCGM field:** 156 (DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION)

Cumulative mJ counter. Validated on GN100 GB10 Superchip with
`spark_hwmon` driver loaded (45/45 DSM offsets confirmed).

RAPL does not exist on the GB10 ARM platform. DCGM is the only validated
GPU energy path on DGX/HGX systems. This is a vendor product decision,
not a hardware limitation (documented in LOCO Workshop paper arXiv:2605.27599).

---

## NVML Backend (NVIDIA Discrete GPUs)

**NVML function:** `nvmlDeviceGetTotalEnergyConsumption()`

Returns cumulative mJ counter. Converted to µJ for consistency with all
other A-LEMS energy columns.

Fallback for older drivers: `nvmlDeviceGetPowerUsage()` returns instantaneous
mW. GPUCollector integrates power × Δt. Confidence drops to 0.85 for
power-integration fallback (method_id: `nvml_power_integration_v1`).

Additional signals available via NVML: utilization, SM clock, memory clock,
memory used, temperature. All populated in `gpu_samples` signal columns.

---

## Sampling Architecture

`GPUCollector` runs in a background daemon thread at **10 Hz** alongside the
existing `HighFrequencySampler` (RAPL at 100 Hz). Rate rationale:

- NVML caps at ~50 Hz; 10 Hz balances detail vs collector overhead
- Matches `cpu_samples` and `interrupt_samples` rate
- Provides sufficient temporal resolution for phase alignment with
  `orchestration_events` phase boundaries (D8 proxy method)

**Queue policy:** oldest-drop (same as `HighFrequencySampler`). Queue size
2000 samples = ~3.3 minutes at 10 Hz before drop occurs.

**Counter wraparound:** MSR 0x641 is a 32-bit counter. Wraparound detected
by negative delta — sample skipped, warning logged, previous state updated.
At 61.0352 µJ/LSB and 50 mW idle, wraparound occurs after ~72 hours of
continuous measurement. Not a practical concern for A-LEMS run durations.

---

## gpu_samples Table

```sql
CREATE TABLE gpu_samples (
    sample_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(run_id),
    gpu_index        INTEGER NOT NULL DEFAULT 0,  -- 0-based, multi-GPU support
    sample_start_ns  BIGINT NOT NULL,
    sample_end_ns    BIGINT NOT NULL,
    interval_ns      BIGINT NOT NULL,
    energy_start_uj  BIGINT,   -- cumulative counter at sample start
    energy_end_uj    BIGINT,   -- cumulative counter at sample end
    energy_uj        BIGINT,   -- delta (denorm for query speed)
    power_mw         INTEGER,  -- instantaneous power (NVML fallback / IOKit)
    util_gpu_pct     REAL,     -- NULL for msr_pp1 backend
    util_mem_pct     REAL,     -- NULL for msr_pp1 backend
    sm_clock_mhz     INTEGER,  -- NULL for msr_pp1 backend
    mem_clock_mhz    INTEGER,  -- NULL for msr_pp1 backend
    mem_used_mb      INTEGER,  -- NULL for msr_pp1 backend
    temperature_c    INTEGER,  -- NULL for msr_pp1 backend
    source           TEXT NOT NULL  -- backend identifier
);
```

---

## gpu_config Table

One row per physical GPU per machine. Populated by `scripts/chunk15_detect_gpu.py`.

```sql
CREATE TABLE gpu_config (
    gpu_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    gpu_index         INTEGER NOT NULL DEFAULT 0,
    vendor            TEXT NOT NULL,   -- 'intel'|'nvidia'|'amd'|'apple'
    model             TEXT NOT NULL,
    driver_version    TEXT,
    cuda_version      TEXT,
    rocm_version      TEXT,
    vbios_version     TEXT,
    pci_id            TEXT,
    memory_total_mb   INTEGER,
    energy_supported  INTEGER NOT NULL DEFAULT 0,
    backend           TEXT,
    gpu_hash          TEXT NOT NULL,   -- SHA256(model||pci_id||driver_version)
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(gpu_index, gpu_hash)
);
```

`gpu_hash` tracks hardware identity across driver upgrades. A new row is
inserted when `gpu_hash` changes (driver or VBIOS update detected).

---

## Attribution Method

`runs.gpu_attribution_method` records how `gpu_dynamic_energy_uj` was computed:

| Value | Meaning | When used |
|-------|---------|-----------|
| `exclusive` | Workload had exclusive GPU use | All current A-LEMS experiments (single-process) |
| `utilization` | GPU shared between processes | Future multi-tenant work |
| `none` | GPU not used or counters unavailable | NoneBackend or no GPU |

**B-decision:** `gpu_dynamic_energy_uj` is the canonical attributed GPU energy
metric. It is identical to what Chunk 15 spec calls `gpu_attributed_energy_uj`.
No separate column needed — the equation is the same:

```
E_gpu,dynamic = E_gpu,total - E_gpu,baseline
```

---

## Conservation Invariants

GPU conservation is independent from CPU conservation. Each domain has its
own invariant chain.

### D4-Extended (cross-domain sanity check)
```
core_energy_uj + gpu_total_energy_uj <= pkg_energy_uj
```
GPU is in PKG remainder, so sum of core + GPU can never exceed PKG.
Zero violations expected. Validated by `validate_energy_chain.py --check d4-extended`.

### D5 — GPU AXIS 1A (sample coverage)
```
SUM(gpu_samples.energy_uj) ≈ gpu_total_energy_uj    (tolerance: 1%)
```
Validates that per-sample sum matches the scalar total stored on `runs`.

### D6 — GPU AXIS 1B (attribution closure)
```
gpu_total_energy_uj = gpu_dynamic_energy_uj + gpu_baseline_energy_uj
```
Exact by construction. Tolerance: 1 mJ for floating-point rounding.

### D7 — GPU AXIS 2A (functional projection, exact)
```
gpu_dynamic_energy_uj = gpu_llm_compute_energy_uj + gpu_orchestration_energy_uj
```
Exact by construction — remainder assigned to `gpu_llm_compute_energy_uj`.

### D8 — GPU AXIS 2B (phase projection, exact)
```
gpu_dynamic_energy_uj = gpu_phase_planning_uj + gpu_phase_execution_uj
                      + gpu_phase_synthesis_uj + gpu_phase_inter_uj
```
Exact by construction — remainder assigned to `gpu_phase_inter_uj`.

---

## Total System Energy

```sql
CREATE VIEW total_system_energy AS
SELECT
    run_id,
    attributed_energy_uj                              AS cpu_attributed_uj,
    COALESCE(gpu_dynamic_energy_uj, 0)                AS gpu_attributed_uj,
    attributed_energy_uj
        + COALESCE(gpu_dynamic_energy_uj, 0)          AS total_attributed_uj,
    gpu_attribution_method,
    gpu_count
FROM runs;
```

`total_attributed_uj` is the headline number for cross-platform comparison.
Confidence inherits the minimum of CPU and GPU confidence for the run.

---

## EpG Extensions

Three EpG variants on `goal_execution`:

| Column | Definition |
|--------|-----------|
| `successful_energy_uj` | Existing CPU EpG (unchanged) |
| `gpu_total_energy_uj` | GPU energy summed across goal attempts |
| `EpG_total` | `(successful_energy_uj + gpu_total_energy_uj) / successful_goals` |

`EpG_total` is the cross-platform headline metric. Computed by
`goal_execution_etl.py` extension in Chunk 15-C.

---

## run_quality GPU Validity

```sql
ALTER TABLE run_quality ADD COLUMN gpu_valid INTEGER DEFAULT 1;
ALTER TABLE run_quality ADD COLUMN gpu_rejection_reason TEXT;
```

| Rejection reason | Meaning |
|-----------------|---------|
| `counter_unavailable` | Driver does not expose energy counters |
| `sample_coverage_below_95pct` | gpu_samples cover < 95% of run duration |
| `temperature_throttle_detected` | GPU thermal throttling mid-run |
| `clock_change_mid_run` | DVFS event invalidates energy comparison |

---

## Method Registry

| method_id | Type | Confidence | Backend |
|-----------|------|-----------|---------|
| `gpu_rapl_pp1_v1` | MEASURED | 1.0 | MSR PP1 (15-A) |
| `gpu_dynamic_baseline_v1` | CALCULATED | 0.90 | All (15-A) |
| `gpu_attribution_exclusive_v1` | CALCULATED | 1.0 | All (15-A) |
| `gpu_baseline_2sigma_v1` | MEASURED | 1.0 | All (15-A) |
| `gpu_phase_alignment_v1` | INFERRED | 0.70 | All (15-C) |
| `nvml_total_energy_v1` | MEASURED | 1.0 | NVML (15-B) |
| `nvml_power_integration_v1` | MEASURED | 0.85 | NVML fallback (15-B) |
| `dcgm_energy_v1` | MEASURED | 1.0 | DCGM (15-B) |
| `iokit_gpu_energy_v1` | MEASURED | 0.90 | IOKit (15-B) |
| `rocm_smi_energy_v1` | MEASURED | 0.85 | ROCm (15-B) |

---

## Limitations

1. **MSR PP1 no signals:** `source='msr_pp1'` samples have NULL for all
   signal columns (util, clocks, memory, temperature). Only energy_uj populated.

2. **Phase alignment proxy:** GPU phase energy (D8) is estimated from CPU
   phase fractions, not directly observed. Confidence 0.70. Will improve when
   NVML/DCGM signal columns enable direct GPU phase boundary detection.

3. **GN100 RAPL absent:** No RAPL equivalent on GB10 ARM platform. DCGM is
   the only path. This is a vendor product decision documented in
   arXiv:2605.27599 "The Energy Blind Spot."

4. **Apple IOKit requires sudo:** `powermetrics` on macOS requires elevated
   privileges. A-LEMS run on Stephen's machine must be launched with sudo
   or the IOKit backend falls back to NoneBackend.

5. **ROCm stub:** No AMD GPU hardware in lab. ROCmBackend interface is
   complete but untested. Activate and validate when AMD hardware joins.

---

## Cross-References

- `07-energy-readers-methodology.md` — CPU RAPL measurement, GPU PP1 section
- `01-measurement-methodology.md` — Overall A-LEMS measurement model
- `CHUNK15_GPU_REVISED.md` — Master spec for Chunk 15
- arXiv:2605.27599 — "The Energy Blind Spot" (LOCO Workshop paper)
