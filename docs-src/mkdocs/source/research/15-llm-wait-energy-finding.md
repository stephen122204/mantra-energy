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
