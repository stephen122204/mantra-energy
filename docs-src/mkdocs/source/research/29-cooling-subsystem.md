---
**Method ID:** cooling_sysfs_v1
**Schema version:** 66 (cooling_devices), 68 (cooling_samples)
**Platforms verified:** NVIDIA Grace GB10 (aarch64), Intel i7-1165G7 (x86_64)
**Status:** PRODUCTION
**Last updated:** 2026-06-19
---

# Cooling Device State Measurement

## Overview

Cooling device state measurement captures whether thermal throttling occurred
during an experiment run. A processor actively throttling (reducing frequency
to stay within thermal limits) consumes less energy per unit of computation
than one running at full speed. Without this measurement, a low EpG reading
is ambiguous: it may indicate an efficient workload or simply a thermally
throttled processor running below its rated frequency.

The Linux thermal framework exposes cooling devices via sysfs. Each device
has a `cur_state` integer: 0 means no throttling, higher values mean
increasingly aggressive throttling. `max_state` is the maximum throttle level
the driver supports.

### What This Method Captures

At experiment end, the current state of all registered cooling devices is
read from sysfs and stored in `cooling_samples`. This is a single end-of-run
snapshot, not per-second data. Cooling state changes on seconds-to-minutes
timescales; an end-of-run reading captures post-experiment thermal state
accurately enough for paper-level throttle detection.

---

## Platform Coverage

| Platform | Architecture | Cooling Devices | Source | Confidence | Status |
|----------|-------------|-----------------|--------|------------|--------|
| NVIDIA Grace GB10 | aarch64 | 20 CPU_FREQ_THROTTLE, 6 PCIE_LINK_THROTTLE, 1 FAN | cpufreq + pcie sysfs | 1.00 | VERIFIED |
| Intel i7-1165G7 | x86_64 | 8 CPU_FREQ_THROTTLE, 3 PCIE_LINK_THROTTLE, 1 POWER_CLAMP, 1 TCC_OFFSET | cpufreq + pcie sysfs | 1.00 | VERIFIED |
| AMD Ryzen | x86_64 | Similar to Intel | cpufreq sysfs | 1.00 | PENDING |
| Apple M1 Pro | arm64 | IOKit (future) | IOKit | TBD | PLANNED |
| Oracle Ampere | aarch64 | cpuidle sysfs | cpufreq sysfs | 1.00 | PLANNED |

### Confidence Score Justification

**cooling_sysfs_v1 (1.00):** `cur_state` is a direct kernel enum value with
no intermediate computation. The value read from sysfs is exactly what the
kernel thermal framework has set. There is no sampling uncertainty or
interpolation. The only limitation is timing: a snapshot taken at experiment
end may not reflect the peak throttle level during the experiment if the
processor returned to an unthrottled state before measurement. This is a
methodological choice (Option A), not a measurement accuracy issue.
Confidence remains 1.00 for the value as measured.

---

## Schema

### `cooling_devices` table (schema version 66)

| Column | Description |
|--------|-------------|
| `device_id` | Primary key |
| `machine_id` | Hostname (from `socket.gethostname().lower()`) |
| `device_type` | Kernel device type string |
| `device_index` | N in `/sys/class/thermal/cooling_deviceN/` |
| `max_state` | Maximum throttle level |
| `canonical_role` | Categorized role: `CPU_FREQ_THROTTLE`, `PCIE_LINK_THROTTLE`, `POWER_CLAMP`, `TCC_OFFSET`, `FAN` |
| `active` | 1 if device should be sampled |

### `cooling_samples` table (schema version 68)

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | INTEGER FK | References `runs.id` |
| `device_id` | INTEGER FK | References `cooling_devices.device_id` |
| `timestamp_ns` | INTEGER | Unix nanoseconds at time of snapshot |
| `cur_state` | INTEGER | Current throttle level (0 = no throttle) |
| `quality_flag` | TEXT | `VALID`, `OUT_OF_RANGE`, `READ_FAILED` |
| `invalid_reason` | TEXT | Populated when quality_flag is not VALID |
| `global_run_id` | TEXT | Federation identifier (NULL for single-machine experiments) |

### Quality Flags

`VALID`: `cur_state >= 0` and sysfs read succeeded.

`OUT_OF_RANGE`: `cur_state < 0`. Observed on NVIDIA Grace GB10 for one
cooling device reporting `cur_state = -231`. This is a kernel anomaly, not
a measurement error. The value is recorded rather than discarded because the
anomaly itself is scientifically interesting for long-running stability analysis.

`READ_FAILED`: sysfs path could not be read (driver unloaded, path missing).
`cur_state` stored as 0. `invalid_reason` contains the exception string.

---

## Method Provenance

| Field | Value |
|-------|-------|
| Method ID | `cooling_sysfs_v1` |
| Layer | `os` |
| Provenance | `MEASURED` |
| Confidence | 1.00 |
| Source | `/sys/class/thermal/cooling_deviceN/cur_state` |

Cooling devices are discovered at machine setup time by the thermal discovery
subsystem and registered in `cooling_devices`. At experiment save time,
`CoolingRepository.snapshot_cooling_state()` reads `cur_state` for each
registered device and writes one row per device to `cooling_samples`.

---

## Query Reference

**1. Throttle detection for a single run**

```sql
SELECT cd.canonical_role, cd.device_type, cd.device_index,
       cs.cur_state, cd.max_state, cs.quality_flag
FROM cooling_samples cs
JOIN cooling_devices cd ON cs.device_id = cd.device_id
WHERE cs.run_id = <run_id>
  AND cd.canonical_role IN ('CPU_FREQ_THROTTLE', 'POWER_CLAMP', 'TCC_OFFSET')
ORDER BY cd.canonical_role, cd.device_index;
```

Expected output: rows with `cur_state = 0` at idle. Under heavy load or
sustained LLM inference, `cur_state > 0` for CPU frequency throttle devices.

**2. Count throttled runs across all experiments**

```sql
SELECT COUNT(DISTINCT cs.run_id) as throttled_run_count
FROM cooling_samples cs
JOIN cooling_devices cd ON cs.device_id = cd.device_id
WHERE cd.canonical_role IN ('CPU_FREQ_THROTTLE', 'POWER_CLAMP', 'TCC_OFFSET')
  AND cs.quality_flag = 'VALID'
  AND cs.cur_state > 0;
```

**3. Cooling state distribution per canonical role**

```sql
SELECT cd.canonical_role,
       cs.cur_state,
       COUNT(*) as occurrences
FROM cooling_samples cs
JOIN cooling_devices cd ON cs.device_id = cd.device_id
WHERE cs.run_id IN (SELECT id FROM runs WHERE run_type = 'agentic')
  AND cs.quality_flag = 'VALID'
GROUP BY cd.canonical_role, cs.cur_state
ORDER BY cd.canonical_role, cs.cur_state;
```

**4. Verify cooling_samples has rows after experiment**

```sql
SELECT COUNT(*) as total_rows,
       COUNT(DISTINCT device_id) as devices_sampled,
       SUM(CASE WHEN quality_flag = 'VALID' THEN 1 ELSE 0 END) as valid_rows
FROM cooling_samples
WHERE run_id = (SELECT MAX(id) FROM runs);
```

Expected (NVIDIA Grace GB10): ~27 total rows, 27 devices, 26 VALID, 1 OUT_OF_RANGE.
Expected (Intel i7-1165G7): ~13 total rows, 13 devices, 13 VALID.

**5. Runs with any throttling detected**

```sql
SELECT r.id, r.run_type, r.created_at,
       MAX(cs.cur_state) as max_throttle_state,
       cd.canonical_role
FROM cooling_samples cs
JOIN runs r ON cs.run_id = r.id
JOIN cooling_devices cd ON cs.device_id = cd.device_id
WHERE cd.canonical_role = 'CPU_FREQ_THROTTLE'
  AND cs.quality_flag = 'VALID'
  AND cs.cur_state > 0
GROUP BY r.id, r.run_type, r.created_at, cd.canonical_role
ORDER BY r.created_at DESC;
```

---

## Verification

```bash
# After running one experiment with --save-db:

# Step 1: confirm cooling_samples has rows
RUN_ID=$(sqlite3 $DB "SELECT MAX(id) FROM runs;")
sqlite3 $DB "
SELECT COUNT(*), COUNT(DISTINCT device_id)
FROM cooling_samples WHERE run_id = $RUN_ID;"
# GN100: 27 rows, 27 devices
# UBUNTU2505: 13 rows, 13 devices

# Step 2: check quality flag distribution
sqlite3 $DB "
SELECT quality_flag, COUNT(*) FROM cooling_samples
WHERE run_id = $RUN_ID GROUP BY quality_flag;"
# GN100: VALID=26, OUT_OF_RANGE=1 (cooling_device26 cur_state=-231)

# Step 3: confirm no throttling at idle
sqlite3 $DB "
SELECT cd.canonical_role, cs.cur_state
FROM cooling_samples cs
JOIN cooling_devices cd ON cs.device_id = cd.device_id
WHERE cs.run_id = $RUN_ID AND cs.quality_flag = 'VALID'
ORDER BY cd.canonical_role;" | head -10
# Expected: all cur_state = 0 at idle

# Step 4: confirm cooling_devices registered
sqlite3 $DB "
SELECT COUNT(*), canonical_role FROM cooling_devices
WHERE machine_id = '$(hostname)' AND active = 1
GROUP BY canonical_role;"
```

---

## Known Limitations

**End-of-run snapshot only:** This implementation captures cooling device
state once at experiment end. If the processor throttled during the experiment
but recovered before the snapshot, throttling is not detected. For guaranteed
throttle detection, per-second sampling (Option B from SPEC_16D2a) is needed.
Option B is deferred to a future implementation revision.
Workaround: experiments that use the `thermal_throttle_flag` column in `runs`
(populated by ThermalAggregator) have a complementary signal from thermal
zone temperatures.

**NEGATIVE cur_state anomaly on GN100:** One cooling device on the NVIDIA
Grace GB10 platform reports `cur_state = -231`. This is stored with
`quality_flag = 'OUT_OF_RANGE'` rather than discarded. The root cause is
under investigation. Downstream queries should filter on
`quality_flag = 'VALID'` for throttle analysis.

**Apple M1 Pro:** IOKit cooling device enumeration is not implemented.
`snapshot_cooling_state()` returns 0 on macOS because `/sys/class/thermal/`
does not exist. No data loss — method returns gracefully.

**Fan speed:** Cooling devices with `canonical_role = 'FAN'` report
`cur_state` as fan speed level (not RPM). Cross-machine comparison of fan
speed levels is not meaningful — use only for same-machine throttle trending.
