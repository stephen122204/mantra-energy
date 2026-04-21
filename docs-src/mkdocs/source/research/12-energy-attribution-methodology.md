# Energy Attribution Methodology

**Document:** `research/12-energy-attribution-methodology.md`  
**Chunk:** 6  
**Method ID:** `energy_attribution_v1`  
**Confidence:** 0.95  
**Layer:** All (L0–L5)

---

## Overview

Energy attribution is the core analytical contribution of A-LEMS. Rather than
reporting a single opaque `pkg_energy_uj` number, A-LEMS decomposes every run's
energy consumption into five causal layers. This enables researchers to answer
questions like:

- *How much of the agentic run's energy was orchestration overhead vs actual LLM compute?*
- *What fraction of energy was consumed waiting for network I/O?*
- *Did thermal throttling inflate the measured energy?*
- *How much energy was unattributed — and why?*

The attribution model produces a row in `energy_attribution` for every run,
automatically computed by the ETL pipeline after `save_pair()` completes.

---

## Attribution Model v1 — Layer Decomposition

```
pkg_energy_uj (total RAPL package energy)
│
├── L0: Hardware Domains
│   ├── core_energy_uj          — CPU cores (RAPL core domain)
│   ├── dram_energy_uj          — DRAM (RAPL dram domain)
│   └── uncore_energy_uj        — Uncore (LLC, memory controller)
│
├── L1: System Overhead
│   ├── background_energy_uj    — residual not attributable to workload
│   ├── interrupt_energy_uj     — estimated from interrupt_rate × 0.5µJ
│   └── scheduler_energy_uj     — estimated from context_switches × 1µJ
│
├── L2: Resource Contention
│   ├── network_wait_energy_uj  — (non_local_ms / duration_ms) × pkg
│   ├── io_wait_energy_uj       — (io_block_time_ms / duration_ms) × pkg
│   ├── disk_energy_uj          — (disk_bytes / 1024) × 0.1µJ/KB
│   ├── memory_pressure_energy_uj — page_faults × 10µJ
│   └── cache_dram_energy_uj    — dram × (l3_misses / l3_total)
│
├── L3: Workflow Decomposition
│   ├── orchestration_energy_uj — attributed − application
│   ├── planning_energy_uj      — from orchestration_events (Chunk 5)
│   ├── execution_energy_uj     — from orchestration_events (Chunk 5)
│   ├── synthesis_energy_uj     — from orchestration_events (Chunk 5)
│   ├── tool_energy_uj          — NULL (Chunk 8)
│   ├── retry_energy_uj         — NULL (Chunk 8)
│   ├── failed_tool_energy_uj   — NULL (Chunk 8)
│   └── rejected_generation_energy_uj — NULL (Chunk 8)
│
├── L4: Model Compute
│   ├── llm_compute_energy_uj   — application_energy (attributed × UCR)
│   ├── prefill_energy_uj       — NULL (Chunk 4 TTFT)
│   └── decode_energy_uj        — NULL (Chunk 4 TTFT)
│
├── L5: Outcome Normalisation
│   ├── energy_per_completion_token_uj
│   ├── energy_per_successful_step_uj
│   ├── energy_per_accepted_answer_uj — NULL (Chunk 8)
│   └── energy_per_solved_task_uj     — NULL (Chunk 8)
│
├── thermal_penalty_energy_uj   — time-weighted throttle penalty
└── unattributed_energy_uj      — residual (research target: → 0)
```

---

## Key Formulas

### Utilisation Compute Ratio (UCR)

```
UCR = compute_time_ms / duration_ms
```

- `compute_time_ms` — from `runs` table, measured by `harness.py`
- `duration_ms` — `runs.duration_ns / 1e6`
- UCR is clamped to [0, 1]
- Represents fraction of wall-clock time the process was doing CPU compute

### Application Energy (LLM Compute)

```
E_application = E_attributed × UCR
```

Where `E_attributed = cpu_fraction × dynamic_energy_uj` (from Chunk 3).

### Orchestration Energy

```
E_orchestration = E_attributed − E_application
```

This is the *orchestration tax* — energy spent coordinating rather than computing.

### Background Energy

```
E_background = max(0, E_pkg − E_core − E_dram − E_orchestration
                      − E_application − E_network − E_io)
```

Energy not attributable to any explicit layer. Should be small on a well-tuned
system; large values indicate missing attribution coverage.

### Network Wait Energy (INFERRED)

```
E_network = (non_local_ms / duration_ms) × E_pkg
```

Source: `llm_interactions.non_local_ms` — the portion of API latency that was
network round-trip (not local compute).

### I/O Wait Energy (INFERRED)

```
E_io = (io_block_time_ms / duration_ms) × E_pkg
```

Source: `io_samples.io_block_time_ms` — time the process was blocked on disk.

### Memory Pressure Energy (INFERRED)

```
E_memory_pressure = minor_page_faults × 10µJ
```

The 10µJ constant is empirical: approximate cost of a TLB miss + page fill
on x86 at 3GHz. Confidence: 0.70 (order-of-magnitude estimate).

### Cache/DRAM Energy (INFERRED)

```
E_cache_dram = E_dram × (l3_cache_misses / (l3_cache_hits + l3_cache_misses))
```

Fraction of DRAM energy attributable to LLC misses forcing main memory access.

**Note:** On this ThinkPad (UBUNTU2505), `l1d_cache_misses = 0` (PMU unavailable).
L3 counters are populated. L1d contribution is zero — expected hardware limitation.

### Thermal Penalty (INFERRED)

```
throttle_ratio = Σ(interval_ns where cpu_temp > 85°C) / Σ(all interval_ns)
E_thermal = E_pkg × throttle_ratio × 0.20
```

The 0.20 (20%) factor represents the estimated frequency reduction when Intel
thermal throttle activates. Confidence: 0.85.

### Unattributed Energy

```
E_unattributed = max(0, E_pkg − Σ all attributed layers)
```

**Research interpretation:**
- `unattributed_energy_uj ≈ 0` — model is complete, all energy explained
- `unattributed_energy_uj` large — there are energy consumers not modelled
- Track `attribution_coverage_pct` over model versions to measure improvement

---

## Attribution Model Quality

`attribution_coverage_pct = (E_pkg - E_unattributed) / E_pkg × 100`

| Coverage | Interpretation |
|----------|---------------|
| > 95% | Excellent — nearly all energy attributed |
| 85–95% | Good — minor gaps in L2 or thermal model |
| 70–85% | Fair — L3/L4 data missing (Chunk 4/8 not yet run) |
| < 70% | Poor — significant attribution model gaps |

Expected coverage with Chunk 6 only (no Chunk 4/8 data): ~75–85%.
Full coverage target after all chunks: > 95%.

---

## Data Sources Per Layer

| Layer | Column | Source Table | Source Column |
|-------|--------|-------------|---------------|
| L0 | `pkg_energy_uj` | `runs` | `pkg_energy_uj` (RAPL) |
| L0 | `core_energy_uj` | `runs` | `core_energy_uj` (RAPL) |
| L0 | `dram_energy_uj` | `runs` | `dram_energy_uj` (RAPL) |
| L1 | `background_energy_uj` | computed | formula above |
| L1 | `interrupt_energy_uj` | `runs` | `interrupt_rate` × 0.5µJ × duration_s |
| L1 | `scheduler_energy_uj` | `runs` | `total_context_switches` × 1µJ |
| L2 | `network_wait_energy_uj` | `llm_interactions` | `non_local_ms` |
| L2 | `io_wait_energy_uj` | `io_samples` | `io_block_time_ms` |
| L2 | `memory_pressure_energy_uj` | `runs` | `minor_page_faults` × 10µJ |
| L2 | `cache_dram_energy_uj` | `runs` | `l3_cache_*_total` |
| L3 | `orchestration_energy_uj` | computed | attributed − application |
| L3 | `planning_energy_uj` | `orchestration_events` / `runs` | phase SUM |
| L4 | `llm_compute_energy_uj` | computed | attributed × UCR |
| L5 | `energy_per_completion_token_uj` | computed | pkg / completion_tokens |
| Thermal | `thermal_penalty_energy_uj` | `thermal_samples` | `cpu_temp`, intervals |

---

## Thermal Penalty Model

### Why time-weighted?

A naive threshold check (`if max_temp > 85: penalty = pkg × 0.20`) would apply
the full penalty even if the CPU touched 85.1°C for a single 1-second sample
in a 120-second run. This inflates the penalty by ~120×.

The correct model weights the penalty by the *fraction of time* the CPU was
above threshold:

```python
throttle_ratio = Σ(sample_end_ns - sample_start_ns | cpu_temp > 85) 
               / Σ(sample_end_ns - sample_start_ns)
```

Source: `thermal_samples` table, sampled at 1Hz.

### Why 20%?

Intel Turbo Boost reduces frequency when TDP is exceeded. At thermal throttle,
typical frequency reduction is 15–25% depending on workload. The 20% midpoint
is used as a conservative estimate. This constant will be refined in later
model versions using measured turbostat data.

---

## Provenance

| Column | Method ID | Type | Confidence |
|--------|-----------|------|-----------|
| L0 columns | `rapl_msr_pkg_energy` | MEASURED | 1.0 |
| L1 background | `energy_attribution_v1` | CALCULATED | 0.95 |
| L1 interrupt | `energy_attribution_v1` | INFERRED | 0.95 |
| L2 network/io | `energy_attribution_v1` | INFERRED | 0.95 |
| L2 memory | `energy_attribution_v1` | INFERRED | 0.95 |
| L3 orchestration | `energy_attribution_v1` | CALCULATED | 0.95 |
| L3 phases | `phase_attribution_cpu_v1` | CALCULATED | 0.95 |
| L4 llm_compute | `energy_attribution_v1` | CALCULATED | 0.95 |
| Thermal penalty | `thermal_penalty_weighted` | INFERRED | 0.85 |
| Unattributed | `energy_attribution_v1` | CALCULATED | 0.95 |

---

## Views

### `v_energy_normalized`

Primary research view. Joins `energy_attribution` + `runs` + `llm_interactions`.
All energy in Joules. Key columns:

| Column | Formula | Unit |
|--------|---------|------|
| `total_energy_j` | `pkg_energy_uj / 1e6` | J |
| `energy_per_token_uj` | `pkg / total_tokens` | µJ/token |
| `avg_power_watts` | `pkg / 1e6 / duration_s` | W |
| `orchestration_ratio` | `orchestration / pkg` | 0–1 |
| `unattributed_ratio` | `unattributed / pkg` | 0–1 |

### `v_attribution_summary`

Per-layer waterfall view for dashboard. All values in Joules + pct of total.
`foreground_energy_j = total_j − background_j` (derived inline, not stored).

### `v_orchestration_overhead`

Research comparison view. Joins attribution with orchestration phase timing.
Used for agentic vs linear orchestration tax analysis.

### `v_outcome_efficiency`

Energy per outcome view. Joins with `normalization_factors`.
Most columns NULL until Chunk 8 outcome tracking is implemented.

---

## References

1. Intel Corporation. *RAPL (Running Average Power Limit) Energy Reporting*, 2023.
2. Barroso, L.A., Hölzle, U. *Energy Proportional Computing*, IEEE Computer, 2007.
3. Panigrahy, D. *A-LEMS Methodology — Section 3: Attribution Model*, 2026.
4. kernel.org. *Power Management in Linux Kernel*, 2024.

---

## Known Limitations (v1)

| Limitation | Impact | Planned Fix |
|-----------|--------|------------|
| `prefill_energy_uj` = NULL | L4 incomplete | Chunk 4 TTFT data |
| `tool_energy_uj` = NULL | L3 incomplete | Chunk 8 outcome tables |
| `energy_per_accepted_answer_uj` = NULL | L5 incomplete | Chunk 8 outcome tables |
| `l1d_cache_misses = 0` on ThinkPad | L2 cache partial | Hardware limitation |
| `voltage_vcore = NULL` on ThinkPad | Not used in attribution | Expected |
| Memory pressure constant (10µJ) empirical | L2 rough estimate | Calibration study |
| Thermal 20% factor empirical | Thermal rough estimate | Turbostat calibration |
