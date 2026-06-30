# Energy Chain Validator: Developer Guide

The energy chain validator is the component that answers a question no prior
AI energy measurement tool could answer: given a set of reported numbers, can
we prove from the measurement artifacts themselves that those numbers are
internally consistent? This document explains how the validator is built, how
it decides what to check on each platform, and how to extend it when new
platforms or new sensors arrive.

## Architecture Overview

The validator follows a strict two-layer design. The first layer,
`validate_energy_chain_v2.py`, collects raw facts from the database, runs
every conservation check, and emits a structured JSON document. It contains
no interpretive text. The second layer, `report_energy_chain.py`, reads that
JSON and produces the human-readable terminal report. This separation matters
because the same JSON can feed a paper table, a dashboard, an automated CI
check, or a reviewer's audit without changing the validation logic.

The supporting modules are:

- `platform_config.py` — all platform-specific knowledge in one place
- `confidence.py` — weighted confidence scoring (sample, calibration, source)
- `dag_validator.py` — walks the platform DAG and checks each conservation edge
- `proc_attr_validator.py` — CPU and GPU process attribution with assumption model
- `check_validators.py` — boundary, activity decomposition, phase partition, goal aggregation
- `scripts/etl/energy_derived_metrics_etl.py` — populates the `energy_derived_metrics` table

All seven files live in `scripts/` (flat, no sub-package). All new energy chain
files for new platforms go to the same flat directory. No nested packages.

## The Measurement DAG

The validator does not hardcode a fixed set of checks. It reads the
conservation structure from `PLATFORM_CONFIGS` in `platform_config.py`.
Each platform defines a list of DAG edges, where each edge specifies a parent
node, a list of child nodes, the conservation check name, whether the edge
crosses measurement source boundaries, and the relation type (exact equality
or bounded greater-than-or-equal).

The DAG for GN100 looks like this at runtime:

```
ML0: DC_INPUT  (board INA shunt monitor)
  └── ML1: PACKAGE  (SoC SPBM accumulator)
        ├── CPU_P   (SPBM performance core cluster)
        ├── CPU_E   (SPBM efficiency core cluster)
        ├── GPU_SPBM  (SPBM broad GPU rail)
        │     └── ML2: GPU_DCGM  (DCGM field 156, compute only)
        └── DLA     (integrated power rail)
```

The edges are:

- `ML1-INT`: pkg >= cpu_p + cpu_e + gpu_spbm + dla (intra-source, bounded)
- `ML0-ML1`: dc_input >= pkg (cross-source, bounded)
- `ML1-ML2`: gpu_spbm >= gpu_dcgm (cross-source, bounded)

For Intel x86 the DAG has a single intra-source edge:

- `ML1-INT`: pkg = core + uncore + dram (intra-source, exact)

The validator never uses if/else platform branches in the validation logic.
It reads `dag_edges` from the config and walks them. Adding a new platform
means adding a new entry to `PLATFORM_CONFIGS`, nothing else.

## Measurement Layers

ML stands for Measurement Layer. It describes the physical hierarchy of where
a sensor sits in the power delivery chain.

**ML0** is the board level. Sensors at this level are physical shunt monitors
on PCB traces, typically INA3221-class devices, that measure current flowing
through a trace and convert it to power. On GN100 they appear as power rail
sysfs files. They see everything: the SoC, the memory DIMMs, NVMe controllers,
USB/DisplayPort controllers, Ethernet PHY, fan headers, and all voltage
regulator losses. DC_INPUT and SYS_TOTAL are ML0 nodes.

**ML1** is the SoC level. On ARM/GN100, SPBM (Spark Board Management) exposes
SoC-internal energy accumulator registers via the sysfs IIO interface. These
registers are inside the chip and count energy consumed by named power domains:
the full package, the CPU performance cores, the CPU efficiency cores, the GPU
rail, and the DLA. On Intel x86, the equivalent is RAPL (Running Average Power
Limit), which exposes the PKG, PP0 (cores), PP1 (integrated GPU), and DRAM
domains via MSR registers. On Apple, IOKit provides package-level power without
DRAM. ML1 sensors are sampled at 10Hz on GN100 SPBM and at approximately
100Hz on Intel RAPL.

**ML2** is the accelerator level. On GN100, DCGM (Data Center GPU Manager)
exposes field 156, which is an internal GPU energy counter covering the compute
complex: streaming multiprocessors, the L2 cache, warp schedulers, register
files, and the crossbar connecting them. It does not cover the GPU memory
interface, the NVLink-C2C interconnect, or GPU voltage regulation overhead.
DCGM samples at 1Hz by default. On AMD platforms, ROCm-SMI provides an
equivalent counter. On Apple M1, there is no equivalent because the Neural
Engine and GPU share a unified memory architecture without separate counters.

## Conservation Check Design

There are three named conservation checks, each representing a different
quality of measurement:

**ML1-INT** (intra-source, bounded) checks that the sum of named SoC
sub-domains does not exceed the parent domain total. On GN100, this is
pkg >= cpu_p + cpu_e + gpu_spbm + dla. This is bounded rather than exact
because the Grace Blackwell SoC has domains that NVIDIA does not expose via
SPBM: the CMN-700 mesh interconnect, L3 cache slice power, and memory
controllers on the SoC side of the C2C bridge. These unmetered domains consume
roughly 30 percent of package energy on typical workloads. On Intel x86 with
full RAPL domain exposure (core + uncore + DRAM), this check is exact: the
sum equals the package total within the hardware's measurement tolerance
(typically less than 1 percent per Intel documentation). The ML1-INT check
uses a hard invariant: if sum(children) > parent by more than 1 mJ, it is a
FAIL indicating a counter wraparound or ETL bug.

**ML0-ML1** (cross-source, bounded) checks that the board-level DC input
energy is at least as large as the SoC package energy. The difference is
real energy consumed by off-die components. On GN100 this is typically
30 percent of DC input: the LPDDR5X memory DIMMs, NVMe storage, USB and
DisplayPort controllers, Ethernet PHY, fan headers, and all VRM conversion
losses including the AC-to-DC adapter. This check crosses sensor source
boundaries and therefore has higher inherent uncertainty than ML1-INT:
the board INA monitor and the SoC SPBM accumulator use different measurement
paths with different sampling rates and potentially different calibration.
A violation (dc_input < pkg) indicates sensor misalignment, sampling skew,
or a board monitor calibration issue.

**ML1-ML2** (cross-source, bounded) checks that the GPU broad rail (SPBM)
is at least as large as the GPU compute energy (DCGM). The difference is
the NVLink-C2C fabric energy, GPU memory interface energy, and GPU voltage
regulator overhead. For inference workloads on GN100, this ratio is typically
1.3x to 2x: DCGM field 156 captures SM compute and L2 cache while SPBM
captures those plus HBM3e PHY energy and C2C fabric energy. For
compute-saturated training kernels the ratio would be closer to 1.5x because
memory bandwidth is less dominant. A ratio above 10x would be anomalous and
warrants investigation.

## Confidence Scoring

Each conservation check receives a composite confidence score:

```
score = 0.4 x sample_score + 0.4 x calibration_score + 0.2 x source_score
```

The sample score rewards runs with more energy samples. At 10Hz SPBM, 100
samples represent a 10-second run, which is typical for a single agentic
task. Short runs with fewer than 20 samples get a low sample score because
the integration uncertainty is higher.

The calibration score compares this run's conservation residual to the
historical distribution of residuals from prior runs of the same workflow
type on the same platform. If the current run falls within one standard
deviation of the historical mean, it gets a perfect calibration score. A
run at three standard deviations gets a very low score and warrants
inspection. When fewer than five historical runs exist, the calibration score
is neutral (0.5) because there is no reliable basis for comparison. As the
corpus grows, calibration scores become more informative.

The source score is a static property of the measurement source, set in
`platform_config.py`. A single-source intra-die check like x86 ML1-INT gets
1.0 because the hardware accumulator design guarantees accuracy. A
cross-source check like ML0-ML1 gets 0.7 because board shunt monitors have
no published accuracy specification and the two sensors run on different
clocks. Adding a new platform means setting these source scores based on the
hardware documentation for that platform.

Confidence levels: HIGH is 0.8 and above, MEDIUM is 0.5 to 0.8, LOW is
below 0.5. A LOW confidence does not mean the check failed. It means the
measurement quality is insufficient to assert the result with high confidence,
typically because the run was too short or calibration history is sparse.

## Process Attribution Model

CPU attribution follows the tick-fraction method on all platforms:

```
cpu_fraction = process_ticks / total_ticks  (from /proc/{pid}/stat)
E_cpu_attributed = cpu_fraction x E_cpu_dynamic
```

On ARM, E_cpu_dynamic uses the SPBM cpu_p + cpu_e domain sum (CPU cores only,
excluding GPU). On x86, it uses pkg minus baseline. This keeps the attribution
definition consistent across platforms while using the best available signal
for each.

GPU attribution uses a separate assumption model. On GN100 with a single
active workload, GPU energy from DCGM is attributed entirely to the process
(fraction = 1.0, confidence = HIGH). The assumption model is explicit in the
JSON output. When multi-tenant GPU scenarios arise (MIG partitions, multiple
active processes), the model changes mode and drops confidence rather than
silently producing a wrong number. This design follows the framework principle
that every reported number must carry its provenance and confidence.

## Adding a New Platform

To add AMD (for Alex Flesher's machine) or Apple M1 (for Stephen Abkin's
machine), create a new entry in `PLATFORM_CONFIGS` in `platform_config.py`.
The entry needs:

- `measurement_layers`: what sensors exist, their interface, and their rate
- `dag_edges`: the conservation relationships between nodes, with check names
- `conservation_nodes`: which nodes participate in the DAG
- `diagnostic_nodes`: which nodes are shown for information but not checked
- `boundary_mode`: how pre/post task energy is computed
- `proc_attr_cpu_method` and `proc_attr_gpu_method`: attribution approaches
- `source_scores`: static accuracy scores per check

Then add energy fetchers in `dag_validator.py` under `resolve_node_energy()`
for the new platform string. The validation logic, confidence scoring, report
rendering, and all checks run automatically for the new platform without any
other changes.

For AMD, the relevant interface is `amd_energy` kernel module for CPU package
energy (similar to RAPL) and ROCm-SMI for GPU energy. The DAG would have
ML1-INT as pkg >= core + uncore + dram (or whatever AMD RAPL exposes) and
ML1-ML2 as amd_gpu_total >= rocm_compute if ROCm provides a compute-only
counter.

For Apple M1, the interface is IOKit for CPU package energy. There is no
DRAM domain (memory is unified). The DAG has a single ML1-INT edge with
a LIMITED provenance flag. There is no GPU energy counter equivalent to
DCGM on Apple Silicon.

## Running the Validator

```bash
# Validate latest experiment
PYTHONPATH=. python scripts/validate_energy_chain_v2.py --latest

# Validate specific experiment
PYTHONPATH=. python scripts/validate_energy_chain_v2.py --exp-id 144

# Validate specific run
PYTHONPATH=. python scripts/validate_energy_chain_v2.py --run-id 1378

# All valid experiments
PYTHONPATH=. python scripts/validate_energy_chain_v2.py --all-valid

# JSON output only (for programmatic use)
PYTHONPATH=. python scripts/validate_energy_chain_v2.py --latest --json-only

# Write JSON to file
PYTHONPATH=. python scripts/validate_energy_chain_v2.py --latest \
    --json-out /tmp/validation_144.json
```

## Populating the energy_derived_metrics Table

Before running `--all-valid`, populate the seven-domain decomposition table:

```bash
# Single run
PYTHONPATH=. python scripts/etl/energy_derived_metrics_etl.py --run-id 1378

# All runs (backfill)
PYTHONPATH=. python scripts/etl/energy_derived_metrics_etl.py --backfill-all
```

The ETL computes gpu_compute, nvlink_c2c, cpu_p, cpu_e, dla, soc_residual,
and board_overhead per run and writes them to `energy_derived_metrics`. On
non-SPBM platforms it skips silently.

## Status Codes

The validator uses five status codes, not just pass/fail:

- `OK` — conservation holds within tolerance
- `WARN` — conservation holds but residual is outside expected calibrated range
- `FAIL` — conservation violated; indicates a bug, counter wraparound, or sensor issue
- `N/A` — check not applicable on this platform or run type
- `DM` — data missing; ETL has not run or sensor was not available

A DM on ACTIVITY-DECOMP means `energy_attribution_etl.py` has not run for
that experiment. It is not a measurement failure. Run the ETL and revalidate.

A N/A on BOUNDARY on ARM means the SPBM accumulators are cumulative from
boot, so the pre/post task snapshots captured by the framework are raw
accumulator values rather than window deltas. The fix is to integrate
`power_rail_samples` over the pre/post time windows, which is deferred.
