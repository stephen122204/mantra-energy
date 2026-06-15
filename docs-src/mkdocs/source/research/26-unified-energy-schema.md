# Unified Energy Schema

## Overview

A-LEMS measures energy across multiple hardware platforms: Intel x86 with RAPL,
NVIDIA Grace with SPBM spark_hwmon, AMD EPYC with amd_energy, Apple M1 with IOKit,
and shared cluster GPUs via nvidia-smi. Each platform has a different set of
energy domains and measurement interfaces.

The unified energy schema accommodates all platforms with zero schema changes
when new hardware arrives. Existing data (4.9M rows in energy_samples from
UBUNTU2505) is never modified. New platforms write to the normalized schema.
The v_energy view unifies both transparently for all queries.

---

## Core Tables

### energy_sources

Maps measurement interfaces to confidence scores and provenance.
One row per hardware interface (RAPL, SPBM, DCGM, NVML, IOKit, etc).
Adding a new platform requires only a new row here.

| source_id | name       | confidence | provenance |
|-----------|-----------|-----------|-----------|
| 1         | RAPL       | 1.00       | MEASURED   |
| 2         | SPBM       | 1.00       | MEASURED   |
| 3         | NVML       | 1.00       | MEASURED   |
| 4         | DCGM       | 1.00       | MEASURED   |
| 5         | IOKIT      | 0.90       | MEASURED   |
| 6         | AMD_ENERGY | 1.00       | MEASURED   |
| 7         | SMI_INTEG  | 0.85       | INFERRED   |
| 8         | MSR_PP1    | 0.95       | MEASURED   |

### energy_domains

Hierarchical domain registry with multiple independent roots.
PACKAGE is not universal — NETWORK, ACCELERATOR, STORAGE are separate roots.

```
PACKAGE (root)
    CORE, UNCORE, DRAM         Intel x86
    CPU_P, CPU_E, GPU          ARM Grace (GN100)
    CCD0, CCD1, IODIE          AMD EPYC

UNIFIED (root)
    CPU_APPLE, GPU_APPLE       Apple M1/M2

NETWORK (root)
    NVLINK_C2C                 GN100 die-to-die interconnect
    NVLINK, RDMA, INFINIBAND   discrete GPU / cluster

ACCELERATOR (root)
    DLA                        GN100 SPBM channel
    NPU                        future

STORAGE (root)
    NVME                       future
```

### energy_samples_v2

One row per measurement event. Narrow by design (hot path during experiments).

```
sample_id     PK local integer
run_id        FK runs
global_run_id NULL until sync — populated by sync_client at sync time
source_id     FK energy_sources (which interface was read)
timestamp_ns  UTC nanoseconds
interval_ns   sample duration
```

### energy_sample_domains

Raw domain energy values. MEASURED only — never derived quantities.
Two sources measuring the same domain produce two rows.

```
sample_id + domain_id + source_id  →  composite PK
energy_uj  raw µJ value from hardware
run_id     denormalized for sync_client fetch
```

**Example: GN100 GPU domain has two rows per sample:**

| sample_id | domain_id | source_id | energy_uj |
|-----------|-----------|-----------|-----------|
| 1023      | 7 (GPU)   | 2 (SPBM)  | 5200      |
| 1023      | 7 (GPU)   | 4 (DCGM)  | 4010      |

ETL subtracts these to derive NVLink-C2C energy (stored in energy_derived_metrics).

### energy_derived_metrics

ETL-computed quantities only. Never raw measurements.
Cleanly separates what was measured from what was calculated.

```
metric_id           PK
run_id              FK runs
sample_id           nullable (NULL = run-level aggregate)
metric_name         TEXT e.g. 'NVLINK_C2C'
value_uj            computed value
derivation_formula  e.g. 'SPBM_GPU - DCGM_GPU' (citeable in paper)
source_ids_used     comma-separated e.g. '2,4'
```

### device_telemetry

Instantaneous device state: power, temperature, utilization, clock.
Replaces gpu_samples for new platforms (gpu_samples stays untouched).

```
device_type  'GPU', 'SOC', 'CPU', 'NETWORK', 'STORAGE'
power_mw     instantaneous milliwatts
energy_uj    nullable — NULL for SMI_INTEG (integrated at ETL)
dc_input_mw  wall input power from SPBM dc_input channel (SOC only)
```

### platform_domain_relationships

Platform topology: which domains contribute to which root on each machine.
This is where contributes_to_parent lives — it is a platform fact, not a domain fact.

**Example: same GPU domain, different topology on different machines:**

| hardware_hash | source | domain | parent  | contributes |
|---------------|--------|--------|---------|-------------|
| gn100_hash    | SPBM   | GPU    | PACKAGE | 1 (unified) |
| alex_hash     | NVML   | GPU    | NULL    | 0 (PCIe)    |

---

## v_energy View

Single query surface for paper macros and student queries.
Never query raw tables directly.

```sql
SELECT source_name, domain_name, AVG(energy_uj)
FROM v_energy
WHERE run_id = ?
GROUP BY source_name, domain_name;
```

Works identically for UBUNTU2505 legacy runs (RAPL) and GN100 new runs (SPBM).

---

## NVLink-C2C Measurement

The ISPASS 2027 paper measures NVLink-C2C die-to-die power on GN100.

**Measurement stack:**

```
SPBM GPU rail   =  GPU compute + HBM + NVLink-C2C
DCGM field 156  =  GPU compute only
NVLink-C2C      =  SPBM GPU - DCGM GPU
```

**At idle (validated 2026-06-14):**

```
SPBM GPU:   ~5,354 mW
DCGM GPU:   ~4,362 mW
NVLink-C2C: ~992 mW
```

ETL produces NVLINK_C2C rows in energy_derived_metrics.
Paper macros query energy_derived_metrics directly.

---

## Conservation Invariant

```sql
SELECT v.run_id, SUM(v.energy_uj) AS leaf_sum, r.pkg_energy_uj
FROM v_energy v
JOIN runs r ON r.run_id = v.run_id
JOIN hardware_config hc ON hc.hw_id = r.hw_id
JOIN platform_domain_relationships pdr
    ON pdr.hardware_hash = hc.hardware_hash
   AND pdr.contributes_to_parent = 1
   AND pdr.parent_domain_id = 1
WHERE v.domain_name = pdr.domain_name
GROUP BY v.run_id;
```

Works for all platforms. No code change when new platform arrives.

---

## What Never Changes When New Platform Arrives

| New thing            | What to add              | Schema change |
|---------------------|--------------------------|---------------|
| New CPU backend      | Row in energy_sources    | None          |
| New GPU backend      | Row in energy_sources    | None          |
| New domain (HBM3)   | Row in energy_domains    | None          |
| New platform         | Rows in platform_domain_relationships | None |
| New derived metric   | ETL writing to energy_derived_metrics | None |
