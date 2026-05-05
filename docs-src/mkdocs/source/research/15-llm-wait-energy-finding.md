# LLM Wait Energy — AXIS 3 Diagnostic Signal
**Document:** `research/15-llm-wait-energy-finding.md`
**Method ID:** `llm_wait_attribution_v1`
**Confidence:** 0.85
**Axis:** AXIS 3A — System Dynamics Signal
**Conservation role:** NONE — diagnostic subset of E_orchestration

---

## LLM Wait Energy Attribution

`llm_wait_energy_uj` is an AXIS 3A physical observable — a named diagnostic
subset of E_orchestration. It is NOT a conservation partition. It is already
inside `orchestration_energy_uj` and must NOT be subtracted from E_attributed.

**Formula:**
$$E_{llm\_wait} = E_{attr} \times \frac{t_{non\_local}}{t_{task}}$$

where `t_non_local` = `llm_interactions.non_local_ms` (network round-trip time)
and `t_task` = `runs.task_duration_ns / 1e6`.

**Type:** MODELED (time-fraction proxy)

**Use for:** AXIS 3B regression input, provider comparison, physics explanation.
**Do NOT use for:** conservation equations, D1 partition.

---

## Key Empirical Finding

This value is NON-ZERO even when `cpu_percent_during_wait ≈ 0`.

During remote API blocking:
- CPU cores are idle → `cpu_percent_during_wait ≈ 0`
- DRAM and uncore remain active for streaming buffer management
- RAPL `pkg_energy_uj` shows sustained non-zero draw
- `E_orchestration` captures this correctly as the residual

This is the empirical foundation proving orchestration energy is non-trivial
during remote provider calls. The physics is explained by `E_dram` and
`E_uncore` remaining active even without core computation.

---

## Empirical Time Decomposition (n=1877 runs)

| Component | Agentic | Linear |
|-----------|---------|--------|
| LLM API wait | ~48% | ~49% |
| Active CPU compute | ~1-2% | ~0% |
| Orchestration/IO overhead | ~50% | ~51% |

---

## Power During Each Phase

| Phase | Power (W) | Notes |
|-------|-----------|-------|
| Active compute | ~33W | CPU fully utilised |
| LLM wait | ~12.9W | Sub-active — above idle, below compute |
| Idle baseline | ~3-5W | System idle measurement |

The ~12.9W during wait is captured in `E_orchestration` via the AXIS 2A
residual formula: `E_orchestration = E_attributed - E_llm_window`.

---

## Relationship to Conservation Model

```
AXIS 2A (conservation):
  E_attributed = E_llm_window + E_orchestration   ← llm_wait is INSIDE E_orchestration

AXIS 3A (diagnostic):
  llm_wait_energy_uj = time-fraction subset of E_orchestration
                     = observational signal only
                     = NOT subtracted from E_attributed
```

The D1 partition is TWO-TERM only:
$$E_{attributed} = E_{llm\_window} + E_{orchestration}$$

`llm_wait` is stored for AXIS 3B regression and provider comparison.
It must never appear in conservation equations.

---

## AXIS 3B Regression Use

`llm_wait_energy_uj / attributed_energy_uj` is a candidate regressor
explaining variance in `E_orchestration / E_attributed`:

$$\frac{E_{orch}}{E_{attr}} = \beta_0 + \beta_1 x_{network} + ... + \epsilon$$

High `llm_wait_ratio` indicates remote provider runs — explains why
E_orchestration is high for groq/openai vs local tinyllama runs.
