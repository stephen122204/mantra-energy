# A-LEMS Cross-Layer Four-Axis Energy Attribution Framework
## Platform Reference — Complete Energy Catalogue
**Version:** 2.0  
**Status:** Authoritative — Living Document  
**Scope:** Every energy column, formula, conservation invariant, and
           measurement method in the A-LEMS platform  
**Audience:** Platform developers, researchers, paper authors,
              future agents, external reviewers  
**Related:** `core/database/schema.py` · `core/utils/provenance.py` ·
             `scripts/validate_energy_chain.py` ·
             `scripts/test_exp_integrity.py`

---

## SECTION 1 — One-Page System Overview

### 1.1 System Intuition

```
                    ┌──────────────────────────────────┐
                    │           AXIS 4                 │
                    │     Goal-Level Economics         │
                    │  EpG | OOI | Retry Cost          │
                    │  Success Efficiency | Waste       │
                    └──────────────▲───────────────────┘
                                   │
                                   │  aggregation over runs + attempts
                                   │
       ┌───────────────────────────┼──────────────────────────┐
       │                           │                          │
┌──────▼──────────┐     ┌──────────▼─────────┐    ┌──────────▼────────┐
│    AXIS 3       │     │      AXIS 2         │    │     AXIS 2        │
│ System Signals  │     │  Functional View    │    │  Workflow View    │
│                 │     │                     │    │                   │
│ network_wait    │     │  E_attributed =     │    │  E_attributed =   │
│ io_wait         │◀────│  E_llm_window       │    │  E_planning       │
│ cache_miss      │     │  + E_orchestration  │    │  + E_execution    │
│ interrupt       │     │                     │    │  + E_synthesis    │
│ scheduler       │     │  [AXIS 2A]          │    │  + E_inter_phase  │
│ cpu_wait        │     └─────────────────────┘    │                   │
│                 │                                 │  [AXIS 2B]        │
│ explanatory     │     ◀── orthogonal projections ──▶               │
│ regressors only │     of the same conserved scalar                  │
└──────▲──────────┘     └─────────────────────────────────────────────┘
       │                                   │
       │                                   │  same E_attributed
       │                                   │
       └───────────────────────────────────┘
                                   │
                          ┌────────▼─────────┐
                          │     AXIS 1       │
                          │ Physical Energy  │
                          │ (Conservation)   │
                          │                  │
                          │  E_pkg           │
                          │  ├── E_core      │
                          │  ├── E_uncore    │
                          │  └── E_dram      │
                          │                  │
                          │  E_dynamic       │
                          │  = E_pkg         │
                          │  - E_baseline    │
                          │                  │
                          │  E_attributed    │
                          │  = α_cpu         │
                          │  × E_dynamic     │
                          └──────────────────┘
```

**One-line definition:**

> *A-LEMS defines energy in agentic AI systems as a conserved scalar
> field measured at hardware level (AXIS 1), projected into orthogonal
> semantic decompositions (AXIS 2), explained via system-level regressors
> (AXIS 3), and aggregated into goal-level economics (AXIS 4).*

---

### 1.2 Formal Energy Core

**Conservation Tree (AXIS 1):**

```
E_pkg   = E_core + E_uncore + E_dram          [Hardware partition]
E_dynamic = E_pkg - E_baseline                [Idle subtraction]
E_attributed = α_cpu × E_dynamic              [Process attribution]
E_background = (1 - α_cpu) × E_dynamic        [Attribution closure]

Monotonic invariant:
  0 ≤ E_attributed ≤ E_dynamic ≤ E_pkg
```

**Decomposition (AXIS 2 — two orthogonal projections):**

```
Functional:  E_attributed = E_llm_window + E_orchestration
Workflow:    E_attributed = E_planning + E_execution
                          + E_synthesis + E_inter_phase

Cross-layer invariant:
  Π_functional(E_attributed) = Π_workflow(E_attributed) = E_attributed
  Π_functional ⊥ Π_workflow
```

**Signal Model (AXIS 3 — post-hoc explanatory regression):**

```
E_orch / E_attributed = β₀ + β₁x₁ + β₂x₂ + β₃x₃ + β₄x₄ + β₅x₅ + ε

where x = [network_wait_ratio, io_wait_ratio, cache_ratio,
           interrupt_ratio, scheduler_ratio, cpu_wait_ratio]

This is E[E_orch | x] — descriptive, not causal inference.
AXIS 3 does NOT define energy. It explains variance in AXIS 2.
```

**Goal Economics (AXIS 4):**

```
E_goal = Σᵢ E_attributed(i)  for all attempts i of goal g
EpG    = E_goal / N_successful_goals
OOI    = EpG_agentic / EpG_linear
```

---

### 1.3 Core System Invariants

| Invariant | Formula | Tolerance |
|-----------|---------|-----------|
| Hardware partition | `E_pkg = E_core + E_uncore + E_dram` | < 1% of E_pkg |
| Idle subtraction | `E_dynamic = E_pkg - E_baseline` | exact |
| Process attribution | `E_dynamic = E_attributed + E_background` | < 1000 µJ |
| Functional partition | `E_attributed = E_llm_window + E_orchestration` | exact |
| Workflow partition | `E_attributed = Σ phases` | exact |
| Goal rollup | `E_goal = Σ E_attributed(attempts)` | < 1000 µJ |

---

### 1.4 Column Quick Navigation

| Column | Axis | Section |
|--------|------|---------|
| pkg_energy_uj | 1A | §5 |
| core_energy_uj | 1A | §5 |
| uncore_energy_uj | 1A | §5 |
| dram_energy_uj | 1A | §5 |
| baseline_energy_uj | 1A | §5 |
| dynamic_energy_uj | 1A | §5 |
| cpu_fraction | 1B | §6 |
| attributed_energy_uj | 1B | §6 |
| background_energy_uj | 1B | §6 |
| framework_overhead_energy_uj | 1B | §6 |
| llm_compute_energy_uj | 2A | §7 |
| orchestration_energy_uj | 2A | §7 |
| prefill_energy_uj | 2A | §8 |
| decode_energy_uj | 2A | §8 |
| llm_wait_energy_uj | 2A | §8 |
| planning_energy_uj | 2B | §9 |
| execution_energy_uj | 2B | §9 |
| synthesis_energy_uj | 2B | §9 |
| inter_phase_energy_uj | 2B | §9 |
| tool_energy_uj | 2A sub | §10 |
| retry_energy_uj | 2A sub | §10 |
| failed_tool_energy_uj | 2A sub | §10 |
| rejected_generation_energy_uj | 2A sub | §10 |
| network_wait_energy_uj | 3A | §11 |
| io_wait_energy_uj | 3A | §11 |
| cache_dram_energy_uj | 3A | §11 |
| interrupt_energy_uj | 3A | §11 |
| scheduler_energy_uj | 3A | §11 |
| memory_pressure_energy_uj | 3A | §11 |
| disk_energy_uj | 3A | §11 |
| thermal_penalty_energy_uj | 3A | §11 |
| unattributed_energy_uj | 3A | §11 |
| energy_per_solved_task_uj | 4 | §14 |
| energy_per_completion_token_uj | 4 | §14 |
| energy_per_successful_step_uj | 4 | §14 |
| energy_per_accepted_answer_uj | 4 | §14 |

---

## SECTION 2 — Platform Measurement Goals

A-LEMS is a measurement platform, not a single-paper system. This
document governs the platform permanently. Research papers are
downstream consumers of platform output — they do not define it.

The platform measures energy at every layer of the agentic AI stack:

```
Hardware silicon     → AXIS 1 (conservation, ground truth)
Runtime attribution  → AXIS 1B (cpu_fraction model)
Workflow semantics   → AXIS 2 (functional and phase projections)
System physics       → AXIS 3 (resource signals and regressors)
Mission outcomes     → AXIS 4 (goal-level economics)
```

Any energy-related research claim about LLM workloads can be verified
using the conservation checks, SQL queries, and validation scripts
defined in this document. The platform supports:

- Energy cost of agentic vs linear workflows
- Provider comparison (local vs remote energy economics)
- Carbon, water, and compute cost of goal completion
- Tool execution energy patterns
- Retry and failure energy waste quantification
- Memory and cache pressure from long context windows
- Thermal throttling energy penalties
- Phase-level energy distribution across workflow lifecycle

---

## SECTION 3 — Formal Mathematical Definition

### 3.1 Primitive Objects and Notation

Let:
- **R** = set of all runs (measurement executions)
- **T_r** = time interval of run r ∈ R
- **S** = system energy state space (RAPL-observed signals over T_r)
- **G** = set of goals, where each goal g ∈ G has attempts A_g ⊆ R

Define the primitive observable:

```
E_pkg(r) ∈ ℝ⁺  — total hardware energy for run r
                  measured by RAPL MSR over T_r
                  this is the ONLY directly measured energy quantity
```

All other energy quantities are derived from E_pkg.

### 3.2 AXIS 1 — Physical Conservation System

**Definition:** AXIS 1 is the hardware-constrained energy conservation
system. It is divided into two sub-systems.

**AXIS 1A — Physical Energy Tree:**

The hardware domain partition:
```
E_pkg = E_core + E_uncore + E_dram
```

where:
- E_core   = CPU core energy (RAPL PP0 domain, MSR 0x639)
- E_uncore = Uncore energy (LLC, memory controller, iGPU)
- E_dram   = DRAM energy (RAPL PP1/DRAM domain, MSR 0x61C)

The idle subtraction:
```
E_dynamic = E_pkg - E_baseline
```

where E_baseline = P_idle × duration_s × 10⁶ µJ, measured from
a controlled idle period using the 2-sigma stable baseline protocol.

**AXIS 1B — Attribution Closure Layer:**

Define the CPU attribution function:
```
α_cpu(r) ∈ [0,1]
α_cpu(r) = workload_cpu_ticks / total_system_cpu_ticks
```

measured via `/proc/stat` (total ticks) and `/proc/[pid]/stat`
(workload ticks) sampled over T_r.

Then:
```
E_attributed = α_cpu × E_dynamic        [process attribution]
E_background = (1 - α_cpu) × E_dynamic  [attribution closure]
```

Conservation constraint:
```
E_dynamic = E_attributed + E_background
```

**Important:** E_background is NOT a hardware node. It is a
statistical closure term — the energy not attributed to the
workload process. It includes uncontrolled system processes
AND A-LEMS measurement overhead. These are not separately
decomposed in the conservation model.

**Monotonic invariant:**
```
0 ≤ E_attributed ≤ E_dynamic ≤ E_pkg
```

This holds by construction: α_cpu ∈ [0,1] and E_baseline ≥ 0.

**E_attributed is the fundamental platform unit.** All AXIS 2, 3,
and 4 computations operate on E_attributed, not on E_pkg.

### 3.3 AXIS 2 — Orthogonal Decomposition Space

**Definition:** AXIS 2 defines multiple orthogonal projections of
E_attributed. These are NOT additional energy — they are
re-partitions of the same conserved scalar.

Define the attributed energy space:
```
ε = {E_attributed(r) : r ∈ R}
```

**AXIS 2A — Functional Projection:**

Define projection operator:
```
Π_func : E_attributed → (E_llm_window, E_orchestration)
```

such that:
```
E_attributed = E_llm_window + E_orchestration
E_llm_window ∩ E_orchestration = ∅
E_llm_window ∪ E_orchestration = E_attributed
```

where:
- E_llm_window   = energy during LLM inference windows
                   (≡ llm_compute_energy_uj, column name retained
                    for backward compatibility)
- E_orchestration = E_attributed − E_llm_window
                    (residual — guaranteed to balance by construction)

**AXIS 2B — Workflow Projection:**

Define projection operator:
```
Π_phase : E_attributed → (E_planning, E_execution, E_synthesis, E_inter)
```

such that:
```
E_attributed = E_planning + E_execution + E_synthesis + E_inter_phase
```

where E_inter_phase = E_attributed − (E_planning + E_execution + E_synthesis)
is the honest residual capturing phase coverage gaps.

**Orthogonality Constraint:**
```
Π_func ⊥ Π_phase
```

meaning the two projections are independent decompositions of the
same space. They can be cross-tabulated:

```
"What fraction of E_planning is E_llm_window?"
```

is a valid analytical query. This cross-tabulation is a novel
analytical capability of the A-LEMS platform.

**Cross-Layer Invariance:**
```
Π_func(E_attributed) = Π_phase(E_attributed) = E_attributed
```

The same conserved scalar is observed through multiple orthogonal
projections. Neither projection creates or destroys energy.

### 3.4 AXIS 3 — System Dynamics and Signal Space

**Definition:** AXIS 3 is a stochastic explanatory model over AXIS 2
outputs. It does NOT define energy. It explains variance in AXIS 2
decompositions using system-observable signals.

**AXIS 3A — Physical Observables:**

Define signal vector for run r:
```
X(r) = [x₁, x₂, x₃, x₄, x₅, x₆]ᵀ

where:
  x₁ = network_wait_energy_uj / E_attributed  [network wait ratio]
  x₂ = io_wait_energy_uj / E_attributed       [IO wait ratio]
  x₃ = cache_dram_energy_uj / E_attributed    [cache miss ratio]
  x₄ = interrupt_energy_uj / E_attributed     [interrupt ratio]
  x₅ = scheduler_energy_uj / E_attributed     [scheduler ratio]
  x₆ = cpu_percent_during_wait / 100          [CPU wait utilization]
```

These signals are:
- Candidate causal variables (may explain orchestration variance)
- Observability indicators (prove regime shifts, e.g. CPU≈0 but
  pkg non-zero during remote wait)
- NOT energy partitions
- NOT conservation components
- NEVER summed — they overlap

**AXIS 3B — Statistical Explanation Model:**

We define a descriptive regression model:

```
E_orch / E_attributed = β₀ + βᵀX + ε

Equivalently:
E[E_orch / E_attributed | X] = f_θ(X)
```

Expanded form:
```
E_orch / E_attributed = β₀ + β₁x₁ + β₂x₂ + β₃x₃
                            + β₄x₄ + β₅x₅ + β₆x₆ + ε
```

**Critical framing — what AXIS 3B is NOT:**

- NOT a decomposition of energy (β coefficients are NOT energy partitions)
- NOT part of conservation (does not affect AXIS 1 invariants)
- NOT used in ETL (does not modify stored energy values)
- NOT causal inference (correlation, not causation)
- NOT used in validation checks

**What AXIS 3B IS:**

- A post-hoc descriptive regression
- Explains variance in E_orchestration / E_attributed
- Identifies which system signals are predictive of orchestration dominance
- Enables the claim: "orchestration energy variance is predictable from
  OS-level signals without modifying the conservation model"

**Three research contributions this enables:**

1. Separation of measurement from explanation — conservation holds
   independently of what explains the values
2. Traceable observability — which system activity causes orchestration
   energy to be high can be quantified
3. Predictive model — OS-level signals predict energy fractions before
   full measurement is complete

### 3.5 AXIS 4 — Goal-Level Energy Economics

**Definition:** AXIS 4 is a temporal aggregation layer over AXIS 1-2
outputs. It operates at a different granularity — per goal, not per run.

Define goal function:
```
g : R → G   (maps runs to goals)
```

For goal g with attempt set A_g:
```
E_goal(g) = Σ_{r ∈ A_g} E_attributed(r)
```

**Energy per Successful Goal (EpG):**
```
EpG = Σ_{g ∈ G_success} E_goal(g) / |G_success|
```

**Failure decomposition:**

Let R_g^s = successful runs, R_g^f = failed runs for goal g:
```
E_goal = E_success + E_waste
E_success = Σ_{r ∈ R_g^s} E_attributed(r)
E_waste   = Σ_{r ∈ R_g^f} E_attributed(r)
```

**Orchestration Overhead Index (OOI):**
```
OOI = EpG_agentic / EpG_linear
```

**Derived economics:**
```
Retry_cost_per_success = E_waste / |G_success|
Success_efficiency     = E_success / E_goal
Failure_fraction       = E_waste / E_goal
```

**AXIS 4 conservation invariant:**
```
E_goal(g) = Σ_{a ∈ A_g} goal_attempt.energy_uj(a)
```

**Important:** AXIS 4 is aggregation over time and attempts — NOT a
physical decomposition. It inherits conservation from AXIS 1 but
does not add new physical constraints.

### 3.6 Master Structural Invariant — Axis Consistency Principle

```
AXIS 1  defines measurable physical quantities
AXIS 2  defines projections of AXIS 1 outputs
AXIS 3  explains variance in AXIS 2 outputs
AXIS 4  aggregates results across AXIS 1-2 over attempts

No axis is allowed to redefine variables of another axis.
This is the non-negotiable invariant of the A-LEMS framework.
```

Formally:
```
AXIS 3 signals: X → variance in AXIS 2 (not → E directly)
AXIS 2 projections: Π(E_attributed) = E_attributed (not → new energy)
AXIS 4 aggregation: Σ E_attributed(r) → goal-space (not → new physics)
```

### 3.7 Theorems

**Theorem 1 — Energy Conservation Invariance:**

For all runs r ∈ R:
```
E_pkg(r) = E_core(r) + E_uncore(r) + E_dram(r)  ± ε₁
E_attributed(r) = E_llm_window(r) + E_orch(r)   ± ε₂
E_attributed(r) = Σᵢ E_phase_i(r)               ± ε₃
```
where ε₁ < 1% × E_pkg, ε₂ = 0 (exact, by construction), ε₃ = 0 (exact).

**Theorem 2 — Cross-Axis Orthogonality:**

Let AXIS 2 projections be Π_func, Π_phase. Then:
```
Π_func(E_attributed) = E_attributed
Π_phase(E_attributed) = E_attributed
Π_func ≠ Π_phase
```

Therefore AXIS 2 defines non-unique decompositions of a conserved
scalar field. The same energy is observable through multiple
independent coordinate systems.

**Theorem 3 — Signal Predictability of Orchestration:**
```
E_orch = f(X) × E_attributed  where f(X) ∈ [0,1]
```

AXIS 3 signals define a bounded energy fraction estimator. The
bound f(X) ∈ [0,1] follows from E_orch ≤ E_attributed by Theorem 1.

---

## SECTION 4 — Measurement Type Taxonomy

Every column carries one of five measurement types. These govern
confidence level and citation requirements.

**MEASURED**
Hardware-observed energy over a time interval.
Applies to: full-run RAPL reads AND RAPL window slices.
The phrase "over a time interval" makes this valid whether the
interval is the full run duration or a timestamp-bounded window.
Platform-agnostic: RAPL on Linux x86, IOKit on macOS.
Example: `pkg_energy_uj`, `planning_energy_uj`

**CALCULATED**
Deterministic formula applied to MEASURED values.
No assumptions beyond the formula itself. Zero uncertainty from
modeling — uncertainty comes only from input measurements.
Example: `orchestration_energy_uj = attributed - llm_compute`

**MODELED**
Proportionality model applied to measured values.
Assumes energy is proportional to time or counter fraction:
`E_signal = (time_fraction or counter_ratio) × E_total`
This assumption is documented. Confidence lower than CALCULATED.
Constants used in MODELED columns are from published literature
(see Section 30 for references).
Example: `network_wait_energy_uj`, `interrupt_energy_uj`

**INFERRED**
Uses external constants, emission factors, or ML models.
Lowest measurement confidence.
Example: `carbon_g`, `water_ml` (emission factor × energy)

**SYSTEM**
Infrastructure metadata. No scientific energy meaning.
Example: `run_id`, `workflow_type`, `attribution_method` (string)

---

## SECTION 5 — Physical Energy Tree (AXIS 1A)

### 5.1 pkg_energy_uj

**[AXIS 1A] [MEASURED] [Confidence: 1.0]**

**Definition:**
Total processor package energy measured by Intel RAPL over the run
duration. This is the hardware ground truth — the only directly
measured energy quantity in the entire system. All other energy
values are derived from, or validated against, this value.

**Formula:**
```
E_pkg = RAPL_MSR_0x611_end - RAPL_MSR_0x611_start  [µJ]
```

**Conservation role:**
`E_pkg = E_core + E_uncore + E_dram`  (AXIS 1A partition)

**Tables:** `runs.pkg_energy_uj`, `energy_attribution.pkg_energy_uj`

**Platform notes:**
- Linux x86: Intel RAPL MSR 0x611 (Package Energy Status)
- macOS: IOKit power source (lower confidence)
- ARM VM: EnergyEstimator (INFERRED, confidence 0.0)

**RAPL reference:** Intel Software Developer Manual Vol. 3B, §14.9.1

**Validation:**
```sql
SELECT run_id,
    ABS(pkg_energy_uj - core_energy_uj
        - uncore_energy_uj - dram_energy_uj) AS delta_uj,
    ROUND(ABS(pkg_energy_uj - core_energy_uj
        - uncore_energy_uj - dram_energy_uj) * 100.0
        / pkg_energy_uj, 3) AS delta_pct
FROM energy_attribution
WHERE pkg_energy_uj > 0 AND core_energy_uj > 0
ORDER BY delta_pct DESC LIMIT 10;
-- Expected: delta_pct < 1.0 for all rows
```

---

### 5.2 core_energy_uj

**[AXIS 1A] [MEASURED] [Confidence: 1.0]**

**Definition:**
Energy consumed by CPU cores — the arithmetic and logic units
performing computation. Does not include memory controller,
last-level cache, or DRAM. High during LLM decode for local models.
Near-zero during remote API wait (cores idle while network blocks).

**Formula:**
```
E_core = RAPL_MSR_0x639_end - RAPL_MSR_0x639_start  [µJ]
```

**Conservation role:** D4 component: `E_pkg = E_core + E_uncore + E_dram`

**Tables:** `runs.core_energy_uj`, `energy_attribution.core_energy_uj`

---

### 5.3 uncore_energy_uj

**[AXIS 1A] [MEASURED] [Confidence: 1.0]**

**Definition:**
Energy consumed by uncore components: last-level cache (LLC),
memory controller, integrated GPU, PCIe links. Critically:
uncore energy remains NON-ZERO during remote API wait periods
even when CPU cores are idle. This is direct hardware evidence
that orchestration energy is non-trivial even at low CPU utilization.

**Formula:**
```
E_uncore = E_pkg - E_core - E_dram  [µJ]
(on platforms without direct uncore MSR)
```

**Tables:** `runs.uncore_energy_uj`, `energy_attribution.uncore_energy_uj`

---

### 5.4 dram_energy_uj

**[AXIS 1A] [MEASURED] [Confidence: 1.0]**

**Definition:**
Energy consumed by DRAM (main memory). Significant for LLM
workloads due to large context windows causing sustained memory
pressure. Like uncore, DRAM energy is NON-ZERO during remote
API wait — the memory subsystem manages streaming buffers even
when the CPU is blocking. This is a key hardware-level explanation
for why E_orchestration is non-zero during remote provider calls.

**Formula:**
```
E_dram = RAPL_MSR_0x61C_end - RAPL_MSR_0x61C_start  [µJ]
```

**Tables:** `runs.dram_energy_uj`, `energy_attribution.dram_energy_uj`

---

### 5.5 baseline_energy_uj

**[AXIS 1A] [MEASURED] [Confidence: 1.0]**

**Definition:**
The energy the system would have consumed doing nothing useful
over the same duration. Measured during a controlled idle period
before the experiment using a 2-sigma stable baseline protocol.
Subtracted from E_pkg to isolate workload-caused energy.

**Formula:**
```
E_baseline = P_idle_watts × task_duration_s × 1,000,000  [µJ]
P_idle from: idle_baselines table, matched by hardware profile
```

**Conservation role:** D3a: `E_dynamic = E_pkg - E_baseline`

**Table:** `runs.baseline_energy_uj`

---

### 5.6 dynamic_energy_uj

**[AXIS 1A] [CALCULATED] [Confidence: 1.0]**

**Definition:**
Energy above the idle baseline — caused by the workload AND all
concurrent system processes (cron, sshd, systemd, A-LEMS itself).
This is the energy the workload caused to exist in the system,
but not all of it belongs to the workload process alone.

**Formula:**
```
E_dynamic = E_pkg - E_baseline  [µJ]
```

**Conservation role:** D3a result. D3b anchor.

**Table:** `runs.dynamic_energy_uj`

**Important:** Lives in `runs` table ONLY. Not in `energy_attribution`.
All views requiring this column must JOIN `runs`.

**Validation:**
```sql
SELECT r.run_id,
    ABS(r.dynamic_energy_uj
        - (r.pkg_energy_uj - r.baseline_energy_uj)) AS delta_uj
FROM runs r
WHERE r.pkg_energy_uj > 0
ORDER BY delta_uj DESC LIMIT 10;
-- Expected: delta_uj = 0 for all rows (CALCULATED)
```

---

## SECTION 6 — Attribution Closure Layer (AXIS 1B)

### 6.1 cpu_fraction

**[AXIS 1B] [MEASURED] [Confidence: 0.95]**

**Definition:**
The fraction of total system CPU time consumed by the workload
process during the run. This is the attribution factor that
isolates the workload's share of dynamic energy from the energy
of all other concurrent system processes.

A value of 0.85 means the workload consumed 85% of all CPU ticks
during the measurement window. It is therefore attributed 85% of
dynamic energy.

**Formula:**
```
α_cpu = workload_cpu_ticks / total_system_cpu_ticks

workload_cpu_ticks: from /proc/[pid]/stat (utime + stime)
total_cpu_ticks:    from /proc/stat (user + nice + system + idle + ...)
both sampled at run start and end, delta taken
```

**Method:** `cpu_fraction_attribution` (confidence: 0.95)

**Table:** `runs.cpu_fraction`

**Known limitation:**
cpu_fraction is accurate for CPU-bound workloads. When the workload
causes other processes to do work on its behalf (e.g., kernel network
stack during remote API calls), that work appears in other processes'
ticks and is not captured. This makes E_attributed a conservative
lower bound on true workload energy — a documented, acceptable
limitation. The error is small compared to total E_attributed.

---

### 6.2 attributed_energy_uj ← AUTHORITATIVE SOURCE: runs TABLE

**[AXIS 1B] [CALCULATED] [Confidence: 0.95]**

**Definition:**
Energy attributed to the workload process. This is the fundamental
A-LEMS measurement unit. All AXIS 2 decompositions, AXIS 3 signal
ratios, and AXIS 4 economics are computed relative to this value.

It represents the workload's fair share of dynamic energy based
on CPU utilization fraction — the energy the workload is responsible
for, excluding background system activity.

**Formula:**
```
E_attributed = α_cpu × E_dynamic  [µJ]
```

**Conservation role:**
- AXIS 1B closure: `E_dynamic = E_attributed + E_background`
- AXIS 2A anchor: `E_attributed = E_llm_window + E_orchestration`
- AXIS 2B anchor: `E_attributed = Σ phases`

**Table:** `runs.attributed_energy_uj` ← AUTHORITATIVE

**Critical architecture note:**
`energy_attribution` ETL reads this from `runs` as INPUT.
It does not store its own copy. All views must pull from
`runs.attributed_energy_uj` when joining to `energy_attribution`.

**Validation:**
```sql
SELECT r.run_id,
    ABS(r.attributed_energy_uj
        - (r.cpu_fraction * r.dynamic_energy_uj)) AS delta_uj
FROM runs r
WHERE r.dynamic_energy_uj > 0 AND r.cpu_fraction IS NOT NULL
ORDER BY delta_uj DESC LIMIT 10;
```

---

### 6.3 background_energy_uj

**[AXIS 1B] [CALCULATED] [Confidence: 1.0]**

**Definition:**
Dynamic energy NOT attributed to the workload process. Includes
energy from uncontrolled system processes (cron, sshd, systemd,
other users) AND from A-LEMS measurement infrastructure itself.
These two components are not separately decomposed — background
is a single closure term for D3b conservation validation.

**Formula:**
```
E_background = E_dynamic - E_attributed
             = (1 - α_cpu) × E_dynamic  [µJ]
```

**Conservation role:** D3b closure: `E_dynamic = E_attributed + E_background`

**Table:** `energy_attribution.background_energy_uj`

**Validation:**
```sql
SELECT r.run_id,
    ABS(r.dynamic_energy_uj - r.attributed_energy_uj
        - ea.background_energy_uj) AS delta_uj
FROM runs r
JOIN energy_attribution ea ON ea.run_id = r.run_id
WHERE r.dynamic_energy_uj > 0
ORDER BY delta_uj DESC LIMIT 10;
-- Expected: delta_uj < 1000 for all rows
```

---

### 6.4 framework_overhead_energy_uj ← MEASUREMENT TRANSPARENCY

**[AXIS 1B diagnostic] [MEASURED] [Confidence: 1.0]**

**Definition:**
The energy consumed by the A-LEMS measurement framework itself
during the experiment. Computed from pre-task and post-task RAPL
windows — the energy cost of instrumentation, timing, database
writes, and sampling that A-LEMS performs around the workload.

This is a **novel metric**. Most energy measurement systems do not
account for the energy cost of measurement itself. A-LEMS explicitly
captures E_measurement and separates it from workload energy,
enabling honest reporting of net workload energy and quantification
of measurement overhead.

**Formula:**
```
E_measurement = pre_task_energy_uj + post_task_energy_uj  [µJ]
```

**Conservation role:**
E_measurement ⊆ E_background — it is NOT part of E_attributed.
It is inside the background energy that was NOT attributed to
the workload process. Stored separately for transparency.

**Table:** `runs.framework_overhead_energy_uj`

**Research note:**
The ratio `E_measurement / E_attributed` quantifies measurement
overhead as a fraction of workload energy. This should be reported
in any paper using A-LEMS data to demonstrate measurement validity.

---

### 6.5 attribution_coverage_pct

**[AXIS 1B] [CALCULATED] [Confidence: 1.0]**

**Definition:**
The percentage of E_pkg that the attribution model can account for.
Computed as `(E_pkg - unattributed_energy_uj) / E_pkg × 100`.
A value of 95% means 95% of hardware energy is explained by the
attribution model. Residual 5% is `unattributed_energy_uj`.

**Formula:**
```
coverage_pct = (E_pkg - E_unattributed) / E_pkg × 100  [%]
```

**Table:** `energy_attribution.attribution_coverage_pct`

---

### 6.6 attribution_method

**[AXIS 1B] [SYSTEM]**

**Definition:**
String identifier of the attribution method used for this run.
Values:
- `sample_based_v2` — RAPL window slice (MEASURED, confidence 0.97)
- `time_fraction_fallback_v1` — time-fraction proxy (MODELED, confidence 0.70)

Used to filter runs by measurement quality in research queries.

**Table:** `energy_attribution.attribution_method`

---

## SECTION 7 — Functional Projection (AXIS 2A)

### 7.1 llm_compute_energy_uj  ≡  E_llm_window

**[AXIS 2A] [MEASURED] [Confidence: 0.97]**

**Definition:**
Energy during LLM inference windows — the time intervals when the
system is actively engaged in an LLM call, from when the request
is sent (`request_start_ns`) to when the last token is received
(`last_token_time_ns`).

Column name `llm_compute_energy_uj` is retained for backward
compatibility. The semantic name is **E_llm_window**.

**Provider semantics:**

For **LOCAL providers** (tinyllama, ollama): this window is
compute-dominated — prefill (prompt encoding) and decode
(token generation). CPU is high. Core energy is elevated.

For **REMOTE providers** (groq, openai, gemini): the model runs
on the provider's infrastructure. Our client machine is primarily
waiting. CPU≈0. However, E_llm_window is still non-zero because
DRAM and uncore remain active for streaming buffer management.

**Remote provider policy (explicit):**
For remote providers, LLM inference occurs off-device. All
client-side energy during LLM interaction (wait + streaming)
is attributed to E_orchestration. E_llm_window captures only
the small residual client-side energy during the inference window.
No energy is missing — this assignment is explicit platform policy.

**Formula:**
```
E_llm_window = Σ_interactions RAPL_sample_slice(request_start_ns,
                                                 last_token_time_ns)
             × α_cpu  [µJ]

RAPL_sample_slice(t_start, t_end) =
  Σ (pkg_energy_uj[i] - pkg_energy_uj[i-1])
    for all samples i where timestamp_ns ∈ [t_start, t_end]
```

**Fallback (when timestamps NULL):**
```
E_llm_window = (local_compute_ms / task_duration_ms) × E_attributed
attribution_method = 'time_fraction_fallback_v1'
```

**Conservation role:** AXIS 2A partition.
`E_attributed = E_llm_window + E_orchestration`

**Table:** `energy_attribution.llm_compute_energy_uj`

**Validation:**
```sql
SELECT r.run_id,
    ABS(r.attributed_energy_uj
        - ea.llm_compute_energy_uj
        - ea.orchestration_energy_uj) AS delta_uj
FROM runs r
JOIN energy_attribution ea ON ea.run_id = r.run_id
WHERE r.attributed_energy_uj > 0
ORDER BY delta_uj DESC LIMIT 10;
-- Expected: delta_uj = 0 (exact — CALCULATED residual)
```

---

### 7.2 orchestration_energy_uj  ≡  E_orchestration

**[AXIS 2A] [CALCULATED] [Confidence: 0.95]**

**Definition:**
All workload energy OUTSIDE LLM inference windows. Everything
the system expends on non-model work: deciding what to call,
waiting for remote responses, executing tools, handling failures
and retries, managing conversation state, HTTP overhead,
database writes, tokenizer calls.

This includes BOTH productive work (tool execution produces
useful results) AND coordination overhead (retry handling,
dispatch logic). The word "orchestration" is not a pejorative —
it describes the work of coordinating a multi-step agentic system.

For remote providers: all client-side energy during LLM interaction
(network wait + streaming) is here because the orchestration system
chose to call a remote provider. The wait is an orchestration cost.

**Formula:**
```
E_orchestration = E_attributed - E_llm_window  [µJ]
(residual — guaranteed to balance by construction)
```

**Conservative lower bound note:**
Orchestration activity WITHIN LLM inference windows (stream
handling, token callbacks, partial JSON parsing) is conservatively
attributed to E_llm_window. E_orchestration therefore understates
true orchestration energy cost. The thesis holds under this
conservative attribution — if anything, true dominance is greater.

**Partition invariant:**
```
E_llm_window ∩ E_orchestration = ∅   (mutually exclusive)
E_llm_window ∪ E_orchestration = E_attributed  (exhaustive)
```

**Table:** `energy_attribution.orchestration_energy_uj`

---

## SECTION 8 — LLM Window Sub-partition (AXIS 2A, Conditional)

Sub-window decomposition is performed ONLY when timestamp
boundaries are available. When NULL, the parent E_llm_window
remains valid and is reported without further partitioning.

> *"Sub-window decomposition of LLM interaction energy is performed
> only when timestamp boundaries are available; otherwise, the
> aggregate window energy is reported without further partitioning."*

This is not a limitation — it reflects honest measurement boundaries.

---

### 8.1 prefill_energy_uj

**[AXIS 2A sub] [MEASURED] [Confidence: 0.97]**

**Definition:**
Energy during the prompt encoding phase — from when the LLM
request is sent to when the first token is received.

For local models: high-CPU burst as model processes all prompt
tokens simultaneously (parallel prefill).
For remote providers: primarily network round-trip latency.

**Formula:**
```
E_prefill = RAPL_sample_slice(request_start_ns, first_token_time_ns)
          × α_cpu  [µJ]
```

**Condition:** `request_start_ns IS NOT NULL AND first_token_time_ns IS NOT NULL`

**Tables:** `energy_attribution.prefill_energy_uj`,
            `llm_interactions.prefill_energy_uj`

**Known NULL cases:**
- tinyllama linear runs: no streaming tokens, first_token_time_ns never set
- Pre-migration-038 runs: request_start_ns not captured

---

### 8.2 decode_energy_uj

**[AXIS 2A sub] [MEASURED] [Confidence: 0.97]**

**Definition:**
Energy during the token generation phase — from first token
received to last token received.

For local models: sustained CPU computation for autoregressive
decode (one token per forward pass).
For remote providers: streaming receive overhead.

**Formula:**
```
E_decode = RAPL_sample_slice(first_token_time_ns, last_token_time_ns)
         × α_cpu  [µJ]
```

**Table:** `energy_attribution.decode_energy_uj`

---

### 8.3 llm_wait_energy_uj  ← Diagnostic Subset

**[AXIS 2A diagnostic] [MODELED] [Confidence: 0.85]**

**Definition:**
Energy during LLM interaction windows that is wait-dominated
rather than compute-dominated. Primarily meaningful for remote
provider runs where the client blocks on API response.

**KEY INSIGHT:** This value is NON-ZERO even when
`cpu_percent_during_wait ≈ 0`. DRAM and uncore remain active
during remote blocking — streaming buffers, memory controller
activity, network interrupt handling. This is the empirical
foundation proving orchestration energy is non-trivial at low CPU.

**Formula:**
```
E_llm_wait = (non_local_ms / task_duration_ms) × E_attributed  [µJ]
```

**Conservation rule:** DIAGNOSTIC ONLY.
- This IS part of E_orchestration (via remote provider policy)
- Do NOT sum with E_orchestration — already included
- Do NOT sum with E_llm_window — overlaps for remote providers
- Use only for insight analysis and AXIS 3 regression

**Table:** `energy_attribution.llm_wait_energy_uj`

---

## SECTION 9 — Workflow Phase Projection (AXIS 2B)

AXIS 2B splits E_attributed by workflow lifecycle phase.
It is a PARALLEL view to AXIS 2A — not nested inside it.
Each phase contains BOTH E_llm_window AND E_orchestration components.

AXIS 2A answers WHAT type of work consumed energy.
AXIS 2B answers WHERE in the workflow lifecycle energy was spent.

Cross-tabulation example:
```sql
-- What fraction of planning phase is LLM window vs orchestration?
SELECT
    ea.planning_energy_uj,
    r.attributed_energy_uj,
    -- approximate LLM fraction of planning using run-level ratio
    ea.planning_energy_uj
        * ea.llm_compute_energy_uj / NULLIF(r.attributed_energy_uj, 0)
        AS planning_llm_est_uj,
    ea.planning_energy_uj
        * ea.orchestration_energy_uj / NULLIF(r.attributed_energy_uj, 0)
        AS planning_orch_est_uj
FROM energy_attribution ea
JOIN runs r ON r.run_id = ea.run_id
WHERE r.workflow_type = 'agentic';
```

---

### 9.1 planning_energy_uj

**[AXIS 2B] [MEASURED] [Confidence: 0.98]**

**Definition:**
Energy during the planning phase — when the orchestration system
decides what steps to take, which tools to call, how to decompose
the goal. Includes LLM calls made during planning AND orchestration
between them.

Near-zero for linear workflows (no planning phase exists).
Growth of planning energy with task complexity is secondary
evidence for orchestration dominance.

**Formula:**
```
E_planning = Σ orchestration_events.attributed_energy_uj
             WHERE phase = 'planning'

Fallback: runs.planning_energy_uj when events table empty
```

**Method:** `phase_attribution_sample_v2` (confidence: 0.98)

**Tables:** `energy_attribution.planning_energy_uj`,
            `runs.planning_energy_uj`

---

### 9.2 execution_energy_uj

**[AXIS 2B] [MEASURED] [Confidence: 0.98]**

**Definition:**
Energy during the execution phase — carrying out the plan:
tool calls, processing results, LLM calls for sub-tasks.
Typically the highest-energy phase for agentic workflows.

**Formula:**
```
E_execution = Σ orchestration_events.attributed_energy_uj
              WHERE phase = 'execution'
```

**Tables:** `energy_attribution.execution_energy_uj`,
            `runs.execution_energy_uj`

---

### 9.3 synthesis_energy_uj

**[AXIS 2B] [MEASURED] [Confidence: 0.98]**

**Definition:**
Energy during the synthesis phase — assembling the final response
from intermediate results. Typically the shortest phase.

**Formula:**
```
E_synthesis = Σ orchestration_events.attributed_energy_uj
              WHERE phase = 'synthesis'
```

**Tables:** `energy_attribution.synthesis_energy_uj`,
            `runs.synthesis_energy_uj`

---

### 9.4 inter_phase_energy_uj  ← Honest Residual

**[AXIS 2B] [CALCULATED] [Confidence: 0.98]**

**Definition:**
Energy in transitions between phases not captured by
orchestration_events timestamps. This is an honest residual —
it acknowledges that phase event coverage is not 100%.
Non-zero values indicate phase coverage gaps, not errors.
Makes AXIS 2B always balance to E_attributed by construction.

**Formula:**
```
E_inter_phase = E_attributed
              - E_planning - E_execution - E_synthesis  [µJ]
```

**Conservation:** Guarantees AXIS 2B partition sums to E_attributed.

**Tables:** `energy_attribution.inter_phase_energy_uj`,
            `runs.inter_phase_energy_uj`

**Validation:**
```sql
SELECT r.run_id,
    ABS(r.attributed_energy_uj
        - ea.planning_energy_uj - ea.execution_energy_uj
        - ea.synthesis_energy_uj - ea.inter_phase_energy_uj) AS delta_uj
FROM runs r
JOIN energy_attribution ea ON ea.run_id = r.run_id
WHERE r.attributed_energy_uj > 0 AND ea.planning_energy_uj > 0
ORDER BY delta_uj DESC LIMIT 10;
-- Expected: delta_uj = 0 (exact — CALCULATED residual)
```

---

## SECTION 10 — Orchestration Sub-components

These are named subsets of E_orchestration for diagnostic analysis.
They OVERLAP — they do NOT sum to E_orchestration.
They MUST NOT be added to conservation equations.

---

### 10.1 tool_energy_uj

**[AXIS 2A sub] [MODELED] [Confidence: 0.95]**

**Definition:**
Energy attributable to tool execution — calculator, database
queries, file reads, API calls. This is PRODUCTIVE energy —
tools do useful work. It is a subset of E_orchestration, not
separate from it.

**Formula:**
```
E_tool = (tool_cpu_time_ns / run_duration_ns) × E_attributed  [µJ]
OR direct RAPL slice when tool window > 1 sample interval (~10ms)
```

**Known limitation:** Tools completing faster than one RAPL sample
interval (~10ms) use time-fraction — less accurate for fast tools.

**Table:** `energy_attribution.tool_energy_uj`

---

### 10.2 retry_energy_uj

**[AXIS 2A sub] [CALCULATED] [Confidence: 0.90]**

**Definition:**
Energy consumed by failed attempts that were retried — wasted
energy. The system spent real resources on work that did not
contribute to the final successful goal. Key metric for
understanding the energy cost of failure recovery.

**Formula:**
```
E_retry = Σ attributed_energy_uj for all failed attempt runs  [µJ]
```

**Table:** `energy_attribution.retry_energy_uj`

**Conservation note:** Subset of E_orchestration. Do NOT sum.

---

### 10.3 failed_tool_energy_uj

**[AXIS 2A sub] [CALCULATED] [Confidence: 0.90]**

**Definition:**
Energy consumed specifically by tool calls that failed.
Subset of retry_energy_uj — do NOT sum both.

**Formula:**
```
E_tool_fail = Σ tool_failure_events.wasted_energy_uj  [µJ]
```

**Table:** `energy_attribution.failed_tool_energy_uj`

**Conservation note:** Subset of retry_energy_uj AND E_orchestration.

---

### 10.4 rejected_generation_energy_uj

**[AXIS 2A sub] [CALCULATED] [Confidence: 0.90]**

**Definition:**
Energy consumed by LLM generations that were rejected due to
hallucination detection or quality failure. May overlap with
retry_energy_uj if rejection triggered a retry.

**Formula:**
```
E_rejected = Σ hallucination_events.wasted_energy_uj  [µJ]
```

**Table:** `energy_attribution.rejected_generation_energy_uj`

---

## SECTION 11 — System Dynamics Signals (AXIS 3A)

These columns are OBSERVATIONAL CHARACTERIZATIONS — not conservation
partitions. They are derived from system counters and explain the
physical mechanisms behind AXIS 2 decomposition values.

**Rules for all AXIS 3A columns:**
- NEVER summed with each other
- NEVER included in conservation equations
- NEVER used to define or modify energy values
- ONLY used as regressors in AXIS 3B or for diagnostic insight

**How to use these signals:**
1. Physics explanation: why is E_orchestration non-zero at low CPU?
2. Provider comparison: remote vs local energy patterns
3. Optimization targeting: which overhead to reduce in future work
4. AXIS 3B regression inputs

---

### 11.1 network_wait_energy_uj

**[AXIS 3A] [MODELED → MEASURED after BUG-E1 fix] [Confidence: 0.95]**

**Definition:**
Energy correlated with network IO blocking periods — when the
system waits for a remote LLM API response. The critical finding:
this value is NON-ZERO even though `cpu_percent_during_wait ≈ 0`,
because DRAM and uncore components stay active for streaming
buffer management. This is the hardware-level explanation for
why remote providers exhibit significant E_orchestration.

**Formula (primary — MEASURED when timestamps available):**
```
E_network_wait = Σ_interactions RAPL_sample_slice(
                   request_start_ns, first_token_time_ns) × α_cpu  [µJ]
```

**Formula (fallback — MODELED when timestamps unavailable):**
```
E_network_wait = (non_local_ms / task_duration_ms) × E_attributed  [µJ]
```

**Table:** `energy_attribution.network_wait_energy_uj`

**Literature basis:**
Hähnel et al. (2012) validated RAPL accuracy for short windows,
confirming that energy during blocking IO periods is measurable
and non-trivial even at low CPU utilization.

---

### 11.2 io_wait_energy_uj

**[AXIS 3A] [MODELED] [Confidence: 0.95]**

**Definition:**
Energy correlated with disk IO wait periods — process blocked
on storage reads/writes. Primarily database writes (experiment
results, energy samples) and model file reads.

**Formula:**
```
E_io_wait = (io_block_time_ms / task_duration_ms) × E_attributed  [µJ]
Base: E_attributed (NOT E_pkg — corrected from earlier bug)
Source: io_samples.io_block_time_ms
```

**Table:** `energy_attribution.io_wait_energy_uj`

---

### 11.3 cache_dram_energy_uj

**[AXIS 3A] [MODELED] [Confidence: 0.95]**

**Definition:**
DRAM energy attributable to L3 cache misses. Large LLM context
windows cause cache thrashing, repeatedly fetching token
representations from DRAM.

**Formula:**
```
E_cache = E_dram × (l3_cache_misses / (l3_cache_hits + l3_cache_misses))
```

**Literature basis:**
Molka et al. (2009) measured DRAM energy per cache miss on Intel
Nehalem: ~65 nJ per L3 miss. The ratio-based formula is preferred
over per-miss constants because it uses directly measured DRAM
energy rather than estimated constants.

**Table:** `energy_attribution.cache_dram_energy_uj`

---

### 11.4 interrupt_energy_uj

**[AXIS 3A] [MODELED] [Confidence: 0.65]**

**Definition:**
Energy correlated with interrupt handling overhead. High during
streaming token receipt (each token triggers network interrupts).

**Formula:**
```
E_interrupt = interrupt_rate × C_interrupt × duration_s  [µJ]

C_interrupt = 0.5 µJ/interrupt
```

**Constant source:**
Hähnel et al. (2012), "Measuring Energy Consumption for Short
Code Paths Using RAPL," SIGMETRICS Performance Evaluation Review,
measured interrupt handling energy on Intel Sandy Bridge: 0.3–0.7 µJ
per interrupt depending on interrupt type. We use 0.5 µJ as the
midpoint estimate. Confidence: 0.65 — literature-derived, not
hardware-calibrated for UBUNTU2505.

**Table:** `energy_attribution.interrupt_energy_uj`

---

### 11.5 scheduler_energy_uj

**[AXIS 3A] [MODELED] [Confidence: 0.65]**

**Definition:**
Energy correlated with context switching overhead. Each context
switch costs CPU cycles for register save/restore and TLB flush.

**Formula:**
```
E_scheduler = total_context_switches × C_switch  [µJ]

C_switch = 1 µJ/switch
```

**Constant source:**
Molka et al. (2009), "Memory Performance and Energy Consumption
of Modern Multi-Core Processors," measured context switch energy
on Intel Nehalem: 0.8–1.2 µJ per switch. We use 1.0 µJ as the
midpoint. Confidence: 0.65 — literature-derived.

**Table:** `energy_attribution.scheduler_energy_uj`

---

### 11.6 memory_pressure_energy_uj

**[AXIS 3A] [MODELED] [Confidence: 0.65]**

**Definition:**
Energy correlated with DRAM pressure from page faults. Large
LLM context windows cause cache thrashing and page faults.

**Formula:**
```
E_memory_pressure = minor_page_faults × C_fault  [µJ]

C_fault = 10 µJ/fault
```

**Constant source:**
Derived from Molka et al. (2009) L3 miss energy (65 nJ) scaled
to page fault granularity (4KB page = ~154 cache lines, sequential
miss cost ≈ 10 µJ). Confidence: 0.65 — literature-derived.

**Table:** `energy_attribution.memory_pressure_energy_uj`

---

### 11.7 disk_energy_uj

**[AXIS 3A] [MODELED] [Confidence: 0.60]**

**Definition:**
Energy correlated with storage operations. Proxy from disk
throughput × energy per byte constant.

**Formula:**
```
E_disk = (disk_read_bytes + disk_write_bytes) / 1024 × 0.1 µJ/KB  [µJ]
```

**Constant source:**
David et al. (2010), "Memory Power Management via Dynamic
Voltage/Frequency Scaling," provides storage energy estimates.
0.1 µJ/KB is a conservative estimate for SSD reads on modern
hardware. Confidence: 0.60 — lowest confidence signal.

**Table:** `energy_attribution.disk_energy_uj`

---

### 11.8 thermal_penalty_energy_uj

**[AXIS 3A] [INFERRED] [Confidence: 0.85]**

**Definition:**
Energy attributable to thermal throttling — when the processor
reduces frequency to manage heat. The workload takes longer and
consumes more energy than it would at full speed.

**Formula:**
```
E_thermal = E_pkg × throttle_ratio × PENALTY_FRACTION

throttle_ratio = Σ(throttled_interval_ns) / total_run_ns
  (from thermal_samples WHERE cpu_temp > threshold)
```

**Table:** `energy_attribution.thermal_penalty_energy_uj`

---

### 11.9 unattributed_energy_uj  ← Measurement Residual

**[AXIS 3A] [CALCULATED] [Confidence: 1.0]**

**Definition:**
The measurement residual — energy in E_pkg that the attribution
model cannot account for. Ideally zero. Non-zero values indicate
gaps in the decomposition. Tracked via `attribution_coverage_pct`.

In research reports: state this as measurement uncertainty.
A value < 5% of E_pkg is acceptable.

**Formula:**
```
E_unattributed = max(0, E_pkg - (E_baseline + E_background
                 + E_llm_window + E_orchestration
                 + E_thermal_penalty))  [µJ]
```

**Table:** `energy_attribution.unattributed_energy_uj`

```sql
-- Attribution coverage check
SELECT
    ROUND(AVG(attribution_coverage_pct), 2) AS avg_coverage_pct,
    ROUND(MIN(attribution_coverage_pct), 2) AS min_coverage_pct,
    COUNT(*) AS runs
FROM energy_attribution WHERE pkg_energy_uj > 0;
-- Expected: avg_coverage_pct > 90
```

---

## SECTION 12 — Statistical Explanation Model (AXIS 3B)

### 12.1 Model Specification

AXIS 3B is a descriptive regression model over AXIS 2 outputs.
It is NOT part of conservation. It does NOT define energy.

**Dependent variable:**
```
y = E_orchestration / E_attributed ∈ [0, 1]
```

**Independent variables (ratio form, normalized by E_attributed):**
```
x₁ = network_wait_energy_uj / attributed_energy_uj
x₂ = io_wait_energy_uj / attributed_energy_uj
x₃ = cache_dram_energy_uj / attributed_energy_uj
x₄ = interrupt_energy_uj / attributed_energy_uj
x₅ = scheduler_energy_uj / attributed_energy_uj
x₆ = cpu_percent_during_wait / 100
```

**Model:**
```
y = β₀ + β₁x₁ + β₂x₂ + β₃x₃ + β₄x₄ + β₅x₅ + β₆x₆ + ε

E[E_orch / E_attributed | X] = f_θ(X)
```

### 12.2 Critical Framing Rules

**What AXIS 3B is NOT:**

- NOT a decomposition of energy (β values are NOT energy partitions)
- NOT part of conservation (does not affect AXIS 1 invariants)
- NOT used in ETL computation (does not modify stored values)
- NOT causal inference (this is conditional expectation, not causation)
- NOT used in validation checks

**What AXIS 3B IS:**

- A post-hoc descriptive regression explaining variance in y
- Identifies which system signals are predictive of orchestration dominance
- Enables the statement: *"orchestration energy variance is predictable
  from OS-level signals without modifying the conservation model"*

### 12.3 Estimation Method

OLS regression, per-run aggregation:

1. Aggregate all signals per run_id from `energy_attribution`
2. Normalize each signal by `attributed_energy_uj`
3. Fit OLS on runs where `attributed_energy_uj > 0`
4. Report R², coefficients, and standard errors

### 12.4 SQL Reference Query

```sql
-- Extract regression variables per run
SELECT
    ea.run_id,
    r.workflow_type,
    e.provider,
    -- Dependent variable
    ea.orchestration_energy_uj * 1.0
        / NULLIF(r.attributed_energy_uj, 0)         AS y_orch_fraction,
    -- Independent variables (ratio form)
    ea.network_wait_energy_uj * 1.0
        / NULLIF(r.attributed_energy_uj, 0)         AS x1_network,
    ea.io_wait_energy_uj * 1.0
        / NULLIF(r.attributed_energy_uj, 0)         AS x2_io,
    ea.cache_dram_energy_uj * 1.0
        / NULLIF(r.attributed_energy_uj, 0)         AS x3_cache,
    ea.interrupt_energy_uj * 1.0
        / NULLIF(r.attributed_energy_uj, 0)         AS x4_interrupt,
    ea.scheduler_energy_uj * 1.0
        / NULLIF(r.attributed_energy_uj, 0)         AS x5_scheduler,
    -- cpu_wait from llm_interactions (average per run)
    COALESCE(li.avg_cpu_wait, 0) / 100.0            AS x6_cpu_wait
FROM energy_attribution ea
JOIN runs r ON r.run_id = ea.run_id
JOIN experiments e ON e.exp_id = r.exp_id
LEFT JOIN (
    SELECT run_id,
           AVG(cpu_percent_during_wait) AS avg_cpu_wait
    FROM llm_interactions
    GROUP BY run_id
) li ON li.run_id = ea.run_id
WHERE r.attributed_energy_uj > 0
  AND ea.orchestration_energy_uj IS NOT NULL
  AND e.experiment_type != 'debug'
ORDER BY ea.run_id;
```

### 12.5 Three Research Contributions

1. **Separation of measurement from explanation:** Conservation holds
   independently of what AXIS 3 signals explain. The measurement
   system is not contaminated by the explanatory model.

2. **Traceable observability:** Which system activity causes high
   E_orchestration can be quantified with regression coefficients.
   A high β₁ (network) means remote providers drive orchestration.
   A high β₃ (cache) means long contexts drive local orchestration.

3. **Predictive model:** OS-level signals predict energy fractions
   before full measurement is complete — useful for online monitoring.

---

## SECTION 13 — Goal-Level Energy Economics (AXIS 4)

AXIS 4 operates at a different granularity than AXIS 1-3.
AXIS 1-3 are per-run. AXIS 4 is per-goal (aggregates across runs).

### 13.1 Energy per Successful Goal (EpG)

**[AXIS 4] [CALCULATED] [Confidence: 1.0]**

**Definition:**
Total energy across ALL attempts for a goal (including failures
and retries) divided by successfully completed goals. This is
the platform's primary outcome metric.

**Formula:**
```
E_goal(g) = Σ_{r ∈ A_g} E_attributed(r)

EpG = Σ_{g ∈ G_success} E_goal(g) / |G_success|  [µJ]
EpG_J = EpG / 1,000,000  [J]
```

**Column:** `goal_execution.total_energy_uj / successful_goals`

**Query:**
```sql
SELECT
    ge.workflow_type,
    AVG(ge.total_energy_uj) / 1e6   AS avg_epg_j,
    COUNT(*)                         AS goals
FROM goal_execution ge
JOIN experiments e ON ge.exp_id = e.exp_id
WHERE e.experiment_type != 'debug'
  AND ge.success = 1
GROUP BY ge.workflow_type;
```

---

### 13.2 Orchestration Overhead Index (OOI)

**[AXIS 4] [CALCULATED] [Confidence: 1.0]**

**Definition:**
Ratio of agentic EpG to linear EpG under matched output token
volume. Quantifies the energy multiplier of orchestration structure.
OOI = 3.97 means agentic workflows cost 3.97× more per successful
goal than equivalent linear workflows.

**Formula:**
```
OOI = EpG_agentic / EpG_linear
```

**Query:**
```sql
SELECT
    agentic.avg_epg / linear.avg_epg AS ooi
FROM
    (SELECT AVG(total_energy_uj) AS avg_epg
     FROM goal_execution ge
     JOIN experiments e ON ge.exp_id = e.exp_id
     WHERE ge.workflow_type = 'agentic'
       AND ge.success = 1
       AND e.experiment_type != 'debug') agentic,
    (SELECT AVG(total_energy_uj) AS avg_epg
     FROM goal_execution ge
     JOIN experiments e ON ge.exp_id = e.exp_id
     WHERE ge.workflow_type = 'linear'
       AND ge.success = 1
       AND e.experiment_type != 'debug') linear;
```

---

### 13.3 Failure and Waste Decomposition

**[AXIS 4] [CALCULATED]**

```
E_goal = E_success + E_waste

E_success = attributed_energy_uj of winning run only
E_waste   = Σ attributed_energy_uj of all failed attempt runs

failure_fraction    = E_waste / E_goal
success_efficiency  = E_success / E_goal
retry_cost_per_goal = E_waste / |G_success|
```

**Columns:** `goal_execution.successful_energy_uj`,
             `goal_execution.overhead_energy_uj`

---

### 13.4 AXIS 4 Conservation Invariant

```
E_goal(g) = Σ_{a ∈ A_g} goal_attempt.energy_uj(a)
```

**Validation:**
```sql
SELECT ge.goal_id,
    ge.total_energy_uj,
    SUM(ga.energy_uj) AS attempt_sum,
    ABS(ge.total_energy_uj - SUM(ga.energy_uj)) AS delta_uj
FROM goal_execution ge
JOIN goal_attempt ga ON ga.goal_id = ge.goal_id
WHERE ga.energy_uj IS NOT NULL
GROUP BY ge.goal_id
HAVING delta_uj > 1000
ORDER BY delta_uj DESC;
-- Expected: 0 rows
```

---

## SECTION 14 — Normalized Outcome Metrics

### 14.1 energy_per_completion_token_uj

**[AXIS 4] [CALCULATED]**

**Definition:**
Energy cost per output token generated. Normalizes runs with
different response lengths for fair comparison across models.

**Formula:** `E_attributed / completion_tokens  [µJ/token]`

**Table:** `energy_attribution.energy_per_completion_token_uj`

---

### 14.2 energy_per_successful_step_uj

**[AXIS 4] [CALCULATED]**

**Definition:**
Energy per successfully completed workflow step, accounting for
steps that failed and had to be retried.

**Formula:** `E_attributed / successful_steps  [µJ/step]`

---

### 14.3 energy_per_accepted_answer_uj

**[AXIS 4] [CALCULATED]**

**Definition:**
Energy per non-hallucinated accepted answer. Requires
`output_quality` table to be populated.

**Formula:** `E_attributed / accepted_answers  [µJ/answer]`

---

### 14.4 energy_per_solved_task_uj  ≡  EpG per run

**[AXIS 4] [CALCULATED]**

**Definition:**
EpG computed at run level — useful for per-run analysis.

**Formula:** `E_attributed / solved_tasks  [µJ/task]`

---

## SECTION 15 — Energy-Adjacent Time and Rate Metrics

These are not energy columns but they FEED energy attribution
and explain physical mechanisms. Required for understanding
AXIS 2 and AXIS 3 column derivations.

### 15.1 orchestration_cpu_ms  [runs]

**Definition:** CPU milliseconds consumed by orchestration logic
outside LLM call windows. The time-domain analog of E_orchestration.
Used in `v_orchestration_overhead.ooi_time` for time-domain OOI.

**Formula:** `Σ cpu_time_ms for between-LLM-call intervals`

---

### 15.2 non_local_ms  [llm_interactions]

**Definition:** Milliseconds waiting for remote LLM response per
interaction. Client blocked, CPU≈0, but RAPL shows non-zero pkg.
The TIME evidence supporting the ENERGY finding in
`network_wait_energy_uj`. The key observable for proving
orchestration energy is non-trivial at low CPU.

**Feeds:** `network_wait_energy_uj` computation

---

### 15.3 cpu_percent_during_wait  [llm_interactions]

**Definition:** CPU utilization percentage during `non_local_ms`
wait period. The critical observable: proves CPU≈0 during remote
wait while RAPL shows non-zero pkg draw.

This is the empirical foundation of the platform's key finding.
Paper figures should show this alongside `network_wait_energy_uj`.

**Query for key finding:**
```sql
SELECT
    li.non_local_ms,
    li.cpu_percent_during_wait,
    ea.network_wait_energy_uj / 1e6  AS network_wait_j,
    ea.llm_wait_energy_uj    / 1e6   AS llm_wait_j,
    e.provider,
    r.workflow_type
FROM llm_interactions li
JOIN runs r ON r.run_id = li.run_id
JOIN experiments e ON e.exp_id = r.exp_id
JOIN energy_attribution ea ON ea.run_id = li.run_id
WHERE li.non_local_ms > 100
  AND li.cpu_percent_during_wait < 10
ORDER BY li.non_local_ms DESC;
```

---

### 15.4 request_start_ns, first_token_time_ns, last_token_time_ns

**[llm_interactions]**

**Definition:** Epoch nanosecond timestamps defining LLM inference
window boundaries. These three timestamps enable RAPL window slicing
for E_llm_window, E_prefill, and E_decode measurement.

- `request_start_ns` → start of inference window (added migration 038)
- `first_token_time_ns` → prefill/decode boundary
- `last_token_time_ns` → end of inference window

When any timestamp is NULL: fallback to time-fraction MODELED.

---

## SECTION 16 — Conservation Verification Summary

All conservation checks must pass after every experiment run.

```sql
-- Run all four invariants at once
SELECT
    'D4_hardware' AS check_name,
    COUNT(*) AS runs,
    ROUND(AVG(ABS(pkg_energy_uj - core_energy_uj
        - uncore_energy_uj - dram_energy_uj)), 0) AS avg_delta_uj,
    MAX(ABS(pkg_energy_uj - core_energy_uj
        - uncore_energy_uj - dram_energy_uj)) AS max_delta_uj
FROM energy_attribution
WHERE pkg_energy_uj > 0 AND core_energy_uj > 0

UNION ALL

SELECT
    'D1_functional',
    COUNT(*),
    ROUND(AVG(ABS(r.attributed_energy_uj
        - ea.llm_compute_energy_uj
        - ea.orchestration_energy_uj)), 0),
    MAX(ABS(r.attributed_energy_uj
        - ea.llm_compute_energy_uj
        - ea.orchestration_energy_uj))
FROM energy_attribution ea
JOIN runs r ON r.run_id = ea.run_id
WHERE r.attributed_energy_uj > 0

UNION ALL

SELECT
    'D3b_attribution',
    COUNT(*),
    ROUND(AVG(ABS(r.dynamic_energy_uj
        - r.attributed_energy_uj
        - ea.background_energy_uj)), 0),
    MAX(ABS(r.dynamic_energy_uj
        - r.attributed_energy_uj
        - ea.background_energy_uj))
FROM energy_attribution ea
JOIN runs r ON r.run_id = ea.run_id
WHERE r.dynamic_energy_uj > 0

UNION ALL

SELECT
    'D2_workflow',
    COUNT(*),
    ROUND(AVG(ABS(r.attributed_energy_uj
        - ea.planning_energy_uj - ea.execution_energy_uj
        - ea.synthesis_energy_uj - ea.inter_phase_energy_uj)), 0),
    MAX(ABS(r.attributed_energy_uj
        - ea.planning_energy_uj - ea.execution_energy_uj
        - ea.synthesis_energy_uj - ea.inter_phase_energy_uj))
FROM energy_attribution ea
JOIN runs r ON r.run_id = ea.run_id
WHERE r.attributed_energy_uj > 0
  AND ea.planning_energy_uj > 0;

-- Expected:
-- D4_hardware:   max_delta_uj < 1% of avg pkg
-- D1_functional: max_delta_uj = 0 (exact by construction)
-- D3b_attribution: max_delta_uj < 1000
-- D2_workflow:   max_delta_uj = 0 (exact by construction)
```

---

## SECTION 17 — Views Inventory

All views read from ETL-populated columns only. Views never
recompute energy — they only format and join existing values.

| View | Purpose | Conservation role |
|------|---------|-----------------|
| `v_attribution_summary` | All energy tiers in Joules per run | Shows all axes |
| `v_energy_normalized` | Per-token and per-second metrics | AXIS 4 ratios |
| `v_fraction_verification` | Verify stored orchestration_fraction | AXIS 2A check |
| `v_orchestration_overhead` | OOI time-domain computation | AXIS 4 |
| `v_goal_energy_decomposition` | Per-goal breakdown | AXIS 4 primary |
| `v_failure_energy_taxonomy` | Wasted energy by failure type | AXIS 2A sub |
| `v_quality_energy_frontier` | Quality vs energy tradeoff | AXIS 4 |
| `energy_samples_with_power` | Instantaneous power from RAPL | AXIS 1A |

**Important:** `v_attribution_summary` pulls `attributed_energy_uj`
from `runs` table (authoritative). `llm_wait_energy_uj` shown in
views is a diagnostic subset — not a separate conservation partition.

---

## SECTION 18 — Known Limitations

1. **E_prefill and E_decode NULL for tinyllama linear:**
   No streaming tokens on linear path → `first_token_time_ns` never
   set. Parent `E_llm_window` remains valid and is reported as
   unsplit. This is documented measurement boundary behavior.

2. **tool_energy_uj MODELED for sub-10ms tools:**
   Tools completing faster than one RAPL sample interval use
   time-fraction. Acceptable for long tools, less accurate for fast
   calculator or dictionary lookup calls.

3. **Cloud energy is client-side only:**
   E_attributed measures energy on the A-LEMS measurement machine.
   Energy consumed by remote provider infrastructure (GPUs at groq,
   openai datacenters) is not captured. A-LEMS measures the
   CLIENT-SIDE cost of orchestration — this is explicitly documented
   and is a feature not a limitation for the research question.

4. **AXIS 3A signals overlap:**
   Resource signals are not mutually exclusive. They must not be
   summed. They are observational characterizations, not partitions.

5. **MODELED constants are literature-derived:**
   interrupt (0.5 µJ), scheduler (1 µJ), memory_pressure (10 µJ)
   constants are from Hähnel 2012 and Molka 2009, not calibrated
   to UBUNTU2505 hardware. Confidence: 0.65 for these columns.

6. **E_orchestration conservative lower bound:**
   Orchestration within LLM windows attributed to E_llm_window.
   True orchestration cost is higher — this makes findings stronger.

7. **background_energy_uj includes A-LEMS cost:**
   The measurement framework's energy is inside E_background.
   `framework_overhead_energy_uj` provides an explicit estimate.

8. **cpu_fraction limitation for remote workloads:**
   When kernel network stack does work on behalf of the workload
   during remote API calls, those CPU ticks appear in system space
   not workload space. E_attributed is a conservative lower bound.

---

## SECTION 19 — Reference Graph Specifications

### Figure 1: E_orchestration vs E_llm_window by Workflow Type
```sql
SELECT r.workflow_type,
    AVG(ea.orchestration_energy_uj / 1e6) AS avg_orchestration_j,
    AVG(ea.llm_compute_energy_uj   / 1e6) AS avg_llm_window_j,
    AVG(r.attributed_energy_uj     / 1e6) AS avg_attributed_j,
    COUNT(*) AS runs
FROM energy_attribution ea
JOIN runs r ON r.run_id = ea.run_id
JOIN experiments e ON e.exp_id = r.exp_id
WHERE e.experiment_type != 'debug'
GROUP BY r.workflow_type;
```
Visualization: Stacked bar. X: workflow type. Y: Energy (J).
Bars: E_llm_window (blue), E_orchestration (orange).

### Figure 2: EpG Distribution Agentic vs Linear
```sql
SELECT r.workflow_type, ge.total_energy_uj / 1e6 AS epg_j
FROM goal_execution ge
JOIN experiments e ON ge.exp_id = e.exp_id
JOIN runs r ON r.run_id = ge.winning_run_id
WHERE e.experiment_type != 'debug' AND ge.success = 1;
```
Visualization: Box plot. X: workflow type. Y: EpG (J).

### Figure 3: CPU% vs pkg Power During LLM Wait (Key Finding)
```sql
SELECT
    li.cpu_percent_during_wait,
    r.pkg_energy_uj / (r.task_duration_ns / 1e9) / 1e6 AS pkg_power_w,
    e.provider
FROM llm_interactions li
JOIN runs r ON r.run_id = li.run_id
JOIN experiments e ON e.exp_id = r.exp_id
WHERE li.non_local_ms > 50;
```
Visualization: Scatter. X: CPU%. Y: pkg power (W). Color: provider.
Shows CPU≈0 but power non-zero for remote providers.

### Figure 4: Orchestration Fraction vs Complexity
```sql
SELECT ge.orchestration_fraction, r.complexity_score, r.workflow_type
FROM goal_execution ge
JOIN runs r ON r.run_id = ge.winning_run_id
WHERE ge.orchestration_fraction IS NOT NULL;
```
Visualization: Scatter with regression line. X: complexity. Y: fraction.

### Figure 5: Four-Axis Cube (Conceptual)
See Section 1.1 ASCII diagram. Render as SVG for paper.

### Figure 6: Causal DAG of Energy Formation
```
RAPL Hardware
     ↓ [AXIS 1A — physical measurement]
E_pkg → E_dynamic → E_attributed
     ↓ [AXIS 1B — attribution closure]
     ↓ [AXIS 2 — orthogonal projections]
E_llm_window | E_orchestration
E_planning | E_execution | E_synthesis
     ↑ [AXIS 3 — explanatory regressors]
network_wait, io_wait, cache, interrupt
cpu_percent_during_wait
     ↓ [AXIS 4 — goal aggregation]
EpG, OOI, retry_cost, failure_fraction
```

---

## SECTION 20 — Literature References

1. **Intel Software Developer Manual, Volume 3B** (2023).
   Chapter 14.9: Running Average Power Limit (RAPL) Interface.
   Intel Corporation. Defines MSR addresses and energy units.

2. **Hähnel, M., Döbel, B., Völp, M., Härtig, H.** (2012).
   "Measuring Energy Consumption for Short Code Paths Using RAPL."
   SIGMETRICS Performance Evaluation Review, 40(3), 13-17.
   Source for: interrupt energy constants, RAPL accuracy validation.

3. **Molka, D., Hackenberg, D., Schöne, R., Müller, M.** (2009).
   "Memory Performance and Energy Consumption of Modern Multi-Core
   Processors." SPEC Benchmark Workshop.
   Source for: DRAM energy per cache miss (~65 nJ), context switch
   energy constants (0.8-1.2 µJ).

4. **David, H., Gorbatov, E., Hanebutte, U., Khanna, R., Le, C.**
   (2010). "RAPL: Memory Power Estimation and Capping."
   IEEE/ACM International Symposium on Low Power Electronics.
   Source for: DRAM energy access models, storage energy estimates.

5. **Green Software Foundation** (2023).
   Software Carbon Intensity Specification v1.0.
   Source for: carbon_g, water_ml, methane_mg emission factors.

6. **MLPerf Power Working Group** (2022).
   MLPerf Power v1.0 Measurement Methodology.
   Comparison reference for whole-system power measurement.

---

## SECTION 21 — Glossary

| Term | Definition | Axis | Column |
|------|-----------|------|--------|
| E_pkg | Total processor package energy from RAPL | 1A | pkg_energy_uj |
| E_core | CPU core energy, PP0 RAPL domain | 1A | core_energy_uj |
| E_uncore | Uncore energy (LLC, memory controller) | 1A | uncore_energy_uj |
| E_dram | DRAM energy, PP1/DRAM RAPL domain | 1A | dram_energy_uj |
| E_baseline | System idle energy over run duration | 1A | baseline_energy_uj |
| E_dynamic | Energy above idle baseline | 1A | dynamic_energy_uj |
| α_cpu | CPU tick fraction of workload process | 1B | cpu_fraction |
| E_attributed | Workload's fair share of dynamic energy | 1B | attributed_energy_uj |
| E_background | Dynamic energy not attributed to workload | 1B | background_energy_uj |
| E_measurement | A-LEMS instrumentation energy | 1B | framework_overhead_energy_uj |
| E_llm_window | Energy during LLM inference windows | 2A | llm_compute_energy_uj |
| E_orchestration | All non-LLM-inference workload energy | 2A | orchestration_energy_uj |
| E_prefill | Energy in prompt encoding window | 2A | prefill_energy_uj |
| E_decode | Energy in token generation window | 2A | decode_energy_uj |
| E_llm_wait | Wait-dominated subset of E_llm_window | 2A diag | llm_wait_energy_uj |
| E_planning | Energy in planning phase events | 2B | planning_energy_uj |
| E_execution | Energy in execution phase events | 2B | execution_energy_uj |
| E_synthesis | Energy in synthesis phase events | 2B | synthesis_energy_uj |
| E_inter_phase | Phase coverage residual | 2B | inter_phase_energy_uj |
| E_tool | Tool execution energy subset | 2A sub | tool_energy_uj |
| E_recovery | Retry attempt energy (wasted) | 2A sub | retry_energy_uj |
| E_network | Network wait signal | 3A | network_wait_energy_uj |
| E_io | IO wait signal | 3A | io_wait_energy_uj |
| E_cache | L3 cache miss DRAM signal | 3A | cache_dram_energy_uj |
| E_residual | Unaccounted measurement gap | 3A | unattributed_energy_uj |
| EpG | Energy per Successful Goal | 4 | energy_per_solved_task_uj |
| OOI | Orchestration Overhead Index = EpG_agentic/EpG_linear | 4 | — |
| E/token | Energy per output token | 4 | energy_per_completion_token_uj |
| RAPL | Running Average Power Limit — Intel x86 hardware energy counter | — | — |
| RAPL slice | RAPL energy delta over a timestamp-bounded window | — | — |
| MEASURED | Hardware-observed energy over a time interval | — | — |
| CALCULATED | Deterministic formula on measured values | — | — |
| MODELED | Proportionality model — time/counter × energy | — | — |
| INFERRED | External constants or ML models | — | — |

---

## APPENDIX A — Column Quick Reference

All energy columns in one table.

| Column | Table | Axis | Type | Formula (short) |
|--------|-------|------|------|----------------|
| pkg_energy_uj | runs, ea | 1A | MEASURED | RAPL MSR delta |
| core_energy_uj | runs, ea | 1A | MEASURED | RAPL PP0 delta |
| uncore_energy_uj | runs, ea | 1A | MEASURED | pkg-core-dram |
| dram_energy_uj | runs, ea | 1A | MEASURED | RAPL DRAM delta |
| baseline_energy_uj | runs | 1A | MEASURED | idle×duration |
| dynamic_energy_uj | runs | 1A | CALCULATED | pkg-baseline |
| cpu_fraction | runs | 1B | MEASURED | proc_ticks/total_ticks |
| attributed_energy_uj | runs | 1B | CALCULATED | cpu_frac×dynamic |
| background_energy_uj | ea | 1B | CALCULATED | dynamic-attributed |
| framework_overhead_energy_uj | runs | 1B diag | MEASURED | pre+post energy |
| attribution_coverage_pct | ea | 1B | CALCULATED | (pkg-unattr)/pkg |
| llm_compute_energy_uj | ea | 2A | MEASURED | RAPL window slice |
| orchestration_energy_uj | ea | 2A | CALCULATED | attributed-llm_window |
| prefill_energy_uj | ea,li | 2A | MEASURED | RAPL[req→first_token] |
| decode_energy_uj | ea | 2A | MEASURED | RAPL[first→last_token] |
| llm_wait_energy_uj | ea | 2A diag | MODELED | non_local_ms/dur×attr |
| planning_energy_uj | ea,runs | 2B | MEASURED | RAPL by events |
| execution_energy_uj | ea,runs | 2B | MEASURED | RAPL by events |
| synthesis_energy_uj | ea,runs | 2B | MEASURED | RAPL by events |
| inter_phase_energy_uj | ea,runs | 2B | CALCULATED | attr-Σphases |
| tool_energy_uj | ea | 2A sub | MODELED | tool_time/dur×attr |
| retry_energy_uj | ea | 2A sub | CALCULATED | Σ failed attempt attr |
| failed_tool_energy_uj | ea | 2A sub | CALCULATED | Σ tool_failure wasted |
| rejected_generation_energy_uj | ea | 2A sub | CALCULATED | Σ hallucination wasted |
| network_wait_energy_uj | ea | 3A | MODELED | non_local/dur×attr |
| io_wait_energy_uj | ea | 3A | MODELED | io_block/dur×attr |
| cache_dram_energy_uj | ea | 3A | MODELED | dram×miss_ratio |
| interrupt_energy_uj | ea | 3A | MODELED | rate×0.5µJ×dur |
| scheduler_energy_uj | ea | 3A | MODELED | switches×1µJ |
| memory_pressure_energy_uj | ea | 3A | MODELED | faults×10µJ |
| disk_energy_uj | ea | 3A | MODELED | bytes/1KB×0.1µJ |
| thermal_penalty_energy_uj | ea | 3A | INFERRED | pkg×throttle_ratio |
| unattributed_energy_uj | ea | 3A | CALCULATED | pkg-Σlayers |
| energy_per_completion_token_uj | ea | 4 | CALCULATED | attr/tokens |
| energy_per_successful_step_uj | ea | 4 | CALCULATED | attr/steps |
| energy_per_accepted_answer_uj | ea | 4 | CALCULATED | attr/accepted |
| energy_per_solved_task_uj | ea | 4 | CALCULATED | Σattr/goals |

*ea = energy_attribution table, li = llm_interactions table*

---

## APPENDIX B — Provenance Cross-Reference

| Column | method_id | Confidence | Type |
|--------|-----------|-----------|------|
| pkg_energy_uj | rapl_msr_pkg_energy | 1.0 | MEASURED |
| attributed_energy_uj | cpu_fraction_attribution | 0.95 | CALCULATED |
| background_energy_uj | energy_attribution_v1 | 0.95 | CALCULATED |
| llm_compute_energy_uj | llm_energy_sample_v2 | 0.97 | MEASURED |
| orchestration_energy_uj | energy_attribution_v1 | 0.95 | CALCULATED |
| planning_energy_uj | phase_attribution_sample_v2 | 0.98 | MEASURED |
| network_wait_energy_uj | energy_attribution_v1 | 0.95 | MODELED |
| interrupt_energy_uj | energy_attribution_v1 | 0.65 | MODELED |
| thermal_penalty_energy_uj | thermal_penalty_weighted | 0.85 | INFERRED |

---

## APPENDIX C — Platform Compatibility

| Column group | Linux x86 | macOS | ARM VM |
|-------------|-----------|-------|--------|
| pkg/core/dram (RAPL) | MEASURED (1.0) | IOKit stub | INFERRED (0.0) |
| cpu_fraction | MEASURED (0.95) | MEASURED (0.95) | MEASURED (0.95) |
| AXIS 2 (window slices) | MEASURED (0.97) | MODELED | MODELED |
| AXIS 3 signals | MODELED (0.65-0.95) | MODELED | MODELED |
| AXIS 4 (aggregations) | CALCULATED (1.0) | CALCULATED (1.0) | CALCULATED (1.0) |

Primary development and measurement platform: UBUNTU2505 (Linux x86, RAPL).

---

*End of A-LEMS Cross-Layer Four-Axis Energy Attribution Framework*  
*Platform Reference v2.0*  
*Governing document: `compliance/MASTER_SPEC_ENERGY_CATALOGUE.md`*
