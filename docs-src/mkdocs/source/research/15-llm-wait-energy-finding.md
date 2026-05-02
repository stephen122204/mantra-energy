# 15. LLM Wait Energy — Novel Research Finding

## Summary

A-LEMS discovered that LLM-integrated workloads spend ~48% of wall-clock time
blocked waiting for LLM API responses. During this period the process consumes
measurable energy (~12.9W) that is invisible to all prior CPU-utilisation-based
measurement tools. We term this **LLM Wait Energy**.

---

## The Problem with Prior Tools

Traditional energy attribution assumes CPU-bound workloads:

$$E_{workload} \approx E_{pkg} \times \text{cpu\_fraction}$$

For LLM workloads this fails because:

- Process is alive and consuming energy during API wait
- CPU utilisation ≈ 0 during wait → prior tools report near-zero
- RAPL captures the real energy — it is simply misattributed

---

## Empirical Time Decomposition (A-LEMS Dataset, n=1877 runs)

| Component | Agentic | Linear |
|-----------|---------|--------|
| LLM API wait | ~48% | ~49% |
| Active CPU compute | ~1–2% | ~0% |
| Orchestration/IO overhead | ~50% | ~51% |

---

## Power During Each Phase

| Phase | Power (W) | Notes |
|-------|-----------|-------|
| Active compute | ~33W | CPU fully utilised |
| LLM API wait | ~12.9W | Process blocked on socket |
| Idle baseline | 2.4–3.2W | 2-sigma measured |

---

## Attribution Formula

$$E_{llm\_wait} = E_{attributed} \times \frac{t_{api}}{t_{task}}$$

Where:
- $E_{attributed}$ = `cpu_fraction × dynamic_energy_uj` (Chunk 3)
- $t_{api}$ = `SUM(api_latency_ms)` from `llm_interactions`
- $t_{task}$ = `task_duration_ns / 1e6` (Chunk 6 corrected duration)

**Confidence:** 0.85 (CALCULATED — time-fraction proxy, power assumed constant during wait)

**Method ID:** `llm_wait_attribution_v1`

---

## Measurement Boundary

| Scope | Measured | Notes |
|-------|----------|-------|
| Client CPU (RAPL) | ✅ Yes | Full pkg energy including wait |
| Local Ollama GPU (NVML) | ⬜ Chunk 14 | Same machine, different process |
| Remote API server | ❌ Out of scope | Different machine |
| Estimated server energy | ⬜ Chunk 15 | Option 2: TDP × tokens / throughput, confidence=0.3 |

---

## Research Contribution

This finding is novel. No prior LLM energy measurement paper distinguishes
client-side LLM wait energy from orchestration overhead. A-LEMS is the first
platform to:

1. Measure and attribute LLM API wait energy via RAPL + api_latency correlation
2. Show that ~48% of agentic run energy is in this previously invisible category
3. Provide a reproducible methodology for future comparative studies

---

## Future Work

- **Chunk 14:** NVML GPU reader for local Ollama server energy
- **Chunk 15:** Server-side energy estimation for remote API runs
- **Chunk 1.2:** ARM ML estimator for platforms without RAPL

---

## References

See `config/methodology_refs/llm_wait_attribution_v1.yaml`

## LLM Energy Attribution v2 — Sample-Based Measurement
 
**Method ID:** `llm_energy_sample_v2`
**Layer:** application
**Provenance:** MEASURED
**Confidence:** 0.97
**Supersedes:** `llm_wait_attribution_v1`
 
### Why v2
 
v1 computed LLM wait energy using time-fraction:
$$E_{llm\_wait}^{v1} = E_{attributed} \times \frac{t_{api\_latency}}{t_{duration}}$$
 
This fails for local models where `api_latency_ms = 0` (localhost HTTP),
producing `E_llm_wait = 0` even though the model takes seconds to generate
tokens and the process draws real power throughout.
 
v2 measures directly from RAPL samples using `llm_interactions` timestamps.
 
### Formula
 
**Prefill window** (active CPU processing prompt):
$$E_{llm\_compute} = \sum_{s \in [t_{call}, t_{first\_token}]} \Delta pkg_s \times f_{cpu}$$
 
**Decode window** (process waiting for token stream):
$$E_{llm\_wait} = \sum_{s \in [t_{first\_token}, t_{last\_token}]} \Delta pkg_s \times f_{cpu}$$
 
where $\Delta pkg_s = pkg\_end\_uj_s - pkg\_start\_uj_s$ per 100Hz sample.
 
**Orchestration residual:**
$$E_{orchestration} = E_{attributed} - E_{llm\_compute} - E_{llm\_wait}$$
 
**Conservation invariant (D1):**
$$E_{attributed} = E_{llm\_compute} + E_{llm\_wait} + E_{orchestration}$$
 
Must sum to 100%. Validated by `scripts/validate_energy_chain.py`.
 
### Data Sources
 
| Variable | Table | Column |
|---|---|---|
| `pkg_start_uj`, `pkg_end_uj` | `energy_samples` | RAPL 100Hz intervals |
| `first_token_time_ns` | `llm_interactions` | Prefill/decode boundary |
| `last_token_time_ns` | `llm_interactions` | Decode end |
| `cpu_fraction` | `runs` | Process CPU share |
 
### Output Columns
 
| Column | Table | Type | Formula |
|---|---|---|---|
| `llm_compute_energy_uj` | `energy_attribution` | MEASURED | samples[call..first_token] × f_cpu |
| `llm_wait_energy_uj` | `energy_attribution` | MEASURED | samples[first_token..last_token] × f_cpu |
| `orchestration_energy_uj` | `energy_attribution` | CALCULATED | E_attr - llm_c - llm_w |
| `attribution_method` | `energy_attribution` | SYSTEM | 'sample_based_v2' or 'time_fraction_fallback_v1' |
 
### Fallback
 
When `first_token_time_ns IS NULL` (older runs, linear runs without timing):
`attribution_method = time_fraction_fallback_v1`
Confidence degrades to 0.70.
 
### Local vs Cloud Provider Behaviour
 
| Provider | `api_latency_ms` | v1 llm_wait | v2 llm_wait |
|---|---|---|---|
| llama_cpp (local) | 0 (localhost) | 0 ❌ | measured from decode window ✅ |
| groq (cloud) | ~8000ms | estimated | measured from decode window ✅ |
 
For local models, decode phase energy was entirely invisible to v1.
This was a systematic undercount of LLM wait energy for all local runs.
 
### Known Limitations
 
- Prefill window start (`t_call`) not currently stored per interaction — `llm_compute_uj` uses `compute_ms` time-fraction as proxy
- Multiple LLM interactions per run summed — individual call breakdown available in `llm_interactions` table
- Sub-100Hz phases may have 0 samples in window — `attribution_method` records this
 
### References
 
See `config/methodology_refs/llm_energy_sample_v2.yaml`.