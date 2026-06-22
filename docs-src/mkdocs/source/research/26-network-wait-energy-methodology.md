# Network Wait Energy Methodology
**Document:** `research/26-network-wait-energy-methodology.md`
**Method ID:** `network_wait_energy_v1`
**Confidence:** 0.95 (RAPL slice) / 0.70 (time-fraction fallback)
**Axis:** AXIS 3A — Physical Observable
**Conservation role:** NONE — diagnostic signal, not a conservation partition

---

## Network Wait Energy Attribution

`network_wait_energy_uj` measures energy during network IO blocking periods —
when the system waits for a remote LLM API response.

This is an AXIS 3A physical observable used for:
- Physics explanation of why E_orchestration is non-zero at low CPU
- Provider comparison (remote vs local energy patterns)
- AXIS 3B regression input

---

## Primary Formula (MEASURED — RAPL window slice)

When `request_start_ns` and `first_token_time_ns` are available
(migration 038 or later):

$$E_{network} = \sum_{i \in \text{interactions}} \sum_{s \in [t^i_{req}, t^i_{first}]} \Delta pkg_s$$

where:
- $t^i_{req}$ = `llm_interactions.request_start_ns` for interaction i
- $t^i_{first}$ = `llm_interactions.first_token_time_ns` for interaction i
- $\Delta pkg_s$ = RAPL sample delta at sample s from `energy_samples`

**Note:** `alpha_cpu` multiplication removed in SPEC_03 (`network_wait_rapl_slice_v2`).
During network blocking CPU≈0 so alpha_cpu≈0 — multiplication zeroed out
the measurement. Raw pkg slice is correct: uncore/PCH/NIC activity is
non-zero during blocking regardless of CPU utilization.

**Type:** MEASURED
**Source:** Direct RAPL `energy_samples` slice over wait window timestamps
**Superseded by:** `network_wait_rapl_slice_v2` in `network_energy_attribution` table
**Platform extension:** Strategy B (`network_wait_spbm_fraction_v1`) covers GN100
via SPBM DC_INPUT (domain_id=28). See doc 31.
---

## Fallback Formula (MODELED — time-fraction)

When timestamps unavailable (pre-migration-038 runs):

$$E_{network} = \frac{t_{non\_local}}{t_{task}} \times E_{dynamic}$$

where `t_non_local` = `SUM(llm_interactions.non_local_ms)` per run.

**Important:** Uses `dynamic_energy_uj` NOT `attributed_energy_uj`.
attributed_energy_uj has alpha_cpu baked in — would double-suppress.

**Type:** MODELED
**Triggered by:** `request_start_ns IS NULL`

---

## Key Finding

This value is NON-ZERO even when `cpu_percent_during_wait ≈ 0`.

During network blocking periods:
- CPU cores are idle → near-zero core energy
- DRAM and uncore remain active → pkg energy non-zero
- Memory subsystem manages streaming receive buffers
- Network interrupt handlers fire for each packet

This is direct hardware evidence that E_orchestration is non-trivial
during remote provider calls. The RAPL slice method captures this
honestly — the time-fraction fallback also captures it but assumes
constant power throughout the run duration.

---

## Conservation Note

```
network_wait_energy_uj ⊂ E_orchestration (AXIS 2A)
It is NOT a separate conservation partition.
It is already inside orchestration_energy_uj.
Do NOT sum with orchestration_energy_uj.
Do NOT use in D1 conservation equations.
```

---

## Literature Basis

Hähnel et al. (2012), "Measuring Energy Consumption for Short Code
Paths Using RAPL," SIGMETRICS Performance Evaluation Review 40(3):
validated RAPL accuracy for short timestamp-bounded windows, confirming
that energy during blocking IO periods is measurable and non-trivial
even at low CPU utilization.

---

## Validation Query

```sql
-- Show CPU% vs pkg power during network wait windows
SELECT
    li.cpu_percent_during_wait,
    ea.network_wait_energy_uj / 1e6 AS network_wait_j,
    e.provider
FROM llm_interactions li
JOIN runs r ON r.run_id = li.run_id
JOIN experiments e ON e.exp_id = r.exp_id
JOIN energy_attribution ea ON ea.run_id = li.run_id
WHERE li.non_local_ms > 100
  AND li.cpu_percent_during_wait < 10
ORDER BY li.non_local_ms DESC;
-- Expected: network_wait_j > 0 despite cpu_percent_during_wait ≈ 0
```

---

## NVLink-C2C Energy Isolation

NVLink-C2C is the die-to-die interconnect between the Grace CPU and Blackwell GPU
on the GN100 unified memory SoC. Unlike NVLink between discrete GPUs, NVLink-C2C
operates within a single package at 900 GB/s with no PCIe boundary.

DCGM field 156 (TOTEC) measures GPU compute energy only. It excludes HBM memory
bandwidth energy and NVLink-C2C transfer energy. SPBM gpu accumulator measures
the full GPU rail including compute, HBM, and NVLink-C2C.

### Isolation Formula

$$E_{nvlink\_c2c} = E_{spbm\_gpu} - E_{dcgm\_gpu}$$

Where:

- $E_{spbm\_gpu}$ = SPBM gpu rail energy (compute + HBM + NVLink-C2C)
- $E_{dcgm\_gpu}$ = DCGM field 156 energy (compute only)
- $E_{nvlink\_c2c}$ = NVLink-C2C + HBM overhead (die-to-die transfer cost)

### Validated Baseline (GN100, 2026-06-14)

| Channel | Idle Power |
|---------|-----------|
| SPBM gpu rail | ~5,354 mW |
| DCGM field 156 | ~4,362 mW |
| NVLink-C2C delta | ~992 mW |

The 992 mW baseline represents the minimum NVLink-C2C + HBM power at idle.
Under inference load this delta increases as GPU pulls KV cache from shared
LPDDR5X memory across the NVLink-C2C interconnect.

### Implementation

ETL computes NVLINK_C2C per sample and writes to `energy_derived_metrics`:

```sql
INSERT INTO energy_derived_metrics
    (run_id, sample_id, metric_name, value_uj,
     derivation_formula, source_ids_used)
SELECT
    spbm.run_id, spbm.sample_id,
    'NVLINK_C2C',
    spbm.energy_uj - dcgm.energy_uj,
    'SPBM_GPU - DCGM_GPU',
    '2,4'
FROM energy_sample_domains spbm
JOIN energy_sample_domains dcgm
    ON dcgm.sample_id = spbm.sample_id
   AND dcgm.domain_id = 7
   AND dcgm.source_id = 4
WHERE spbm.domain_id = 7
  AND spbm.source_id = 2;
```

### Distinction from ET (ASHES 2026)

ET (Tran, Maiterth et al.) measures NVLink energy between discrete GPUs via NVML.
That topology mixes compute and NVLink in the same counter. SPBM rail subtraction
separates them for the first time on a unified memory SoC.

### method_id

`nvlink_c2c_isolation_v1` — confidence 0.95 (INFERRED: subtraction of two MEASURED values)
