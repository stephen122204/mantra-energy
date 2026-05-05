# Energy Attribution Methodology
**Document:** `research/12-energy-attribution-methodology.md`
**Method ID:** `energy_attribution_v1`
**Confidence:** 0.95
**Layer:** All (AXIS 1-4)
**Supersedes:** Layer model (L0-L5) — replaced by Four-Axis framework

---

## Overview

A-LEMS decomposes every run's energy across four orthogonal axes. This enables
researchers to answer:

- *How much energy was orchestration vs LLM inference?*
- *What fraction was consumed waiting for network IO?*
- *How does energy scale with workflow complexity?*
- *What did each goal actually cost including failures?*

---

## Attribution Model v1 — Four-Axis Framework

```
AXIS 1 — Conservation System (Ground Truth)
  E_pkg = E_core + E_uncore + E_dram          [Hardware partition]
  E_dynamic = E_pkg - E_baseline              [Idle subtraction]
  E_attributed = α_cpu × E_dynamic            [Process attribution]
  E_background = E_dynamic - E_attributed     [Attribution closure]

  Monotonic invariant: 0 ≤ E_attributed ≤ E_dynamic ≤ E_pkg

AXIS 2 — Orthogonal Decompositions (same E_attributed, two views)
  Functional:  E_attributed = E_llm_window + E_orchestration
  Workflow:    E_attributed = E_planning + E_execution
                            + E_synthesis + E_inter_phase

AXIS 3 — System Dynamics Signals (non-conserved observables)
  network_wait_energy_uj  — RAPL slice during network wait windows
  io_wait_energy_uj       — time-fraction during IO blocking
  cache_dram_energy_uj    — dram × (l3_misses / l3_total)
  interrupt_energy_uj     — rate × 0.5µJ × duration_s
  scheduler_energy_uj     — context_switches × 1µJ
  memory_pressure_energy_uj — page_faults × 10µJ
  disk_energy_uj          — bytes × 0.1µJ/KB
  ⚠ NOT conservation partitions — overlapping signals, never summed

AXIS 4 — Goal-Level Economics
  EpG = Σ E_attributed(all attempts) / successful_goals
  OOI = EpG_agentic / EpG_linear
```

---

## Conservation Equations

### AXIS 1A — Hardware Domain Partition
$$E_{pkg} = E_{core} + E_{uncore} + E_{dram}$$

### AXIS 1B — Attribution Closure
$$E_{dynamic} = E_{pkg} - E_{baseline}$$
$$E_{attributed} = \alpha_{cpu} \times E_{dynamic}$$
$$E_{background} = E_{dynamic} - E_{attributed}$$

### AXIS 2A — Functional Partition (two-term, exact)
$$E_{attributed} = E_{llm\_window} + E_{orchestration}$$

where:
- $E_{llm\_window} \equiv$ `llm_compute_energy_uj` (semantic rename, column unchanged)
- $E_{orchestration} = E_{attributed} - E_{llm\_window}$ (residual, exact by construction)

### AXIS 2B — Workflow Phase Partition
$$E_{attributed} = E_{planning} + E_{execution} + E_{synthesis} + E_{inter\_phase}$$

where $E_{inter\_phase} = E_{attributed} - (E_{planning} + E_{execution} + E_{synthesis})$
is the honest residual.

---

## Axis Independence Principle

```
AXIS 1 defines measurable physical quantities
AXIS 2 defines projections of AXIS 1 outputs
AXIS 3 explains variance in AXIS 2 outputs
AXIS 4 aggregates results across AXIS 1-2

No axis redefines variables of another axis.
```

AXIS 2 projections are orthogonal — same E_attributed, two coordinate systems:
$$\Pi_{functional}(E_{attributed}) = \Pi_{workflow}(E_{attributed}) = E_{attributed}$$
$$\Pi_{functional} \perp \Pi_{workflow}$$

---

## Column Mapping

| Column | Axis | Type | Formula |
|--------|------|------|---------|
| pkg_energy_uj | 1A | MEASURED | RAPL MSR |
| core_energy_uj | 1A | MEASURED | RAPL PP0 |
| uncore_energy_uj | 1A | MEASURED | pkg-core-dram |
| dram_energy_uj | 1A | MEASURED | RAPL DRAM |
| baseline_energy_uj | 1A | MEASURED | idle×duration |
| dynamic_energy_uj | 1A | CALCULATED | pkg-baseline |
| cpu_fraction | 1B | MEASURED | proc_ticks/total |
| attributed_energy_uj | 1B | CALCULATED | α_cpu×dynamic |
| background_energy_uj | 1B | CALCULATED | dynamic-attributed |
| llm_compute_energy_uj | 2A | MEASURED | RAPL window slice |
| orchestration_energy_uj | 2A | CALCULATED | attributed-llm_window |
| planning_energy_uj | 2B | MEASURED | RAPL by events |
| execution_energy_uj | 2B | MEASURED | RAPL by events |
| synthesis_energy_uj | 2B | MEASURED | RAPL by events |
| inter_phase_energy_uj | 2B | CALCULATED | attr-Σphases |
| network_wait_energy_uj | 3A | MEASURED/MODELED | RAPL slice / fallback |
| io_wait_energy_uj | 3A | MODELED | time-fraction×attributed |
| cache_dram_energy_uj | 3A | MODELED | dram×miss_ratio |
| interrupt_energy_uj | 3A | MODELED | rate×0.5µJ×dur |
| scheduler_energy_uj | 3A | MODELED | switches×1µJ |
| memory_pressure_energy_uj | 3A | MODELED | faults×10µJ |
| disk_energy_uj | 3A | MODELED | bytes×0.1µJ/KB |
| unattributed_energy_uj | 3A | CALCULATED | pkg-Σlayers |

---

## Validation Queries

```sql
-- AXIS 1A: Hardware partition
SELECT ABS(pkg_energy_uj - core_energy_uj
           - uncore_energy_uj - dram_energy_uj) AS d_hw
FROM energy_attribution WHERE pkg_energy_uj > 0;
-- Expected: < 1% of pkg

-- AXIS 2A: Functional partition (must be exact)
SELECT ABS(r.attributed_energy_uj
           - ea.llm_compute_energy_uj
           - ea.orchestration_energy_uj) AS d1_delta
FROM runs r JOIN energy_attribution ea ON ea.run_id = r.run_id
WHERE r.attributed_energy_uj > 0;
-- Expected: 0 for all rows

-- AXIS 2B: Phase partition (must be exact)
SELECT ABS(r.attributed_energy_uj
           - ea.planning_energy_uj - ea.execution_energy_uj
           - ea.synthesis_energy_uj - ea.inter_phase_energy_uj) AS d2_delta
FROM runs r JOIN energy_attribution ea ON ea.run_id = r.run_id
WHERE ea.planning_energy_uj > 0;
-- Expected: 0 for all rows
```

---

## Known Limitations

1. AXIS 3 signals use literature-derived constants (Hähnel 2012, Molka 2009)
   — not calibrated to specific hardware.
2. E_orchestration is a conservative lower bound — orchestration within
   LLM windows is attributed to E_llm_window.
3. E_background includes A-LEMS instrumentation cost — not separately isolated.
4. cloud energy is client-side only — remote provider GPU energy not captured.
