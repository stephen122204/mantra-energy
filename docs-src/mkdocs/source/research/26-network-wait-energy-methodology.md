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

$$E_{network} = \sum_{i \in \text{interactions}} \sum_{s \in [t^i_{req}, t^i_{first}]} \Delta pkg_s \times \alpha_{cpu}$$

where:
- $t^i_{req}$ = `llm_interactions.request_start_ns` for interaction i
- $t^i_{first}$ = `llm_interactions.first_token_time_ns` for interaction i
- $\Delta pkg_s$ = RAPL sample delta at sample s from `energy_samples`
- $\alpha_{cpu}$ = `runs.cpu_fraction`

**Type:** MEASURED
**Source:** Direct RAPL `energy_samples` slice over wait window timestamps

---

## Fallback Formula (MODELED — time-fraction)

When timestamps unavailable (pre-migration-038 runs):

$$E_{network} = \frac{t_{non\_local}}{t_{task}} \times E_{attributed}$$

where `t_non_local` = `SUM(llm_interactions.non_local_ms)` per run.

**Type:** MODELED
**Triggered by:** `request_start_ns IS NULL`
**Attribution method stored:** `time_fraction_fallback_v1`

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
