# Thermal and Cooling Subsystem

---
**Method IDs:** `thermal_zone_sysfs_v2`, `cooling_sysfs_v1`
**Schema versions:** 65 (thermal_zones), 66 (cooling_devices), 67 (thermal_samples_v2), 68 (cooling_samples), 69 (v_thermal_cpu)
**Platforms verified:** NVIDIA Grace GB10 (aarch64), Intel i7-1165G7 (x86_64)
**Status:** PRODUCTION
**Last updated:** 2026-06-19
---

## Overview

The A-LEMS thermal subsystem measures CPU package temperature and cooling
device state at 1Hz during every experiment. It supports three research goals:

**Goal 1 — Energy attribution:** Temperature elevation increases leakage
current and dynamic power. Thermal data enables post-hoc attribution of
energy overhead to thermal conditions rather than workload alone.

**Goal 2 — Hardware reliability research:** Thermal stress cycles accelerate
electromigration and rare earth metal degradation in semiconductor devices.
Per-zone 1Hz samples provide the time series needed for lifetime modeling.

**Goal 3 — Cross-platform comparison:** Agentic AI workloads are compared
across Intel, AMD, and NVIDIA Grace platforms. A unified thermal schema enables
queries that do not require platform-conditional logic.

The subsystem replaces two broken prior implementations: `SensorReader` which
returned empty results on NVIDIA Grace, and turbostat-based temperature
aggregation which produced zeros on all platforms after turbostat version
changes broke the `package_temp` field.

---

## Platform Coverage

| Platform | Architecture | Primary Zone | Canonical Role | Confidence | Status |
|----------|-------------|-------------|---------------|------------|--------|
| NVIDIA Grace GB10 | aarch64 | acpitz (7 zones) | SOC | 0.92 | VERIFIED |
| Intel i7-1165G7 | x86\_64 | x86\_pkg\_temp | CPU\_PACKAGE | 0.92 | VERIFIED |
| AMD Ryzen (RTX 2070 Super) | x86\_64 | k10temp | CPU\_PACKAGE | 0.92 | PENDING |
| Apple M1 Pro | arm64 | IOKit (future) | CPU\_PACKAGE | TBD | PLANNED |

### NVIDIA Grace GB10 (aarch64)

All 7 thermal zones report type `acpitz` (ACPI thermal zone). They measure
different locations on the Grace SoC but the kernel assigns identical type
strings. Zone identity uses `(zone_type, zone_index)` — stable across reboots.
Package temperature is derived as `MAX(all 7 zones)` per timestamp, giving
peak SoC temperature at each sample point.

Idle temperature range: 40-45°C. Under LLM inference: 50-65°C typical.

One cooling device anomaly: `cooling_device26` reports `cur_state = -231`
(kernel bug). This reading is stored as `OUT_OF_RANGE` and never triggers
throttle detection.

### Intel i7-1165G7 (x86\_64)

Zone `x86_pkg_temp` (CPU\_PACKAGE role) is the reliable package temperature
source. Zone `TCPU` reports -273.15°C (absolute zero — broken sensor on this
hardware). The broken zone is stored as `OUT_OF_RANGE` and excluded from
all aggregations. Intel DPTF aggregate zone (`INT3400 Thermal`) is classified
as `DPTF_AGGREGATE` and also excluded from package temperature calculation.

Idle temperature range: 46-52°C.

Two PCIe cooling devices show `cur_state = 2 / max_state = 2` at idle —
fully throttled. This is expected behavior on this platform and does not
indicate active CPU throttling during experiments.

---

## Schema

### thermal_zones (registry)

One row per unique thermal zone per machine. Identity is stable across reboots.

| Column | Type | Description |
|--------|------|-------------|
| zone\_id | INTEGER PK | Stable identity |
| machine\_id | TEXT | From `socket.gethostname()` |
| zone\_type | TEXT | Kernel type string (x86\_pkg\_temp, acpitz, etc.) |
| zone\_index | INTEGER | From sysfs path index — part of stable identity |
| canonical\_role | TEXT | CPU\_PACKAGE, SOC, GPU, WIFI, etc. |
| source\_subsystem | TEXT | thermal\_zone (sysfs) |
| first\_seen | TEXT | ISO timestamp of first discovery |
| last\_seen | TEXT | Updated at each platform init |
| active | INTEGER | 1 = present at last init, 0 = disappeared |

### cooling_devices (registry)

One row per unique cooling actuator per machine. Same identity pattern as thermal\_zones.

| Column | Type | Description |
|--------|------|-------------|
| device\_id | INTEGER PK | Stable identity |
| machine\_id | TEXT | From `socket.gethostname()` |
| device\_type | TEXT | Kernel type string (Fan, Processor, etc.) |
| device\_index | INTEGER | From sysfs path index |
| canonical\_role | TEXT | FAN, CPU\_FREQ\_THROTTLE, PCIE\_LINK\_THROTTLE, etc. |
| max\_state | INTEGER | Maximum throttle level |
| active | INTEGER | 1 = present at last init |

### thermal_samples_v2 (1Hz raw samples)

One row per zone per 1Hz tick. All zones sampled including invalid ones.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | |
| run\_id | INTEGER | FK to runs |
| zone\_id | INTEGER | FK to thermal\_zones |
| timestamp\_ns | INTEGER | Epoch nanoseconds |
| temp\_celsius | REAL | Raw reading — may be invalid |
| quality\_flag | TEXT | VALID, OUT\_OF\_RANGE, READ\_FAILED, MISSING |
| invalid\_reason | TEXT | Human-readable cause for non-VALID |
| global\_run\_id | TEXT | Cross-machine correlation (NULL until populated) |

### cooling_samples (1Hz raw samples)

One row per cooling device per 1Hz tick.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | |
| run\_id | INTEGER | FK to runs |
| device\_id | INTEGER | FK to cooling\_devices |
| timestamp\_ns | INTEGER | Epoch nanoseconds |
| cur\_state | INTEGER | Raw kernel state value |
| quality\_flag | TEXT | VALID, OUT\_OF\_RANGE, READ\_FAILED, MISSING |
| invalid\_reason | TEXT | Cause for non-VALID (e.g. NEGATIVE\_STATE=-231) |

### v_thermal_cpu (view)

Filters `thermal_samples_v2` to CPU\_PACKAGE and SOC zones, VALID readings only.
Use this view for all temperature analysis — never query `thermal_samples_v2` directly
for temperature unless you need invalid readings for audit purposes.

```sql
-- Definition
SELECT ts.run_id, ts.timestamp_ns, ts.temp_celsius AS cpu_temp,
       tz.machine_id, tz.zone_id, tz.zone_type, tz.canonical_role
FROM thermal_samples_v2 ts
JOIN thermal_zones tz ON ts.zone_id = tz.zone_id
WHERE tz.canonical_role IN ('CPU_PACKAGE', 'SOC')
  AND ts.quality_flag = 'VALID'
  AND tz.active = 1;
```

---

## Canonical Roles

### Thermal zone roles

| Role | Platforms | Included in package\_temp\_celsius |
|------|-----------|----------------------------------|
| CPU\_PACKAGE | Intel (x86\_pkg\_temp), AMD (k10temp) | Yes — direct |
| SOC | NVIDIA Grace (acpitz) | Yes — MAX per timestamp |
| CPU\_DIE | Intel (TCPU) | Only if no CPU\_PACKAGE or SOC found |
| GPU | AMD (amdgpu), Tegra | No |
| DPTF\_AGGREGATE | Intel (INT3400 Thermal) | No |
| DPTF\_SENSOR | Intel (SEN1-SEN4) | No |
| WIFI | All (iwlwifi\_1) | No |
| STORAGE | All (nvme) | No |
| OTHER | Unknown types | No |

### Cooling device roles

| Role | Example | Triggers throttle detection |
|------|---------|---------------------------|
| CPU\_FREQ\_THROTTLE | Processor (Linux) | Yes |
| POWER\_CLAMP | intel\_powerclamp | Yes |
| TCC\_OFFSET | TCC Offset (Intel) | Yes |
| PCIE\_LINK\_THROTTLE | PCIe\_Port\_Link\_Speed\_\* | No |
| FAN | Fan | No |
| OTHER | Unknown | No |

---

## Query Reference

All queries use `$DB` as the path to `experiments.db`. Replace `<hostname>`
with the output of `socket.gethostname()` for the target machine.

### 1. Inspect registered thermal zones for a machine

Answers: what zones are active on this platform and what roles were assigned?

```sql
SELECT zone_id, zone_type, zone_index, canonical_role, active, first_seen
FROM thermal_zones
WHERE machine_id = '<hostname>'
ORDER BY zone_index;
```

Expected on NVIDIA Grace GB10: 7 rows, all type=acpitz, role=SOC.
Expected on Intel i7-1165G7: 8 rows, one x86\_pkg\_temp (CPU\_PACKAGE),
one TCPU (CPU\_DIE, OUT\_OF\_RANGE at sample time).

### 2. Package temperature for the most recent run

Answers: what was the CPU temperature profile during the last experiment?

```sql
-- NVIDIA Grace GB10 (SOC role — MAX across zones per tick)
SELECT MAX(cpu_temp) as soc_temp_c, timestamp_ns
FROM v_thermal_cpu
WHERE run_id = (SELECT MAX(run_id) FROM runs)
  AND canonical_role = 'SOC'
GROUP BY timestamp_ns
ORDER BY timestamp_ns;

-- Intel / AMD (CPU_PACKAGE role — direct reading)
SELECT cpu_temp, timestamp_ns
FROM v_thermal_cpu
WHERE run_id = (SELECT MAX(run_id) FROM runs)
  AND canonical_role = 'CPU_PACKAGE'
ORDER BY timestamp_ns;
```

### 3. Temperature summary for a run (matches runs table columns)

Answers: what are the aggregate temperature stats for run N?

```sql
WITH cpu_temps AS (
    SELECT MAX(cpu_temp) as tick_temp, timestamp_ns
    FROM v_thermal_cpu
    WHERE run_id = ?
      AND canonical_role = 'SOC'   -- change to 'CPU_PACKAGE' for Intel/AMD
    GROUP BY timestamp_ns
)
SELECT
    AVG(tick_temp)               AS package_temp_celsius,
    MIN(tick_temp)               AS min_temp_c,
    MAX(tick_temp)               AS max_temp_c,
    MAX(tick_temp) - MIN(tick_temp) AS thermal_delta_c
FROM cpu_temps;
```

### 4. Quality flag distribution for a run

Answers: how many readings were invalid and why?

```sql
SELECT quality_flag, invalid_reason, COUNT(*) as count
FROM thermal_samples_v2
WHERE run_id = ?
GROUP BY quality_flag, invalid_reason
ORDER BY count DESC;
```

Expected on Intel i7-1165G7: TCPU zone shows OUT\_OF\_RANGE with reason
`TEMP=-273.1C_RANGE=[-10.0,125.0]` for every sample.
Expected on NVIDIA Grace GB10: cooling\_device26 shows OUT\_OF\_RANGE in
cooling\_samples with reason `NEGATIVE_STATE=-231`.

### 5. Throttle detection for a run

Answers: was the CPU thermally throttled during this experiment?

```sql
SELECT COUNT(*) as throttle_ticks
FROM cooling_samples cs
JOIN cooling_devices cd ON cs.device_id = cd.device_id
WHERE cs.run_id = ?
  AND cd.canonical_role IN ('CPU_FREQ_THROTTLE', 'POWER_CLAMP', 'TCC_OFFSET')
  AND cs.quality_flag = 'VALID'
  AND cs.cur_state > 0;
-- 0 = no throttle, >0 = throttled for that many 1Hz ticks
```

### 6. Per-zone heating rate under inference load

Answers: which zone heats fastest when LLM inference starts?
Applies to: NVIDIA Grace GB10 (multiple SOC zones).

```sql
SELECT tz.zone_type, tz.zone_index,
       MIN(ts.temp_celsius) AS start_temp_c,
       MAX(ts.temp_celsius) AS peak_temp_c,
       MAX(ts.temp_celsius) - MIN(ts.temp_celsius) AS delta_c
FROM thermal_samples_v2 ts
JOIN thermal_zones tz ON ts.zone_id = tz.zone_id
WHERE ts.run_id = ?
  AND ts.quality_flag = 'VALID'
  AND tz.canonical_role = 'SOC'
GROUP BY ts.zone_id
ORDER BY delta_c DESC;
```

### 7. Cross-run thermal trend (degradation timeline)

Answers: does the platform run hotter over time as hardware ages?
Use for hardware degradation research and rare earth metal lifetime modeling.

```sql
SELECT r.run_id, r.created_at,
       AVG(ts.temp_celsius)  AS avg_temp_c,
       MAX(ts.temp_celsius)  AS peak_temp_c,
       COUNT(*)              AS sample_count
FROM thermal_samples_v2 ts
JOIN runs r ON ts.run_id = r.run_id
JOIN thermal_zones tz ON ts.zone_id = tz.zone_id
WHERE tz.machine_id = '<hostname>'
  AND tz.canonical_role IN ('CPU_PACKAGE', 'SOC')
  AND ts.quality_flag = 'VALID'
GROUP BY r.run_id
ORDER BY r.run_id;
```

### 8. Thermal stress cycle count (degradation research)

Answers: how many measurement ticks exceeded a given temperature threshold?
Input to hardware lifetime models.

```sql
SELECT tz.zone_type, tz.zone_index, tz.canonical_role,
       COUNT(*) AS ticks_above_threshold,
       MAX(ts.temp_celsius) AS absolute_peak_c
FROM thermal_samples_v2 ts
JOIN thermal_zones tz ON ts.zone_id = tz.zone_id
WHERE tz.machine_id = '<hostname>'
  AND ts.quality_flag = 'VALID'
  AND ts.temp_celsius > 70.0   -- adjust threshold per platform
GROUP BY ts.zone_id
ORDER BY ticks_above_threshold DESC;
```

---

## Verification

Run these commands after applying migrations and running one experiment.
Replace `$DB` with the correct path for your platform.

```bash
# 1. Migrations applied
sqlite3 $DB ".tables" | tr ' ' '\n' | \
  grep -E 'thermal_zones|cooling_devices|thermal_samples_v2|cooling_samples'
# Expected: all 4 tables listed

# 2. Zones registered
sqlite3 $DB \
  "SELECT zone_id, zone_type, zone_index, canonical_role, active FROM thermal_zones;"
# NVIDIA Grace GB10: 7 rows, all acpitz/SOC
# Intel i7-1165G7: 8 rows, one x86_pkg_temp/CPU_PACKAGE

# 3. Cooling devices registered
sqlite3 $DB \
  "SELECT COUNT(*), canonical_role FROM cooling_devices GROUP BY canonical_role;"
# NVIDIA Grace GB10: 20 CPU_FREQ_THROTTLE, 6 PCIE_LINK_THROTTLE, 1 FAN
# Intel i7-1165G7: 8 CPU_FREQ_THROTTLE, 3 PCIE_LINK_THROTTLE, 1 POWER_CLAMP, 1 TCC_OFFSET

# 4. Thermal samples flowing
sqlite3 $DB \
  "SELECT COUNT(*), COUNT(DISTINCT zone_id), AVG(temp_celsius)
   FROM thermal_samples_v2
   WHERE run_id = (SELECT MAX(run_id) FROM runs)
     AND quality_flag = 'VALID';"
# Expected: N*zones rows, avg_temp 40-65°C depending on platform and load

# 5. v_thermal_cpu view working
sqlite3 $DB \
  "SELECT COUNT(*), AVG(cpu_temp), MIN(cpu_temp), MAX(cpu_temp)
   FROM v_thermal_cpu
   WHERE run_id = (SELECT MAX(run_id) FROM runs);"
# Expected: non-zero count, realistic temp range

# 6. runs table populated (not zero)
sqlite3 $DB \
  "SELECT package_temp_celsius, start_temp_c, max_temp_c, min_temp_c, thermal_delta_c
   FROM runs ORDER BY run_id DESC LIMIT 3;"
# Expected: all values non-zero, package_temp_celsius 40-65°C

# 7. Old thermal_samples not broken (regression check)
sqlite3 $DB \
  "SELECT COUNT(*) FROM thermal_samples
   WHERE run_id = (SELECT MAX(run_id) FROM runs);"
# Expected: same number of samples as before (no regression)

# 8. Quality flag distribution
sqlite3 $DB \
  "SELECT quality_flag, COUNT(*) FROM thermal_samples_v2
   GROUP BY quality_flag ORDER BY COUNT(*) DESC;"
# Expected: mostly VALID, OUT_OF_RANGE for known broken sensors
```

---

## Known Limitations

- **ACPI polling lag:** ACPI thermal zones on NVIDIA Grace GB10 poll at
  ~100ms intervals. Temperature transitions faster than 100ms are missed.
  Workaround: accept as measurement characteristic. For sub-100ms thermal
  events use hardware performance counters (not available on this platform).

- **No per-cluster resolution on Grace:** All 7 acpitz zones report package-level
  temperature. P-core (Cortex-X925) and E-core (Cortex-A725) temperatures
  cannot be separated. Workaround: None — accept SOC-level granularity.

- **GPU temperature not included:** GPU temperature on NVIDIA Grace GB10 is
  available via DCGM and nvidia-smi but is NOT included in thermal\_samples\_v2.
  GPU thermal data lives in the DCGM backend outputs.
  Workaround: Join with gpu\_samples for GPU temperature.

- **Apple M1 Pro not supported:** No `/sys/class/thermal/` on macOS. Discovery
  returns empty list. IOKit thermal path planned for a future implementation.
  Workaround: thermal columns NULL on Apple M1 Pro platform.

- **TCC Offset interpretation:** Intel TCC Offset `cur_state=10` means the
  throttle trigger point is set 10°C below Tjmax, not that throttling is
  occurring. The device is classified as TCC\_OFFSET and included in throttle
  detection for completeness, but `cur_state > 0` for TCC\_OFFSET does not
  mean active throttling — it means the offset is configured.
  Workaround: use CPU\_FREQ\_THROTTLE role only for reliable throttle detection.

---

## v_thermal_cpu View — Derivation and Platform Logic

### What the view does

`v_thermal_cpu` filters `thermal_samples_v2` to only the zones relevant for
CPU package temperature reporting. It joins with `thermal_zones` to apply
two filters:

1. `canonical_role IN ('CPU_PACKAGE', 'SOC')` — only CPU-relevant zones
2. `quality_flag = 'VALID'` — only readings within [-10, 125]°C
3. `active = 1` — only zones found at last discovery

The view returns raw rows — one row per zone per tick. It does NOT average
or aggregate. Aggregation is the responsibility of `ThermalAggregator` and
`aggregate_run_stats()`.

### Per-platform derivation logic

**Intel i7-1165G7 (x86\_64) — CPU\_PACKAGE role:**

One zone (`x86_pkg_temp`) has `canonical_role = CPU_PACKAGE`. The view
returns one row per 1Hz tick. `ThermalAggregator` computes:

```sql
SELECT cpu_temp FROM v_thermal_cpu
WHERE run_id = ? AND canonical_role = 'CPU_PACKAGE'
ORDER BY timestamp_ns
```

`package_temp_celsius = AVG(cpu_temp)` — direct average of package readings.

**NVIDIA Grace GB10 (aarch64) — SOC role:**

Seven zones all have `canonical_role = SOC`. The view returns 7 rows per
1Hz tick (one per zone). `ThermalAggregator` computes:

```sql
SELECT MAX(cpu_temp) FROM v_thermal_cpu
WHERE run_id = ? AND canonical_role = 'SOC'
GROUP BY timestamp_ns
ORDER BY timestamp_ns
```

`package_temp_celsius = AVG(MAX per tick)` — average of peak SoC temperature
at each sample point. MAX() is used because all 7 acpitz zones measure
different SoC locations — the peak represents the hottest point on the die,
which is the scientifically correct value for thermal stress analysis.

### Why not store the aggregated value directly

The view returns raw per-zone rows so that:

1. Per-zone heating analysis is possible (which zone heats first)
2. Different aggregation strategies can be applied post-hoc
3. The raw data is preserved for degradation research
4. Paper reviewers can verify the derivation from first principles

### Verified output on each platform

**NVIDIA Grace GB10 (aarch64), run 62:**
```
COUNT(*) = 28   (7 zones × 4 ticks)
AVG(cpu_temp) = 43.4°C
MIN(cpu_temp) = 43.1°C
MAX(cpu_temp) = 43.5°C
canonical_role = SOC (all rows)
```

**Intel i7-1165G7 (x86\_64), run 4561:**
```
COUNT(*) = 4    (1 zone × 4 ticks)
AVG(cpu_temp) = 51.5°C
MIN(cpu_temp) = 51.0°C
MAX(cpu_temp) = 52.0°C
canonical_role = CPU_PACKAGE (all rows)
```

---

## v_thermal_cpu View — Derivation and Platform Logic

### What the view does

`v_thermal_cpu` filters `thermal_samples_v2` to only the zones relevant for
CPU package temperature reporting. It joins with `thermal_zones` to apply
two filters:

1. `canonical_role IN ('CPU_PACKAGE', 'SOC')` — only CPU-relevant zones
2. `quality_flag = 'VALID'` — only readings within [-10, 125]°C
3. `active = 1` — only zones found at last discovery

The view returns raw rows — one row per zone per tick. It does NOT average
or aggregate. Aggregation is the responsibility of `ThermalAggregator` and
`aggregate_run_stats()`.

### Per-platform derivation logic

**Intel i7-1165G7 (x86\_64) — CPU\_PACKAGE role:**

One zone (`x86_pkg_temp`) has `canonical_role = CPU_PACKAGE`. The view
returns one row per 1Hz tick. `ThermalAggregator` computes:

```sql
SELECT cpu_temp FROM v_thermal_cpu
WHERE run_id = ? AND canonical_role = 'CPU_PACKAGE'
ORDER BY timestamp_ns
```

`package_temp_celsius = AVG(cpu_temp)` — direct average of package readings.

**NVIDIA Grace GB10 (aarch64) — SOC role:**

Seven zones all have `canonical_role = SOC`. The view returns 7 rows per
1Hz tick (one per zone). `ThermalAggregator` computes:

```sql
SELECT MAX(cpu_temp) FROM v_thermal_cpu
WHERE run_id = ? AND canonical_role = 'SOC'
GROUP BY timestamp_ns
ORDER BY timestamp_ns
```

`package_temp_celsius = AVG(MAX per tick)` — average of peak SoC temperature
at each sample point. MAX() is used because all 7 acpitz zones measure
different SoC locations — the peak represents the hottest point on the die,
which is the scientifically correct value for thermal stress analysis.

### Why not store the aggregated value directly

The view returns raw per-zone rows so that:

1. Per-zone heating analysis is possible (which zone heats first)
2. Different aggregation strategies can be applied post-hoc
3. The raw data is preserved for degradation research
4. Paper reviewers can verify the derivation from first principles

### Verified output on each platform

**NVIDIA Grace GB10 (aarch64), run 62:**
```
COUNT(*) = 28   (7 zones × 4 ticks)
AVG(cpu_temp) = 43.4°C
MIN(cpu_temp) = 43.1°C
MAX(cpu_temp) = 43.5°C
canonical_role = SOC (all rows)
```

**Intel i7-1165G7 (x86\_64), run 4561:**
```
COUNT(*) = 4    (1 zone × 4 ticks)
AVG(cpu_temp) = 51.5°C
MIN(cpu_temp) = 51.0°C
MAX(cpu_temp) = 52.0°C
canonical_role = CPU_PACKAGE (all rows)
```
