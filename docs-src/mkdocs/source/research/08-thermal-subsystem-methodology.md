# Thermal Zone and Cooling Device Measurement Methodology

---
**Method IDs:** `thermal_zone_sysfs_v2`, `cooling_sysfs_v1`
**Schema versions:** 65 (thermal_zones), 66 (cooling_devices), 67 (thermal_samples_v2), 68 (cooling_samples), 69 (v_thermal_cpu)
**Platforms verified:** NVIDIA Grace GB10 (aarch64), Intel i7-1165G7 (x86_64)
**Status:** PRODUCTION
**Last updated:** 2026-06-19
---

## thermal_zone_sysfs_v2

**Source:** `/sys/class/thermal/thermal_zone*/temp` (Linux sysfs)
**Layer:** os
**Provenance:** MEASURED
**Confidence:** 0.92

**Formula:**

$$T_{pkg} = f(\{T_i : \text{role}(i) \in \{\text{CPU\_PACKAGE, SOC}\}, \text{valid}(i)\})$$

Where:
- $T_i$ = temperature of zone $i$ in Celsius (millidegrees / 1000)
- $\text{role}(i)$ = canonical role from THERMAL\_ROLE\_MAP
- $\text{valid}(i)$ = quality\_flag = 'VALID' and $T_i \in [-10, 125]$°C
- On CPU\_PACKAGE platforms (Intel, AMD): $f = \text{mean}$
- On SOC platforms (GN100): $f = \text{MAX per timestamp}$

**Confidence justification:**
0.92 not 1.0: ACPI polling interval introduces up to 100ms lag between true
silicon temperature and reported value. Under sustained LLM inference (>10s)
this averages to <0.5°C error. Quality filtering removes broken sensors
(e.g. TCPU = -273.15°C on Intel i7-1165G7) before aggregation, hence higher
confidence than arm\_thermal\_sysfs\_v1 (0.90). To reach 1.0 would require
direct silicon temperature via MSR thermal registers (unavailable on ARM).

**Parameters:**

| Parameter | Value |
|-----------|-------|
| source | /sys/class/thermal/thermal\_zone\*/temp |
| unit | millidegrees Celsius ÷ 1000 |
| valid range | [-10.0, 125.0]°C |
| quality flags | VALID, OUT\_OF\_RANGE, READ\_FAILED, MISSING |
| identity key | (zone\_type, zone\_index) — stable across reboots |
| sampling rate | 1 Hz |

**Outputs:**

| Column | Table | Derivation |
|--------|-------|-----------|
| package\_temp\_celsius | runs | mean of VALID CPU\_PACKAGE or MAX(SOC) per tick |
| start\_temp\_c | runs | first sample in run |
| max\_temp\_c | runs | maximum across run |
| min\_temp\_c | runs | minimum across run |
| thermal\_delta\_c | runs | last sample minus first sample |
| temp\_celsius | thermal\_samples\_v2 | raw per-zone reading |
| quality\_flag | thermal\_samples\_v2 | VALID or rejection reason |

---

## cooling_sysfs_v1

**Source:** `/sys/class/thermal/cooling_device*/cur_state` (Linux sysfs)
**Layer:** os
**Provenance:** MEASURED
**Confidence:** 1.00

**Formula:**

$$\text{throttled} = \exists\, i : \text{role}(i) \in \text{THROTTLE\_ROLES} \land \text{cur\_state}(i) > 0 \land \text{valid}(i)$$

Where THROTTLE\_ROLES = {CPU\_FREQ\_THROTTLE, POWER\_CLAMP, TCC\_OFFSET}

**Confidence justification:**
1.00: `cur_state` is an exact kernel enum value — no measurement uncertainty
in the reading itself. Physical interpretation (how much frequency reduction
corresponds to each state level) is platform-specific and documented in
the cooling\_devices registry via the `max_state` column.

**Parameters:**

| Parameter | Value |
|-----------|-------|
| source | /sys/class/thermal/cooling\_device\*/cur\_state |
| unit | kernel state enum (0 = idle, max\_state = full throttle) |
| invalid states | negative cur\_state stored as OUT\_OF\_RANGE |
| sampling rate | 1 Hz |

**Outputs:**

| Column | Table | Derivation |
|--------|-------|-----------|
| thermal\_during\_experiment | runs | any THROTTLE\_ROLE device cur\_state > 0 |
| thermal\_throttle\_flag | runs | 0 or 1 |
| cur\_state | cooling\_samples | raw kernel state value |
| quality\_flag | cooling\_samples | VALID or OUT\_OF\_RANGE |
