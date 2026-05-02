# A-LEMS Energy Attribution Guide
# Complete Reference: Every Energy Field, Every Formula, Every Layer
# Version: 2.0 (Phase Attribution v2 + Sample-based LLM energy)
# Location: docs-src/mkdocs/source/research/25-energy-attribution-guide.md

## Overview

This document is the single source of truth for all energy fields in A-LEMS.
Every field is documented with:
- Formula (LaTeX-style)
- Data source table/column
- Provenance type (MEASURED / CALCULATED / INFERRED)
- Confidence level
- Paper section reference

---

## Energy Hierarchy Tree

```
E_pkg  [MEASURED — RAPL package-0 MSR delta]
│  = RAPL_end - RAPL_start across run duration
│  Source: energy_samples → runs.pkg_energy_uj
│
├── E_baseline  [MEASURED — idle power × duration]
│   = P_idle_min × Δt  (2nd-percentile baseline sample × elapsed seconds)
│   Source: idle_baselines → runs.baseline_energy_uj
│
└── E_dynamic  [CALCULATED — E_pkg - E_baseline]
    │  = workload energy above idle floor
    │  Source: runs.dynamic_energy_uj
    │  Invariant: E_pkg = E_baseline + E_dynamic
    │
    ├── E_background  [CALCULATED — E_dynamic × (1 - f_cpu)]
    │   = energy consumed by OTHER processes during our run
    │   Source: energy_attribution.background_energy_uj
    │
    └── E_attributed  [CALCULATED — f_cpu × E_dynamic]
        │  f_cpu = process_ticks / total_ticks  [/proc — MEASURED]
        │  = this process share of workload energy
        │  Source: runs.attributed_energy_uj
        │  Invariant: E_dynamic = E_attributed + E_background
        │
        ├── E_pre  [MEASURED — energy_samples SUM[t0..t1]]
        │   = framework setup before first LLM call
        │   Source: runs.pre_task_energy_uj
        │
        ├── E_post  [MEASURED — energy_samples SUM[t2_last..t3]]
        │   = framework teardown after last LLM returns
        │   Source: runs.post_task_energy_uj
        │
        ├── E_inter_phase  [CALCULATED — E_attr - SUM(E_phase_i)]
        │   = energy between phase boundaries
        │   = Python interpreter, tool dispatch, retry logic, framework calls
        │   NOT zero by construction (v2) — honestly measured residual
        │   Source: runs.inter_phase_energy_uj
        │
        ├── E_planning  [MEASURED — samples in planning window × cpu_frac]
        │   = energy during LLM planning phase
        │   Source: runs.planning_energy_uj
        │   Method: phase_attribution_sample_v2
        │
        ├── E_execution  [MEASURED — samples in execution window × cpu_frac]
        │   = energy during tool execution + LLM step calls
        │   Source: runs.execution_energy_uj
        │   Method: phase_attribution_sample_v2
        │
        ├── E_synthesis  [MEASURED — samples in synthesis window × cpu_frac]
        │   = energy during final LLM synthesis call
        │   Source: runs.synthesis_energy_uj
        │   Method: phase_attribution_sample_v2
        │
        ├── E_llm_compute  [MEASURED — samples[call_start..first_token_ns] × cpu_frac]
        │   = energy during active prompt prefill (CPU computing)
        │   Source: energy_attribution.llm_compute_energy_uj
        │   Method: llm_energy_sample_v2
        │   Fallback: time-fraction when timestamps NULL
        │
        ├── E_llm_wait  [MEASURED — samples[first_token_ns..last_token_ns] × cpu_frac]
        │   = energy while process blocked waiting for token stream
        │   NOVEL FINDING: not idle (3-5W), draws ~12.9W during decode
        │   For local models: api_latency=0 but window exists → correctly measured
        │   For cloud models: confirms wait energy is real and significant
        │   Source: energy_attribution.llm_wait_energy_uj
        │   Method: llm_energy_sample_v2
        │
        └── E_orchestration  [CALCULATED — E_attr - E_llm_compute - E_llm_wait]
            │  = pure framework overhead: planning logic, tool dispatch,
            │    retry coordination, synthesis, result processing
            │  THIS IS THE PAPER THESIS METRIC
            │  Source: energy_attribution.orchestration_energy_uj
            │
            ├── E_planning (from phase ETL, see above)
            ├── E_execution (from phase ETL, see above)
            ├── E_synthesis (from phase ETL, see above)
            └── E_inter_phase (Python/framework between phases)

RAPL Domain View (parallel decomposition — paper Figure 2):
E_pkg = E_core + E_uncore + E_dram  [all MEASURED]
  E_core   = CPU cores (arithmetic units, caches)
  E_uncore = LLC cache + ring bus + memory controller + PCIe
  E_dram   = DRAM memory
```

---

## Goal-Level Energy Rollup

```
goal_execution.total_energy_uj  [CALCULATED — Approach 2]
= SUM(goal_attempt.energy_uj) across ALL attempts (including failed)
Invariant: E_dyn(winning_run) = SUM(attempts)

├── successful_energy_uj  [CALCULATED]
│   = winning_attempt.energy_uj
│
├── overhead_energy_uj  [CALCULATED]
│   = total - successful
│   = energy wasted on failed attempts
│
├── overhead_fraction  [CALCULATED]
│   = overhead_energy_uj / total_energy_uj
│
└── orchestration_fraction  [CALCULATED]
    = E_orchestration / E_attributed
    Formula: f_orch = E_orch / E_attr
    CORRECT denominator: attributed (not pkg, not dynamic)
    Reason: E_orch is derived FROM E_attributed;
            using pkg includes idle + background → understates f_orch

tool_failure_events.wasted_energy_uj  [CALCULATED — N11/N17 pending]
= energy during failed tool execution window
```

---

## Inferred Fields (RAPL cannot measure directly)

These use models/heuristics — documented for reviewer transparency:

| Field | Formula | Assumption | Confidence |
|---|---|---|---|
| `network_wait_energy_uj` | `E_attr × (non_local_ms / duration_ms)` | Constant power during network wait | 0.75 |
| `io_wait_energy_uj` | `E_pkg × (io_wait_ms / duration_ms)` | Constant power during I/O | 0.70 |
| `memory_pressure_energy_uj` | `page_faults × 10µJ` | 10µJ per TLB miss (empirical) | 0.65 |
| `disk_energy_uj` | `(bytes_r + bytes_w) / 1024 × 0.1µJ/KB` | Linear I/O energy model | 0.60 |
| `interrupt_energy_uj` | `interrupt_rate × 0.5µJ × duration_s` | 0.5µJ per interrupt | 0.65 |
| `scheduler_energy_uj` | `ctx_switches × 1µJ` | 1µJ per context switch | 0.65 |
| `thermal_penalty_energy_uj` | `E_pkg × throttle_ratio × 0.20` | 20% energy penalty per throttle | 0.85 |

---

## Provenance Classification

```
MEASURED   = direct hardware counter or OS read
             RAPL MSR, /proc ticks, energy_samples timestamps
             Confidence: 0.97-1.0

CALCULATED = exact arithmetic from MEASURED values
             No model assumptions, deterministic, reproducible
             Confidence: 1.0

INFERRED   = model-based estimate
             Documented assumption, stated confidence
             Reviewer must be told these are estimates
             Confidence: 0.60-0.85
```

---

## Key Invariants for Paper Validation

```
L0: E_pkg = E_core + E_uncore + E_dram              [RAPL domain identity]
L1: E_pkg = E_baseline + E_dynamic                  [three-layer model]
L2: E_dynamic = E_attributed + E_background          [process attribution]
L3: workload_pure = E_dynamic - E_pre - E_post       [boundary model]
L4: E_attr = E_plan + E_exec + E_synth + E_inter     [phase decomposition v2]
L5: E_dyn(run) = SUM(goal_attempt.energy_uj)         [Approach 2 conservation]
L6: E_attr = E_llm_compute + E_llm_wait + E_orch     [LLM attribution v2]
L7: f_orch = E_orch / E_attr                         [orchestration fraction]
L8: P_avg = E_dynamic / duration_s                   [power identity]
```

All invariants validated by: `python scripts/validate_energy_chain.py --latest`

---

## Known Limitations (Paper Section: Threats to Validity)

1. **Phase coverage < 100%**: Short phases (< 10ms synthesis) may capture 0
   energy samples at 100Hz. `phase_sample_coverage_pct` documents this per run.

2. **Inter-phase energy**: Energy between phase boundaries attributed to
   `inter_phase_energy_uj`. This includes Python interpreter overhead,
   tool dispatch latency, and framework calls not in any named phase.
   Reported honestly — not hidden by normalization.

3. **Single-PID attribution**: Only the top-level process PID is tracked.
   Spawned subprocesses (e.g. llama.cpp workers) contribute to E_pkg but
   may not be in E_attributed if they run under different PIDs.

4. **RAPL temporal resolution**: At 100Hz sampling, sub-10ms phases have
   high quantisation error. Reported in `phase_sample_coverage_pct`.

5. **Inferred sub-fields**: Network, I/O, memory pressure fields use
   time-fraction or heuristic models (see table above). Always report
   confidence level alongside these values in paper tables.

6. **Local model LLM wait**: For local models (llama_cpp), the decode
   phase energy is real but historically under-reported because
   `api_latency_ms = 0` (localhost). Sample-based v2 corrects this.

---

## Files Reference

| File | Purpose |
|---|---|
| `scripts/etl/phase_attribution_etl.py` | L4 phase energy (v2: direct samples) |
| `scripts/etl/energy_attribution_etl.py` | L6 LLM energy + full attribution model |
| `scripts/etl/_llm_energy_from_samples.py` | L6 sample-based helper |
| `scripts/etl/goal_execution_etl.py` | L7 orchestration fraction + goal rollup |
| `scripts/validate_energy_chain.py` | Full invariant validation (L0-L8) |
| `scripts/migrations/037_phase_attribution_v2.sql` | Schema additions + view fixes |
| `core/utils/provenance.py` | Provenance registry |
| `scripts/seed_methodology.py` | Method definitions with LaTeX formulas |
