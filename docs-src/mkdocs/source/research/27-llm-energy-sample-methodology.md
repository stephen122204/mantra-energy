# LLM Energy Attribution v2 — Sample-Based Measurement
**Document:** `research/27-llm-energy-sample-methodology.md`
**Method ID:** `llm_energy_sample_v2`
**Confidence:** 0.97
**Provenance:** MEASURED
**Supersedes:** `llm_wait_attribution_v1` (time-fraction method)

---

## LLM Energy Attribution v2

Measures LLM inference window energy directly from 100Hz RAPL samples
using `llm_interactions` timestamp windows. Replaces time-fraction
estimation with direct hardware measurement.

---

## Core Formula

**E_prefill** — energy during prompt encoding:
$$E_{prefill} = \sum_{s \in [t_{req}, t_{first}]} \Delta pkg_s \times \alpha_{cpu}$$

**E_decode** — energy during token generation:
$$E_{decode} = \sum_{s \in [t_{first}, t_{last}]} \Delta pkg_s \times \alpha_{cpu}$$

**E_llm_window** — total LLM inference window energy:
$$E_{llm\_window} = E_{prefill} + E_{decode}$$

**E_orchestration** — residual (TWO-TERM D1 partition, exact):
$$E_{orchestration} = E_{attributed} - E_{llm\_window}$$

where:
- $t_{req}$ = `llm_interactions.request_start_ns`
- $t_{first}$ = `llm_interactions.first_token_time_ns`
- $t_{last}$ = `llm_interactions.last_token_time_ns`
- $\Delta pkg_s$ = RAPL delta from `energy_samples`
- $\alpha_{cpu}$ = `runs.cpu_fraction`

---

## D1 Partition Rule (Critical)

The functional partition is TWO-TERM only:
$$E_{attributed} = E_{llm\_window} + E_{orchestration}$$

`llm_wait_energy_uj` (decode window energy) is stored as an AXIS 3
diagnostic signal — it is a named subset of E_orchestration. It is
NOT subtracted from E_attributed in the conservation equation.

**Column mapping:**
- `llm_compute_energy_uj` ≡ E_llm_window (= E_prefill + E_decode)
- `orchestration_energy_uj` ≡ E_orchestration (= E_attributed - E_llm_window)
- `prefill_energy_uj` = E_prefill (AXIS 2A sub, conditional)
- `decode_energy_uj` = E_decode (AXIS 2A sub, conditional)
- `llm_wait_energy_uj` = E_decode (AXIS 3A diagnostic only)

---

## Why v2 Supersedes v1

v1 (`llm_wait_attribution_v1`) computed LLM energy using time-fraction:
$$E_{llm\_wait}^{v1} = E_{attr} \times \frac{t_{api}}{t_{task}}$$

Problems with v1:
- `api_latency_ms = 0` for local models → E_llm_wait = 0 (always wrong)
- Assumes constant power during wait — not measured
- Three-term D1: `attributed = llm_compute + llm_wait + orchestration`
  violates the Two-Term conservation invariant

v2 fixes all three:
- Uses RAPL samples directly — works for local AND remote
- Measures actual energy in each window — no power assumption
- Two-term D1: `attributed = llm_window + orchestration` (exact)

---

## Fallback (when timestamps NULL)

When `first_token_time_ns IS NULL` (tinyllama linear, pre-migration-038):
```
attribution_method = 'time_fraction_fallback_v1'
llm_compute_uj = attributed × (compute_ms / task_duration_ms)
orchestration_uj = attributed - llm_compute_uj  ← TWO-TERM preserved
llm_wait_uj = attributed × (non_local_ms / task_duration_ms)  ← AXIS 3 only
```

Fallback also preserves the two-term invariant — llm_wait is stored
for AXIS 3 diagnostic use but never subtracted from attributed.

---

## Novel Finding

Local models (tinyllama, ollama) with `api_latency_ms = 0` still draw
significant power during decode — v1 missed this entirely by returning
zero. v2 captures it via direct RAPL sample measurement in the
`[first_token_time_ns → last_token_time_ns]` window.

---

## Validation Query

```sql
-- Verify two-term D1 conservation for v2 runs
SELECT ea.run_id,
    ea.attribution_method,
    ABS(r.attributed_energy_uj
        - ea.llm_compute_energy_uj
        - ea.orchestration_energy_uj) AS d1_delta
FROM energy_attribution ea
JOIN runs r ON r.run_id = ea.run_id
WHERE ea.attribution_method = 'sample_based_v2'
  AND r.attributed_energy_uj > 0
ORDER BY d1_delta DESC LIMIT 10;
-- Expected: d1_delta = 0 for all rows
```
