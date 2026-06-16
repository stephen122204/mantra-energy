# Power Rail Schema

## Overview

A-LEMS extends the unified energy schema with a power rail time series capability
for platforms that expose instantaneous power channels without energy accumulators.
The GN100 SPBM hwmon driver exposes 14 channels: 4 energy accumulators (ground truth)
and 10 instantaneous power rails. This document describes the schema design and
measurement methodology for the power rail layer.

---

## Motivation

The SPBM driver on the NVIDIA GN100 exposes the following channel types:

Energy accumulators (hardware counters, ground truth):
pkg, cpu_p, cpu_e, gpu

Instantaneous power rails (no hardware accumulator):
dc_input, sys_total, soc_pkg, cpu_gpu, cpu_p, cpu_e, vcore, gpu, prereg, dla

Firmware limits (configuration, not measurements):
pl1, pl2, syspl1, syspl2

The unified energy schema stores accumulator deltas in energy_sample_domains.
A separate layer is needed for instantaneous power rails, captured at high
frequency and integrated by ETL to produce derived energy quantities.

---

## Design Principles

Three abstractions separate fundamentally different data types:

Energy accumulators go to energy_sample_domains as ground truth delta
measurements. Instantaneous power goes to power_rail_samples as a time series.
Device state (temperature, utilization, clock) goes to device_telemetry.
Power limits go to run_power_limits once per run as configuration metadata.

Power rail samples use their own timestamp and are decoupled from
energy_samples_v2. This allows independent sampling frequencies per stream.
Future platforms may sample power rails at 100 Hz and energy accumulators
at 10 Hz without schema changes.

---

## Schema

### power_rails (registry)

One row per measurable power rail. Platform-independent registry.
Adding a new platform requires only new rows here, no schema change.

| Column | Type | Description |
|--------|------|-------------|
| rail_id | INTEGER PK | Stable identifier |
| rail_name | TEXT | Human name (dc_input, gpu, dla etc) |
| device_type | TEXT | SOC, CPU, GPU, BOARD, ACCELERATOR |
| parent_rail_id | INTEGER | Topology parent (NULL for roots) |
| rail_kind | TEXT | POWER, ESTIMATE, CONTROL |
| hwmon_channel | TEXT | Informational (power7 etc) |
| hw_config_key | TEXT | Key in hw_config.json power_paths |
| notes | TEXT | Description |

### power_limits (registry)

One row per firmware limit type. Separate from power_rails because
limits are configuration values, not measurements.

| Column | Type | Description |
|--------|------|-------------|
| limit_id | INTEGER PK | Stable identifier |
| limit_name | TEXT | PL1, PL2, SYSPL1, SYSPL2 |
| description | TEXT | Human description |
| units | TEXT | mw |

### power_rail_samples (time series)

High-frequency instantaneous power readings. One row per rail per tick.

| Column | Type | Description |
|--------|------|-------------|
| rail_sample_id | INTEGER PK | Auto increment |
| run_id | INTEGER | FK runs |
| timestamp_ns | INTEGER | UTC nanoseconds |
| interval_ns | INTEGER | Duration since previous tick (NULL for first) |
| rail_id | INTEGER | FK power_rails |
| power_mw | REAL | Instantaneous milliwatts |

Indexed on (run_id, timestamp_ns) and (rail_id, run_id) for ETL queries.

### run_power_limits (run configuration)

Firmware limits captured once at experiment start. Not sampled at frequency.

| Column | Type | Description |
|--------|------|-------------|
| run_id | INTEGER PK part | FK runs |
| limit_id | INTEGER PK part | FK power_limits |
| value_mw | REAL | Limit value in milliwatts |

### power_limit_events (history)

Mid-run limit changes. Most runs have zero rows. Created now for
schema completeness. Populated only when firmware dynamically adjusts
limits (thermal throttle, driver intervention).

| Column | Type | Description |
|--------|------|-------------|
| event_id | INTEGER PK | Auto increment |
| run_id | INTEGER | FK runs |
| timestamp_ns | INTEGER | When change detected |
| limit_id | INTEGER | FK power_limits |
| old_value_mw | REAL | Previous value (NULL if unknown) |
| new_value_mw | REAL | New value |

---

## GN100 Power Rail Topology

```
dc_input  (rail_id=1, BOARD root)
    sys_total  (rail_id=2, BOARD)
        soc_pkg  (rail_id=3, SOC)
            cpu_gpu  (rail_id=4, SOC)
                cpu_p   (rail_id=5, CPU)
                cpu_e   (rail_id=6, CPU)
                vcore   (rail_id=7, CPU)
                gpu     (rail_id=8, GPU)
            prereg  (rail_id=9, BOARD)
            dla     (rail_id=10, ACCELERATOR)
```

Firmware limits (no topology parent, configuration only):
pl1, pl2 (SOC limits), syspl1, syspl2 (system limits)

---

## Power Rail Sampling

### PowerRailSampler

Reads all 10 POWER rails from SPBM hwmon at configurable frequency (default 10 Hz).
Paths sourced from hw_config.json spbm.power_paths — no hardcoded hwmon numbers.
Dynamic discovery ensures correctness across reboots.

Reads power limits once at start (run_power_limits). Limits are firmware constants
during normal operation. If limits change mid-run, power_limit_events captures the
event without retroactively sampling unchanged values.

Decoupled from SPBMSampler — independent thread, independent timestamp stream.
PAC-2 compliant: init failure falls back gracefully via try/except in energy_engine.

### Sampling frequency rationale

At 10 Hz, a 60-second experiment produces 600 samples per rail and 6000 rows
total in power_rail_samples. Storage cost is negligible. Integration error from
Riemann sum at 10 Hz is below 1% for slowly varying power signals (CPU/GPU
workloads with thermal time constants of seconds).

---

## ETL Integration

### Power Rail Sampling

```
power_rail_samples
    power_mw * interval_ns / 1e6
    -> energy_derived_metrics
```

Three derived metrics produced per run:

wall_energy_uj integrates dc_input rail (rail_id=1). This is the true energy
drawn from the wall for the experiment duration.

dla_energy_uj integrates dla rail (rail_id=10). Captures Deep Learning
Accelerator energy per experiment. Invisible to all other measurement tools.

board_overhead_uj = wall_energy_uj minus pkg accumulator energy_uj.
Captures board-level losses: voltage regulation, thermal management, networking.

### Conservation Invariant

```
dc_input_integrated ≈ pkg_accumulator + board_overhead
```

Deviation beyond 5% flags a measurement anomaly in runs.quality_flags.
This invariant is publishable as a validation experiment for the SIGMETRICS paper.

---

## Research Significance

The GN100 power rail schema produces three measurements not available from
any existing tool:

Wall energy per experiment from dc_input time-integrated at 10 Hz. This
enables true energy-to-solution measurement including board overhead.

DLA energy per experiment. The Deep Learning Accelerator rail (dla) is
invisible to NVML, DCGM, and nvidia-smi. A-LEMS captures it directly.

Board overhead energy = wall minus package. This separates compute energy
from infrastructure energy, a distinction critical for datacenter efficiency
analysis.

All three quantities are derived from hardware measurements, citeable via
methodology registry entries power_rail_sampling_v1 and power_rail_etl_v1.

---

## Migration Versions

| Version | Content |
|---------|---------|
| v57 | power_rails + power_limits registries with GN100 seed |
| v58 | power_rail_samples time series table |
| v59 | run_power_limits configuration table |
| v60 | power_limit_events history table (future-proof) |
