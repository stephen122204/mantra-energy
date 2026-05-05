# Master Specification — A-LEMS Energy Catalogue
# Version: 1.0
# Status: AUTHORITATIVE — all agents read this before touching energy columns
# Covers: schema.py, provenance.py, seed_methodology.py,
#         validate_energy_chain.py, test_exp_integrity.py,
#         25-energy-attribution-guide.md
# Last updated: 2026-05-03

---

## 0. Purpose

This spec governs a synchronized Energy Catalogue spanning five artifacts:

1. `core/database/schema.py`
       — column definitions + dimension tags per column comment
2. `core/utils/provenance.py`
       — COLUMN_PROVENANCE + METHOD_CONFIDENCE entries
3. `scripts/seed_methodology.py`
       — formula + LaTeX + confidence per method_id
4. `scripts/validate_energy_chain.py`
       — live conservation verification (D1–D4 balance checks)
5. `docs-src/mkdocs/source/research/25-energy-attribution-guide.md`
       — master human-readable catalogue with empirical proof

Every energy column MUST appear consistently in ALL five artifacts.
A researcher must find any column via grep, DB query, or doc search
and get the same definition, formula, and measurement type.

This spec also governs related time/rate metrics in `runs` and
`llm_interactions` that feed energy attribution but are not
energy columns themselves (orchestration_cpu_ms, non_local_ms, etc.)

---

## 1. Paper Thesis (Never Forget)

"Orchestration structure — NOT active compute — is the dominant
driver of energy consumption in agentic AI workloads."

Fundamental paper metrics:
  EpG = SUM(E_attributed across ALL attempts) / successful_goals
  OOI = EpG_agentic / EpG_linear

Every column in this catalogue must ultimately serve these metrics
or explain the physics behind them.

---

## 2. Known Bugs To Fix (Pre-Catalogue Work)

### BUG-C1: validate_energy_chain.py header equations WRONG

Current header:
  D1: E_attributed = E_llm_compute + E_llm_wait + E_orchestration  ← WRONG
  D2: E_orchestration = E_plan + E_exec + E_synth + E_inter_phase  ← WRONG

Correct:
  D1: E_attributed = E_llm_window + E_orchestration
  D2: E_attributed = E_planning + E_execution + E_synthesis + E_inter_phase

Fix: surgical patch to header comment block only.
Do NOT change any computation logic — only the documentation strings.

### BUG-C2: D1 print label WRONG

Line 190:
  "E_process = E_llm_prefill + E_llm_token_wait + E_framework_overhead"

Correct:
  "E_attributed = E_llm_window + E_orchestration"

Fix: surgical patch to print statement only.

### BUG-C3: attributed_energy_uj source inconsistency

v_attribution_summary pulls attributed_energy_uj from runs table.
energy_attribution ETL pulls it from runs.attributed_energy_uj.
These must stay in sync — document the authoritative source clearly.
Authoritative: runs.attributed_energy_uj (written at run time).
energy_attribution uses it as input — never writes its own copy.

### BUG-C4: llm_wait_energy_uj placement ambiguous

Currently shown as separate column in views alongside
llm_compute_energy_uj and orchestration_energy_uj.
This implies THREE-term D1 which is WRONG.
llm_wait_energy_uj is a DIAGNOSTIC SUBSET of E_orchestration.
Must be clearly labeled in all views and docs.
Do NOT add to conservation equations.

### BUG-C5: check_energy_conservation checks wrong invariant

Currently checks: attributed_energy_uj ≈ SUM(goal_attempt.energy_uj)
This is a goal-level rollup check — useful but NOT a D1/D2/D3/D4 check.
Must add explicit D1, D2, D3b, D4 balance checks to test_exp_integrity.py.

---

## 3. Locked Conservation Equations

### D4 — Hardware Domain Partition
```
E_pkg = E_core + E_uncore + E_dram
```
- Source: RAPL hardware counters (MSR reads)
- Measurement type: MEASURED
- Delta tolerance: < 1% of E_pkg (RAPL rounding acceptable)
- Columns (energy_attribution):
    pkg_energy_uj     — total processor package energy
    core_energy_uj    — CPU core energy (RAPL PP0 domain)
    uncore_energy_uj  — uncore energy (LLC, integrated GPU)
    dram_energy_uj    — DRAM energy (RAPL PP1/DRAM domain)
- Same columns also in: runs table (denormalized for query speed)
- Validation query:
    SELECT ABS(pkg_energy_uj - core_energy_uj
               - uncore_energy_uj - dram_energy_uj) AS d4_delta
    FROM energy_attribution WHERE pkg_energy_uj > 0;

### D3a — Idle Subtraction
```
E_dynamic = E_pkg - E_baseline
```
- Measurement type: DERIVED
- E_baseline = idle_power_watts × duration_s (from idle_baselines table)
- Columns (runs table):
    dynamic_energy_uj   — workload-caused energy above idle
    baseline_energy_uj  — system idle energy over same duration
- NOTE: dynamic_energy_uj lives in runs, NOT energy_attribution
- Validation query:
    SELECT ABS(dynamic_energy_uj - (pkg_energy_uj - baseline_energy_uj))
    FROM runs JOIN energy_attribution USING (run_id)
    WHERE pkg_energy_uj > 0;

### D3b — Process Attribution
```
E_dynamic = E_attributed + E_background

E_attributed = cpu_fraction × E_dynamic
E_background = E_dynamic - E_attributed
```

Plain English:
  E_attributed — "Energy attributed to the workload process via
    CPU tick fraction measured over run duration. This is the
    fundamental A-LEMS measurement unit. All paper metrics
    are computed relative to E_attributed."

  cpu_fraction — "Fraction of total system CPU ticks consumed
    by the workload process. Measured via /proc/stat and
    process-level tick counters over run duration."

  E_background — "Remaining dynamic energy not attributed to
    the workload process. Includes uncontrolled system activity
    and A-LEMS instrumentation overhead. These two components
    are NOT separately decomposed in the conservation model.
    E_background is stored for D3b validation only."

- Measurement type: DERIVED
- Authoritative source: runs.attributed_energy_uj (written at run time)
- Columns:
    runs.attributed_energy_uj        — authoritative
    runs.cpu_fraction                — the attribution factor
    energy_attribution.background_energy_uj — ETL populated
- Validation query:
    SELECT ABS(r.dynamic_energy_uj
               - r.attributed_energy_uj
               - ea.background_energy_uj) AS d3b_delta
    FROM runs r JOIN energy_attribution ea USING (run_id)
    WHERE r.dynamic_energy_uj > 0;

### D1 — Activity Partition (PRIMARY THESIS PROOF)
```
E_attributed = E_llm_window + E_orchestration

E_llm_window   ≡ llm_compute_energy_uj   (semantic rename, column unchanged)
E_orchestration ≡ orchestration_energy_uj
```

Plain English:
  E_llm_window — "Energy during LLM inference windows, defined
    by timestamps [request_start_ns → last_token_time_ns].
    Compute-dominated for local models (prefill + decode).
    For remote providers, LLM inference occurs off-device —
    client-side energy in this window is near-zero but not
    exactly zero (streaming, HTTP keep-alive).
    Column: llm_compute_energy_uj
    (name retained for backward compatibility — semantics are
     inference-window energy, not pure compute energy)"

  E_orchestration — "All non-LLM-inference workload energy.
    TIME-ANCHORED: everything outside LLM inference windows.
    Includes BOTH productive computation (tool execution) AND
    coordination overhead (dispatch, wait, retry, planning).
    For remote providers, all client-side energy during LLM
    interaction (wait + streaming) is intentionally attributed
    to E_orchestration — no energy is missing, this is
    explicit policy.
    Column: orchestration_energy_uj
    Computed as residual: E_attributed - E_llm_window"

PARTITION INVARIANT:
  E_llm_window ∩ E_orchestration = ∅       (mutually exclusive)
  E_llm_window ∪ E_orchestration = E_attributed  (exhaustive)

CONSERVATIVE LOWER BOUND NOTE (important for paper):
  Orchestration activity WITHIN LLM inference windows
  (stream handling, token callbacks, partial JSON parsing)
  is conservatively attributed to E_llm_window.
  E_orchestration therefore represents a lower bound on
  total orchestration energy cost. The thesis holds even
  under this conservative attribution.

- Measurement type: E_llm_window = MEASURED (RAPL window slice)
                    E_orchestration = DERIVED (residual)
- D1 guaranteed to balance by ETL construction
- Columns (energy_attribution):
    llm_compute_energy_uj   → E_llm_window
    orchestration_energy_uj → E_orchestration
- Validation query:
    SELECT ABS(r.attributed_energy_uj
               - ea.llm_compute_energy_uj
               - ea.orchestration_energy_uj) AS d1_delta
    FROM runs r JOIN energy_attribution ea USING (run_id)
    WHERE r.attributed_energy_uj > 0;

### D1r — LLM Window Sub-Partition (CONDITIONAL)
```
E_llm_window = E_prefill_window + E_decode_window

IFF (request_start_ns IS NOT NULL AND first_token_time_ns IS NOT NULL)
```

Plain English:
  E_prefill_window — "Energy during prompt encoding window
    [request_start_ns → first_token_time_ns].
    Local: high CPU burst as model processes prompt tokens.
    Remote: near-zero compute, mostly HTTP overhead."

  E_decode_window — "Energy during token generation window
    [first_token_time_ns → last_token_time_ns].
    Local: sustained CPU for autoregressive decode.
    Remote: near-zero compute, mostly streaming receive."

  "Sub-window decomposition is performed only when timestamp
   boundaries are available. When NULL, aggregate window energy
   is reported without further partitioning. This is NOT a
   limitation — it reflects honest measurement boundaries."

- Measurement type: MEASURED (RAPL slice by timestamps)
- Columns:
    prefill_energy_uj  (energy_attribution + llm_interactions)
    decode_energy_uj   (energy_attribution)
- Condition: tinyllama linear has NULL first_token_time_ns
             (no streaming tokens) — D1r not applied, D1 still valid

### D2 — Workflow Phase Partition
```
E_attributed = E_planning + E_execution + E_synthesis + E_inter_phase

E_inter_phase = E_attributed - (E_planning + E_execution + E_synthesis)
```

Plain English:
  E_planning   — "Energy during planning phase orchestration events.
    Includes LLM calls for planning AND orchestration between them."
  E_execution  — "Energy during execution phase events.
    Includes tool calls, LLM calls, and coordination."
  E_synthesis  — "Energy during synthesis/response generation phase."
  E_inter_phase — "Honest residual. Energy in transitions between
    phases not captured by orchestration_events timestamps.
    Non-zero indicates gap in phase coverage — not a bug,
    documented measurement boundary."

CRITICAL ARCHITECTURE:
  D1 and D2 are ORTHOGONAL views over the same E_attributed.
  Each D2 phase contains BOTH E_llm_window AND E_orchestration.
  D2 does NOT decompose E_orchestration — it is a parallel cut.
  D1 answers WHAT type of work consumed energy.
  D2 answers WHERE in the workflow lifecycle energy was spent.

  SUM(D1) = E_attributed  ✓ guaranteed by construction
  SUM(D2) = E_attributed  ✓ guaranteed by inter_phase residual

- Measurement type: MEASURED (RAPL slice by orchestration_events)
- Fallback: runs.planning_energy_uj when events table empty
- Columns (energy_attribution):
    planning_energy_uj
    execution_energy_uj
    synthesis_energy_uj
    inter_phase_energy_uj
- Validation query:
    SELECT ABS(r.attributed_energy_uj
               - ea.planning_energy_uj
               - ea.execution_energy_uj
               - ea.synthesis_energy_uj
               - ea.inter_phase_energy_uj) AS d2_delta
    FROM runs r JOIN energy_attribution ea USING (run_id)
    WHERE r.attributed_energy_uj > 0;

---

## 4. Full Column Catalogue

Format per column:
  Column name | Table | Dimension | Measurement type | Plain English | Formula

### TIER 1A — Core Conservation (D3, D4)
These form mutually exclusive partitions. Must balance.

pkg_energy_uj
  Table:   energy_attribution, runs
  Dim:     D4
  Type:    MEASURED
  English: Total processor package energy from RAPL.
           Ground truth hardware measurement. All other
           energy columns are derived from this.
  Formula: RAPL MSR 0x611 delta over run duration

core_energy_uj
  Table:   energy_attribution, runs
  Dim:     D4
  Type:    MEASURED
  English: CPU core energy from RAPL PP0 domain.
           Represents active compute in CPU cores only.
           Does not include memory controller or uncore.
  Formula: RAPL MSR 0x639 delta

uncore_energy_uj
  Table:   energy_attribution, runs
  Dim:     D4
  Type:    MEASURED
  English: Uncore energy — last-level cache, memory controller,
           integrated GPU. Non-trivial during memory-bound
           workloads and remote API wait periods.
  Formula: E_pkg - E_core - E_dram (on some platforms direct MSR)

dram_energy_uj
  Table:   energy_attribution, runs
  Dim:     D4
  Type:    MEASURED
  English: DRAM energy from RAPL PP1/DRAM domain.
           Critical for LLM workloads — large context windows
           cause sustained DRAM pressure. Non-zero during
           remote wait periods — key physics insight.
  Formula: RAPL MSR 0x61C delta

baseline_energy_uj
  Table:   runs
  Dim:     D3a
  Type:    MEASURED (pre-run idle period)
  English: System idle energy over equivalent duration.
           Measured from idle_baselines table matched by
           hardware profile. Subtracted to isolate workload.
  Formula: idle_power_watts × task_duration_s × 1e6

dynamic_energy_uj
  Table:   runs
  Dim:     D3a, D3b
  Type:    DERIVED
  English: Energy above idle baseline — caused by workload
           and all concurrent system activity.
  Formula: E_pkg - E_baseline

attributed_energy_uj
  Table:   runs  ← AUTHORITATIVE SOURCE
  Dim:     D3b, D1, D2
  Type:    DERIVED
  English: Energy attributed to the workload process via
           CPU tick fraction. The fundamental A-LEMS unit.
           All paper metrics computed relative to this.
           Represents workload's fair share of dynamic energy.
  Formula: cpu_fraction × dynamic_energy_uj
  WARNING: Lives in runs table. energy_attribution uses it
           as input. Never duplicated in energy_attribution.

cpu_fraction
  Table:   runs
  Dim:     D3b (attribution factor)
  Type:    MEASURED
  English: Fraction of total system CPU ticks consumed by
           the workload process over run duration.
           Used to isolate workload energy from background.
  Formula: workload_cpu_ticks / total_cpu_ticks

background_energy_uj
  Table:   energy_attribution
  Dim:     D3b
  Type:    DERIVED
  English: Dynamic energy NOT attributed to workload process.
           Includes uncontrolled system activity AND A-LEMS
           instrumentation overhead. Not separately decomposed.
           Stored for D3b conservation validation only.
  Formula: dynamic_energy_uj - attributed_energy_uj

### TIER 1B — D1 Activity Partition
```
E_attributed = E_llm_window + E_orchestration
```

llm_compute_energy_uj
  Table:   energy_attribution
  Dim:     D1
  Type:    MEASURED (RAPL window slice)
  English: Energy during LLM inference windows.
           Semantic name: E_llm_window.
           Column name retained for backward compatibility.
           Local models: compute-dominated (prefill + decode).
           Remote providers: near-zero on client machine.
           Window defined by [request_start_ns → last_token_time_ns].
  Formula: SUM(RAPL delta for each LLM call window)

orchestration_energy_uj
  Table:   energy_attribution
  Dim:     D1
  Type:    DERIVED (residual)
  English: All non-LLM-inference workload energy.
           Everything outside LLM inference windows.
           Includes tool execution (productive), retry handling
           (wasted), dispatch overhead, and for remote providers,
           all client-side wait + streaming energy.
           This is the dominant term in agentic workloads.
           THE PAPER'S PRIMARY FINDING.
  Formula: attributed_energy_uj - llm_compute_energy_uj

### TIER 1C — D1r LLM Window Sub-Components (CONDITIONAL)
Only populated when timestamps available. Not conservation-critical.

prefill_energy_uj
  Table:   energy_attribution, llm_interactions
  Dim:     D1r
  Type:    MEASURED (RAPL slice)
  English: Energy during prompt encoding window.
           [request_start_ns → first_token_time_ns].
           Local: high CPU burst processing prompt tokens.
           Remote: near-zero, mostly HTTP overhead.
           NULL when request_start_ns or first_token_time_ns missing.
  Formula: RAPL delta over [request_start_ns, first_token_time_ns]

decode_energy_uj
  Table:   energy_attribution
  Dim:     D1r
  Type:    MEASURED (RAPL slice)
  English: Energy during token generation window.
           [first_token_time_ns → last_token_time_ns].
           Local: sustained CPU for autoregressive decode.
           Remote: near-zero, mostly streaming receive overhead.
           NULL when first_token_time_ns missing.
  Formula: RAPL delta over [first_token_time_ns, last_token_time_ns]

### TIER 1D — D2 Phase Partition
```
E_attributed = E_planning + E_execution + E_synthesis + E_inter_phase
```
Each phase contains BOTH E_llm_window AND E_orchestration.
D2 is parallel to D1 — same E_attributed, different cut.

planning_energy_uj
  Table:   energy_attribution, runs
  Dim:     D2
  Type:    MEASURED (RAPL slice by orchestration_events)
  English: Energy during planning phase events.
           Includes LLM calls for planning AND orchestration
           between them. Only meaningful for agentic workflows.
           Zero or minimal for linear runs.
  Formula: SUM(orchestration_events.attributed_energy_uj
               WHERE phase='planning')

execution_energy_uj
  Table:   energy_attribution, runs
  Dim:     D2
  Type:    MEASURED
  English: Energy during execution phase events.
           Includes tool calls, LLM calls, coordination.
  Formula: SUM(orchestration_events.attributed_energy_uj
               WHERE phase='execution')

synthesis_energy_uj
  Table:   energy_attribution, runs
  Dim:     D2
  Type:    MEASURED
  English: Energy during synthesis/response assembly phase.
  Formula: SUM(orchestration_events.attributed_energy_uj
               WHERE phase='synthesis')

inter_phase_energy_uj
  Table:   energy_attribution, runs
  Dim:     D2
  Type:    DERIVED (honest residual)
  English: Energy in transitions between phases not captured
           by orchestration_events timestamps. Non-zero values
           indicate gap in phase event coverage — documented
           measurement boundary, not a bug.
  Formula: attributed_energy_uj
           - planning_energy_uj
           - execution_energy_uj
           - synthesis_energy_uj

### TIER 2 — Orchestration Sub-Components
OVERLAPPING — NOT additive — NOT conservation partitions.
These are named subsets of E_orchestration for diagnostic use.

tool_energy_uj
  Table:   energy_attribution
  Dim:     D1 subset (inside E_orchestration)
  Type:    INFERRED (time-fraction proxy)
  English: Energy attributable to tool execution windows.
           Productive computation — tools do useful work.
           Not waste. Subset of E_orchestration.
           INFERRED because tool windows < 1 RAPL sample interval
           for fast tools (<10ms).
  Formula: (tool_cpu_time_ns / run_duration_ns) × attributed_uj
           OR RAPL slice if window > sample interval

retry_energy_uj
  Table:   energy_attribution
  Dim:     D1 subset (inside E_orchestration)
  Type:    DERIVED
  English: Energy of failed retry attempts — wasted energy.
           Subset of E_orchestration. Overlaps with
           failed_tool_energy_uj for tool-caused retries.
           Key waste signal for paper.
  Formula: SUM(attributed_energy_uj for failed attempt runs)

failed_tool_energy_uj
  Table:   energy_attribution
  Dim:     D1 subset, subset of retry_energy_uj
  Type:    DERIVED
  English: Energy of tool calls that failed — subset of retry.
           Failed_tool ⊆ retry — do NOT sum both.
  Formula: SUM(tool_failure_events.wasted_energy_uj)

rejected_generation_energy_uj
  Table:   energy_attribution
  Dim:     D1 subset (inside E_orchestration)
  Type:    DERIVED
  English: Energy of hallucinated or rejected LLM outputs.
           May overlap with retry_energy_uj if rejection
           triggered a retry.
  Formula: SUM(hallucination_events.wasted_energy_uj)

### TIER 3 — Resource Signals (D3h)
NOT conservation equations. NOT additive. NOT partitions.
Overlapping observational signals derived from system counters.
Used for physics explanation and optimization targeting only.
MUST NOT be summed. MUST NOT appear in conservation checks.

network_wait_energy_uj
  Table:   energy_attribution
  Dim:     D3h signal
  Type:    ESTIMATED (time-fraction proxy)
  English: Energy correlated with network IO blocking periods.
           Derived from llm_interactions.non_local_ms.
           Explains why E_orchestration is non-zero at low CPU:
           DRAM and uncore stay active during network wait.
           Key physics insight for remote provider runs.
  Formula: (non_local_ms / duration_ms) × attributed_uj

io_wait_energy_uj
  Table:   energy_attribution
  Dim:     D3h signal
  Type:    ESTIMATED
  English: Energy correlated with disk IO wait periods.
           From io_samples.io_block_time_ms.
           Identifies DB write overhead as optimization target.
  Formula: (io_block_time_ms / duration_ms) × attributed_uj

disk_energy_uj
  Table:   energy_attribution
  Dim:     D3h signal
  Type:    ESTIMATED
  English: Energy correlated with storage operations.
           Proxy from disk read/write bytes.
  Formula: (disk_bytes / duration_ms) × attribution_constant

memory_pressure_energy_uj
  Table:   energy_attribution
  Dim:     D3h signal
  Type:    ESTIMATED
  English: Energy correlated with DRAM pressure from
           page faults and memory allocation patterns.
  Formula: page_faults × 10µJ constant (calibrated)

cache_dram_energy_uj
  Table:   energy_attribution
  Dim:     D3h signal
  Type:    ESTIMATED
  English: DRAM energy attributable to L3 cache misses.
           Large LLM context windows cause cache thrashing.
           Key signal for memory-bound inference energy.
  Formula: dram_energy_uj × (l3_misses / total_cache_accesses)

interrupt_energy_uj
  Table:   energy_attribution
  Dim:     D3h signal
  Type:    ESTIMATED
  English: Energy correlated with interrupt handling overhead.
           High during streaming token receipt from remote APIs.
  Formula: interrupt_rate × duration_s × energy_per_interrupt

scheduler_energy_uj
  Table:   energy_attribution
  Dim:     D3h signal
  Type:    ESTIMATED
  English: Energy correlated with context switching overhead.
           From context_switches × cost_per_switch constant.
  Formula: total_context_switches × scheduler_energy_constant

### TIER 4 — Diagnostic (Outside Conservation Tree)

llm_wait_energy_uj
  Table:   energy_attribution
  Dim:     DIAGNOSTIC (named subset of E_orchestration)
  Type:    ESTIMATED
  English: Energy during LLM interaction windows dominated
           by wait rather than compute. Primarily remote
           provider runs where client blocks on API response.
           This IS part of E_orchestration — not a separate
           partition. Stored for diagnostic and insight use.
           KEY INSIGHT: non-zero even at CPU≈0 because DRAM
           and uncore remain active during blocking wait.
           Do NOT sum with orchestration_energy_uj — already included.
  Formula: (non_local_ms / duration_ms) × attributed_uj

framework_overhead_energy_uj
  Table:   runs
  Dim:     DIAGNOSTIC (subset of E_background)
  Type:    MEASURED (pre+post task RAPL delta)
  English: A-LEMS instrumentation energy — cost of measurement
           itself. Pre-task and post-task RAPL windows.
           Lives in E_background — NOT in E_attributed.
           NOT a workload cost. DIAGNOSTIC ONLY.
  Formula: pre_task_energy_uj + post_task_energy_uj

thermal_penalty_energy_uj
  Table:   energy_attribution
  Dim:     DIAGNOSTIC
  Type:    ESTIMATED
  English: Energy attributable to thermal throttling events.
           When thermal_throttle_flag=1, actual performance
           drops but energy continues — wasted energy signal.
  Formula: throttle_duration_ms × avg_power_watts × 1e3

unattributed_energy_uj
  Table:   energy_attribution
  Dim:     DIAGNOSTIC (measurement residual)
  Type:    DERIVED
  English: E_pkg minus sum of all explicitly attributed layers.
           Ideally zero. Non-zero indicates decomposition gap.
           Alias in docs: E_measurement_residual.
           Reviewers will ask — we answer: attribution coverage
           tracked via attribution_coverage_pct.
  Formula: max(0, pkg_energy_uj - (baseline + background
                + llm_compute + orchestration
                + thermal_penalty))

### TIER 5 — Normalized Metrics (per-unit rates)

energy_per_completion_token_uj
  Table:   energy_attribution
  Type:    DERIVED
  English: Energy cost per output token generated.
           Normalizes across runs with different output lengths.
  Formula: attributed_energy_uj / completion_tokens

energy_per_successful_step_uj
  Table:   energy_attribution
  Type:    DERIVED
  English: Energy per successfully completed workflow step.
  Formula: attributed_energy_uj / successful_steps

energy_per_accepted_answer_uj
  Table:   energy_attribution
  Type:    DERIVED
  English: Energy per non-hallucinated accepted answer.
           Requires output_quality table to be populated.
  Formula: attributed_energy_uj / accepted_answers

energy_per_solved_task_uj  ≡  EpG
  Table:   energy_attribution
  Type:    DERIVED
  English: Energy per Successful Goal — the paper's
           fundamental unit. Aggregates total workflow energy
           across ALL attempts (including failures) normalized
           by successfully completed goals.
  Formula: SUM(attributed_energy_uj all attempts) / successful_goals

### TIER 6 — Energy-Adjacent Time/Rate Metrics

These are NOT energy columns but FEED energy attribution.
Must be defined in the catalogue — they explain the physics.

orchestration_cpu_ms  [runs table]
  English: CPU milliseconds consumed by orchestration logic
           outside LLM call windows. Time analog of E_orchestration.
           Used to compute OOI time-domain version.
  Formula: SUM(cpu_time_ms for between-LLM-call intervals)
  View:    v_orchestration_overhead.ooi_time

non_local_ms  [llm_interactions table]
  English: Milliseconds spent waiting for remote LLM response.
           Network round-trip time — client blocked, CPU≈0,
           but RAPL shows non-zero pkg draw (key insight).
           Feeds network_wait_energy_uj estimation.
  Formula: MEASURED (wall clock during non-local API call)

local_compute_ms  [llm_interactions table]
  English: Milliseconds of local model computation.
           Only non-zero for local providers (llama_cpp, ollama).
           Feeds llm_compute_energy_uj window slicing.
  Formula: MEASURED (wall clock during local inference)

api_latency_ms  [llm_interactions, runs]
  English: Total API call latency including network + compute.
           For remote: dominated by non_local_ms.
           For local: dominated by local_compute_ms.
  Formula: MEASURED (wall clock from request send to response)

ttft_ms  [llm_interactions, runs]
  English: Time to First Token — latency from request to
           first generated token. Defines E_prefill_window
           time boundary when request_start_ns available.
  Formula: (first_token_time_ns - request_start_ns) / 1e6

tpot_ms  [llm_interactions]
  English: Time Per Output Token — average decode latency.
           (last_token_time_ns - first_token_time_ns) / tokens
  Formula: decode_duration_ms / (completion_tokens - 1)

request_start_ns  [llm_interactions]
  English: Epoch nanoseconds when LLM call was initiated.
           Enables E_prefill_window measurement.
           Added in migration 038. NULL for pre-038 runs.
  Formula: MEASURED (time.time_ns() before API call)

first_token_time_ns  [llm_interactions]
  English: Epoch nanoseconds of first token arrival.
           Defines prefill/decode window boundary.
  Formula: MEASURED (time.time_ns() on first streaming chunk)

last_token_time_ns  [llm_interactions]
  English: Epoch nanoseconds of last token arrival.
           Defines end of LLM inference window.
  Formula: MEASURED (time.time_ns() on final streaming chunk)

cpu_percent_during_wait  [llm_interactions]
  English: CPU utilization during non_local_ms wait period.
           Key measurement — proves CPU≈0 during remote wait
           while RAPL shows non-zero pkg draw.
           The empirical foundation of the paper's insight.
  Formula: MEASURED (psutil during wait window)

---

## 5. Views Inventory

All views must be consistent with this catalogue.
Column aliases in views must match taxonomy names.

v_attribution_summary
  Purpose: Primary paper view. All energy tiers in one place.
  Issues:  pulls attributed_energy_uj from runs (correct — authoritative)
           llm_wait shown separately — mark DIAGNOSTIC in comments
  Fix needed: add comment clarifying llm_wait is subset of orchestration

v_energy_normalized
  Purpose: Per-token and per-second normalized metrics.
  Issues:  llm_wait shown as separate line item alongside orchestration
           Fix: add comment — diagnostic subset, not separate partition

v_fraction_verification
  Purpose: Verifies stored orchestration_fraction matches recomputed.
  Status:  correct — no changes needed

v_orchestration_overhead
  Purpose: OOI computation view.
  Issues:  ooi_time uses orchestration_cpu_ms / task_duration —
           this is TIME-domain OOI, not ENERGY-domain OOI.
           Must be clearly labeled in docs.

v_goal_energy_decomposition
  Purpose: Per-goal energy breakdown. Primary paper query view.
  Status:  check conservation — does it use attributed correctly?

v_failure_energy_taxonomy
  Purpose: Wasted energy from failures.
  Status:  review for overlap between hallucination + tool failure

energy_samples_with_power
  Purpose: Instantaneous power from RAPL sample deltas.
  Status:  correct — powers the empirical conservation proofs

---

## 6. Scripts To Update

### validate_energy_chain.py — Required Changes

1. Fix header comment (BUG-C1):
   D1: E_attributed = E_llm_window + E_orchestration
   D2: E_attributed = E_planning + E_execution + E_synthesis + E_inter_phase

2. Fix D1 print label (BUG-C2):
   "E_attributed = E_llm_window + E_orchestration"

3. Add explicit D4 balance check:
   PASS if |E_pkg - E_core - E_uncore - E_dram| < 1% of E_pkg

4. Add explicit D3b balance check:
   PASS if |E_dynamic - E_attributed - E_background| < 1000µJ

5. Add explicit D2 balance check:
   PASS if |E_attributed - SUM(phases)| < 1000µJ

6. Mark D3h signals clearly as NON-CONSERVATION:
   Print header: "[Resource Signals — observational, not additive]"

7. Mark llm_wait as DIAGNOSTIC SUBSET:
   Print: "llm_wait [diagnostic subset of orchestration]"

### test_exp_integrity.py — Required Changes

1. Fix check_energy_conservation (BUG-C5):
   Add D1 check: attributed ≈ llm_compute + orchestration
   Add D4 check: pkg ≈ core + uncore + dram
   Add D3b check: dynamic ≈ attributed + background
   Add D2 check: attributed ≈ planning + execution + synthesis + inter_phase

2. Fix N41: NULL failure_type check (add AND is_retry = 1)

3. Fix N42: complexity_score check (add WHERE workflow_type='agentic')

### schema.py — Required Changes

Add dimension tags to every energy column comment:
  [D4] [D3a] [D3b] [D1] [D1r] [D2] [D3h] [DIAG] [NORM]
Add measurement type to every column comment:
  [MEASURED] [DERIVED] [ESTIMATED] [INFERRED]

---

## 7. Provenance Sync Requirements

Every Tier 1A-1D column needs entry in COLUMN_PROVENANCE.
Currently missing (verify with grep):
  llm_compute_energy_uj
  orchestration_energy_uj
  background_energy_uj
  All Tier 3 D3h signal columns

Method IDs needed in METHOD_CONFIDENCE + seed_methodology.py:
  llm_window_energy_v1      — RAPL slice by LLM timestamps
  orchestration_residual_v1 — attributed - llm_window
  background_energy_v1      — dynamic - attributed
  phase_energy_v2           — RAPL slice by orchestration_events
  resource_signal_v1        — time-fraction proxy methods
  prefill_decode_split_v1   — conditional timestamp split

---

## 8. Document To Write

### 25-energy-attribution-guide.md

Structure:
  1. Abstract — thesis + contribution + catalogue purpose
  2. Taxonomy Diagram — visual hierarchy of all dimensions
  3. Conservation Equations — D1-D4 with LaTeX formulas
  4. Column Catalogue — all tiers, plain English + formula + type
  5. Conservation Proofs — empirical numbers from clean run
     (actual µJ values showing equations balance)
  6. Key Empirical Finding — E_orchestration dominance
     Show: agentic vs linear orchestration_fraction comparison
     Show: cpu_percent_during_wait ≈ 0 but RAPL non-zero (remote)
  7. Provider Comparison — local vs remote energy patterns
  8. D2 Phase Analysis — where in workflow energy accumulates
  9. Resource Signals Guide — how to use D3h, what they explain
  10. Time Metrics Guide — how non_local_ms, ttft_ms feed attribution
  11. Known Limitations — honest, precise
      - D1r NULL for tinyllama linear
      - tool_energy INFERRED for sub-10ms tools
      - cloud energy client-side only
      - D3h signals overlap — not additive
  12. Researcher Validation Queries — SQL per equation
  13. Graph Specifications — queries + chart types for paper figures
  14. Glossary — every term one sentence

---

## 9. Execution Order For Implementing Agent

Step 1: Read this spec fully. Read COMPLIANCE.md. Read NFR_QUICK_REFERENCE.md.
Step 2: Grep every file before touching. Never assume contents.
Step 3: Fix schema.py column comments — add dimension + type tags.
Step 4: Fix COLUMN_PROVENANCE — add missing entries.
Step 5: Fix seed_methodology.py — add missing method_ids.
Step 6: Run: bash scripts/test_provenance.sh — must pass before continuing.
Step 7: Fix validate_energy_chain.py — header + labels + new D4/D3b/D2 checks.
Step 8: Fix test_exp_integrity.py — D1/D2/D3b/D4 checks + N41 + N42.
Step 9: Run empirical validation queries to get real numbers.
Step 10: Write 25-energy-attribution-guide.md with real numbers.
Step 11: Run full compliance chain:
         bash scripts/test_provenance.sh
         python scripts/validate_energy_chain.py --latest
         python scripts/test_exp_integrity.py --latest
Step 12: Fix original bugs: N39 (YAML), N40 (etl_queue), N30 (agentic success).
Step 13: Run paper data collection experiment.
Step 14: Update 25-energy-attribution-guide.md with paper data numbers.

---

## 10. Rules This Agent Must Never Violate

- Never rename columns — SC-5 backward compat
- Never DROP or RENAME existing columns
- Never change phase_attribution_etl v2 algorithm
- Never change f_orch = E_orch/E_attributed denominator
- Never make D1 and D2 nest inside each other
- Never sum D3h signals — they overlap
- Never sum retry + failed_tool — failed_tool ⊆ retry
- Never put llm_wait in conservation equations — it is diagnostic
- Migrations 036, 037, 038 already run — never modify
- _compute_attribution takes (run, cursor, conn) — never change signature
- tool_graph pass-through in all 3 entry points — never remove
- Always grep before writing any patch
- Always FIND/REPLACE — never rewrite whole files
- Always cp to platform path before running
- Always run compliance chain after every change

---

## 11. Key Architecture Facts

- attributed_energy_uj lives in RUNS table (authoritative)
- energy_attribution uses runs.attributed_energy_uj as INPUT
- dynamic_energy_uj lives in RUNS table only
- background_energy_uj lives in energy_attribution only
- D1 balance guaranteed by ETL construction (residual)
- D2 balance guaranteed by inter_phase residual
- D4 balance depends on RAPL hardware — may have small delta
- llm_wait is inside E_orchestration — never separate
- framework_overhead_energy_uj is inside E_background — never in E_attributed
- unattributed_energy_uj = measurement gap — ideally zero
- attribution_coverage_pct tracks how well decomposition covers pkg

---
END OF MASTER SPEC
---

---

## 12. ETL Bugs Discovered — Resource Signal Methods Wrong

### BUG-E1: network_wait_energy_uj uses time-fraction instead of RAPL slice

Current ETL (energy_attribution_etl.py line 664):
  network_wait_uj = (network_wait_ms / duration_ms) × attributed_uj
  TYPE: MODELED (time-fraction proxy)

Should be:
  Slice energy_samples between network wait window timestamps
  from llm_interactions.non_local_ms start/end
  TYPE: MEASURED (direct RAPL slice)

We have 100Hz energy_samples. We have non_local_ms timestamps.
We should do a direct RAPL slice — not a time fraction.
Time fraction assumes energy is uniform over the run — wrong.
During network wait CPU≈0 so pkg draw is LOWER than average.
Time fraction OVERESTIMATES network_wait_energy_uj.

Fix: implement _get_network_wait_energy_from_samples(cursor, run_id)
     using same pattern as _llm_energy_from_samples.py
     Slice energy_samples WHERE timestamp_ns BETWEEN wait_start AND wait_end

### BUG-E2: io_wait_energy_uj uses time-fraction against pkg (wrong base)

Current ETL (line 665):
  io_wait_uj = (io_wait_ms / duration_ms) × pkg   ← uses pkg not attributed!

Two errors:
  1. Should slice RAPL samples for IO wait windows from io_samples table
  2. Using pkg as base instead of attributed — inflates by 1/cpu_fraction

Fix: implement _get_io_wait_energy_from_samples(cursor, run_id)
     Use io_samples.io_block_time_ms timestamps to slice energy_samples

### BUG-E3: memory_pressure_energy_uj uses hardcoded constant

Current ETL (line 670):
  memory_pressure_uj = page_faults × 10µJ

This is a made-up constant — not calibrated to this hardware.
No reference cited. No measurement basis.

Options:
  A. Calibrate constant against known memory pressure benchmarks
  B. Use dram_energy_uj correlated with page_fault_rate
  C. Mark clearly as MODELED with low confidence (0.5)
     and document the 10µJ/fault assumption explicitly

### BUG-E4: interrupt_energy_uj uses hardcoded 0.5µJ/interrupt constant

Current ETL (line 702):
  interrupt_uj = interrupt_rate × 0.5µJ × duration_s

Same issue — uncalibrated constant.
Should be correlated with actual uncore_energy during high-interrupt periods.

### BUG-E5: cache_dram_energy_uj — only valid method of the four

Current ETL:
  cache_dram_uj = dram_energy × (l3_misses / total_accesses)

This IS a valid RAPL-based approach — uses measured dram_energy_uj
and measured cache counters. Correctly MODELED (proportionality).
No fix needed — just correct classification.

---

## 13. Classification Corrections For provenance.py

Based on ETL reality:

| Column                    | Current    | Correct    | Reason                        |
|---------------------------|------------|------------|-------------------------------|
| ea.network_wait_energy_uj | INFERRED   | MODELED    | time-fraction (should be MEASURED after BUG-E1 fix) |
| ea.io_wait_energy_uj      | INFERRED   | MODELED    | time-fraction (should be MEASURED after BUG-E2 fix) |
| ea.memory_pressure_energy_uj | INFERRED | MODELED   | constant × counter            |
| ea.interrupt_energy_uj    | INFERRED   | MODELED    | constant × rate               |
| ea.scheduler_energy_uj    | INFERRED   | MODELED    | constant × switches           |
| ea.cache_dram_energy_uj   | INFERRED   | MODELED    | dram × cache_ratio (correct)  |
| ea.disk_energy_uj         | INFERRED   | MODELED    | bytes proxy                   |
| ea.tool_energy_uj         | INFERRED   | MODELED    | time-fraction proxy           |
| ea.llm_wait_energy_uj     | MEASURED   | MODELED    | time-fraction — NOT a RAPL slice |

After BUG-E1 and BUG-E2 are fixed:
  network_wait_energy_uj → MEASURED
  io_wait_energy_uj      → MEASURED

---

## 14. Priority Order For ETL Fixes

Priority 1 — BUG-E1 (network_wait): 
  Directly affects paper insight (E_wait non-zero during remote blocking).
  Current time-fraction OVERESTIMATES because CPU≈0 during wait.
  RAPL slice will show LOWER but MORE HONEST value.
  Fix before paper data collection.

Priority 2 — BUG-E2 (io_wait):
  Wrong base (pkg vs attributed) is a correctness bug.
  Fix before paper data collection.

Priority 3 — BUG-E3/E4 (constants):
  Document assumptions explicitly.
  Add to Known Limitations in doc.
  Fix calibration in future chunk.

Priority 4 — BUG-E5 (cache_dram):
  Already correct method. Just reclassify.

---

## 15. Provenance.py Patches Required

### Patch 1 — Add MODELED type

FIND:
    INFERRED   — uses external constants, emission factors, or models
    SYSTEM     — infrastructure metadata, no scientific meaning

REPLACE WITH:
    INFERRED   — uses external constants, emission factors, or models
    MODELED    — proportionality model applied to measured values
                 (time-fraction or counter-fraction × total energy)
    SYSTEM     — infrastructure metadata, no scientific meaning

### Patch 2 — Fix 8 INFERRED → MODELED

FIND:
    "ea.interrupt_energy_uj":            ("energy_attribution_v1",      "INFERRED"),
    "ea.scheduler_energy_uj":            ("energy_attribution_v1",      "INFERRED"),
    # L2: Resource contention
    "ea.network_wait_energy_uj":         ("energy_attribution_v1",      "INFERRED"),
    "ea.io_wait_energy_uj":              ("energy_attribution_v1",      "INFERRED"),
    "ea.disk_energy_uj":                 ("energy_attribution_v1",      "INFERRED"),
    "ea.memory_pressure_energy_uj":      ("energy_attribution_v1",      "INFERRED"),
    "ea.cache_dram_energy_uj":           ("energy_attribution_v1",      "INFERRED"),

REPLACE WITH:
    "ea.interrupt_energy_uj":            ("energy_attribution_v1",      "MODELED"),
    "ea.scheduler_energy_uj":            ("energy_attribution_v1",      "MODELED"),
    # L2: Resource contention — MODELED via time/counter-fraction proxy
    # TODO BUG-E1: network_wait should be RAPL slice after fix
    # TODO BUG-E2: io_wait should be RAPL slice after fix
    "ea.network_wait_energy_uj":         ("energy_attribution_v1",      "MODELED"),
    "ea.io_wait_energy_uj":              ("energy_attribution_v1",      "MODELED"),
    "ea.disk_energy_uj":                 ("energy_attribution_v1",      "MODELED"),
    "ea.memory_pressure_energy_uj":      ("energy_attribution_v1",      "MODELED"),
    "ea.cache_dram_energy_uj":           ("energy_attribution_v1",      "MODELED"),

### Patch 3 — Fix tool_energy_uj

FIND:
    "ea.tool_energy_uj":                 ("energy_attribution_v1",      "INFERRED"),

REPLACE WITH:
    "ea.tool_energy_uj":                 ("energy_attribution_v1",      "MODELED"),

### Patch 4 — Fix llm_wait_energy_uj

FIND:
    "ea.llm_wait_energy_uj":             ("llm_energy_sample_v2",       "MEASURED"),

REPLACE WITH:
    "ea.llm_wait_energy_uj":             ("energy_attribution_v1",      "MODELED"),

### Patch 5 — Fix duplicate energy_per entries (verify lines first)
grep -n "energy_per_accepted_answer_uj\|energy_per_solved_task_uj" \
  $BASE/core/utils/provenance.py
Then remove the duplicate block at lines 137-138.

---
