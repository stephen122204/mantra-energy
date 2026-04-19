# Derived Metrics Methodology

This document describes the methodology for all metrics computed from
raw measurements in A-LEMS — energy derivations, performance ratios,
sustainability calculations, LLM timing, and orchestration complexity.

---

## Dynamic Energy Calculation

### Overview

Dynamic energy isolates the energy attributable to the workload by
subtracting the idle baseline from total package energy.

### Formula

$$E_{dyn} = \max(0, E_{pkg} - E_{idle})$$

Where:
- $E_{pkg}$ = Raw package energy from RAPL (µJ)
- $E_{idle}$ = Idle baseline energy for the same duration (µJ)
- $\max(0, \cdot)$ = Ensures non-negative result

### Baseline Method

A-LEMS uses the **2nd percentile minimum baseline** (not mean) to
account for natural variance in idle power consumption:

$$E_{idle} = P_{baseline} \times t_{duration}$$

Where $P_{baseline} = \max(0, \bar{P} - 2\sigma)$ from 30-second idle
measurement with CPU pinned to dedicated cores.

### Derived Metrics

| Metric | Formula | Description |
|--------|---------|-------------|
| `dynamic_energy_uj` | $\max(0, E_{pkg} - E_{idle})$ | Workload energy µJ |
| `total_energy_uj` | $E_{pkg}$ | Total package energy µJ |
| `baseline_energy_uj` | $E_{idle}$ | Idle baseline energy µJ |
| `avg_power_watts` | $E_{dyn} / t \times 10^{-6}$ | Average dynamic power W |

### Provenance

- **Provenance**: `CALCULATED`
- **Method ID**: `dynamic_energy_calculation`
- **Confidence**: `1.0`

---

## IPC Calculation

### Overview

Instructions Per Cycle (IPC) measures CPU execution efficiency — how many
instructions the processor retires per clock cycle on average.

### Formula

$$IPC = \frac{N_{instructions}}{N_{cycles}}$$

Where both values come from hardware performance counters
(see Performance Counter Methodology).

### Interpretation

| IPC Range | Interpretation |
|-----------|---------------|
| < 1.0 | Memory-bound workload, cache misses limiting execution |
| 1.0 – 2.0 | Balanced workload |
| > 2.0 | Compute-bound, efficient execution |

### Provenance

- **Provenance**: `CALCULATED`
- **Method ID**: `ipc_calculation`
- **Confidence**: `1.0`

---

## Cache Miss Rate Calculation

### Overview

Last Level Cache (LLC) miss rate measures the fraction of LLC memory
accesses that result in a cache miss (requiring DRAM access).

### Formula

$$\%_{miss} = \frac{N_{LLC\_miss}}{N_{LLC\_ref}} \times 100$$

### Interpretation

High cache miss rates (>30%) indicate:
- Working set exceeds LLC capacity
- Poor memory access locality
- Potential energy waste from DRAM accesses

### Provenance

- **Provenance**: `CALCULATED`
- **Method ID**: `cache_miss_calculation`
- **Confidence**: `1.0`

---

## Energy Efficiency Metrics

### Overview

A-LEMS computes normalised energy efficiency ratios to enable fair
comparison across workloads of different sizes.

### Formulas

| Metric | Formula | Unit |
|--------|---------|------|
| `energy_per_token` | $E_{pkg} / N_{tokens}$ | µJ/token |
| `energy_per_instruction` | $E_{pkg} / N_{instructions}$ | µJ/instruction |
| `energy_per_cycle` | $E_{pkg} / N_{cycles}$ | µJ/cycle |
| `instructions_per_token` | $N_{instructions} / N_{tokens}$ | inst/token |

### Interpretation

`energy_per_token` is the primary thesis metric — it enables comparison
of energy efficiency across different LLM providers, model sizes, and
inference strategies independent of prompt length.

### Provenance

- **Provenance**: `CALCULATED`
- **Method ID**: `efficiency_metrics_calculation`
- **Confidence**: `1.0`

---

## Orchestration Tax Calculation

### Overview

Orchestration tax quantifies the energy overhead introduced by agentic
workflow coordination compared to direct linear execution.

### Formula

$$\tau = E_{agentic} - E_{linear}$$

$$\tau_{\%} = \frac{E_{agentic} - E_{linear}}{E_{linear}} \times 100$$

$$\tau_{multiplier} = \frac{E_{agentic}}{E_{linear}}$$

### Phase Decomposition

Agentic workflows decompose into three phases:

| Phase | Metric | Formula |
|-------|--------|---------|
| Planning | `planning_time_ms` | Wall clock for plan generation |
| Execution | `execution_time_ms` | Wall clock for tool calls + LLM |
| Synthesis | `synthesis_time_ms` | Wall clock for response synthesis |

Phase ratios:

$$r_{planning} = \frac{t_{planning}}{t_{total}}$$
$$r_{execution} = \frac{t_{execution}}{t_{total}}$$
$$r_{synthesis} = \frac{t_{synthesis}}{t_{total}}$$

### Orchestration CPU

$$t_{orch} = t_{planning} + t_{synthesis}$$

This captures the CPU time spent on agent coordination (not LLM inference).

### Provenance

- **Provenance**: `CALCULATED`
- **Method ID**: `orchestration_tax_calculation`
- **Confidence**: `1.0`

---

## Orchestration Complexity Score

### Overview

A composite metric quantifying the coordination complexity of an agentic
workflow based on three observable factors.

### Formula

$$S = \alpha \cdot \hat{L} + \beta \cdot \hat{T} + \gamma \cdot \hat{N}$$

Where each component is normalised to [0, 1]:

$$\hat{L} = \min\left(\frac{N_{LLM\_calls}}{L_{max}}, 1\right), \quad L_{max} = 10$$
$$\hat{T} = \min\left(\frac{N_{tool\_calls}}{T_{max}}, 1\right), \quad T_{max} = 10$$
$$\hat{N} = \min\left(\frac{N_{tokens}}{N_{max}}, 1\right), \quad N_{max} = 1000$$

### Weights

| Weight | Value | Justification |
|--------|-------|---------------|
| $\alpha$ (LLM calls) | 0.4 | Model invocations dominate energy |
| $\beta$ (Tool calls) | 0.3 | Tool execution adds CPU + I/O cost |
| $\gamma$ (Tokens) | 0.3 | Inference scales with token volume |

**Weight basis**: Heuristic coefficients informed by Schwartz et al. (2020)
and Patterson et al. (2021). These are a novel contribution of A-LEMS —
not directly from literature.

### Complexity Levels

| Score | Level | Description |
|-------|-------|-------------|
| 0 – 0.33 | 1 | Simple: 0-1 tools, direct response |
| 0.33 – 0.67 | 2 | Moderate: 2-3 tools, some planning |
| 0.67 – 1.0 | 3 | Complex: 4+ tools, multi-step |

### Provenance

- **Provenance**: `CALCULATED`
- **Method ID**: `complexity_score_calculation`
- **Confidence**: `0.8` (heuristic weights)

### References

- Schwartz, R. et al. *Green AI*. Communications of the ACM, 2020.
- Patterson, D. et al. *Carbon Emissions and Large Neural Network Training*.
  arXiv:2104.10350, 2021.
- Kaplan, J. et al. *Scaling Laws for Neural Language Models*.
  arXiv:2001.08361, 2020.

---

## Carbon Emission Calculation

### Overview

Carbon emissions are estimated by multiplying energy consumption by
the grid carbon intensity factor for the experiment's geographic location.

### Formula

$$C = E_{pkg} \cdot I_{carbon} \cdot 10^3$$

Where:
- $E_{pkg}$ = Package energy in kWh ($E_{pkg\_uj} \div 3.6 \times 10^9$)
- $I_{carbon}$ = Grid carbon intensity in g CO₂/kWh
- Result in grams CO₂

### Carbon Intensity Source

**Default source**: Ember Global Electricity Review 2026
**Default value**: Country-specific (US ≈ 386 g CO₂/kWh, UK ≈ 148 g CO₂/kWh)

The actual intensity used is stored in `measurement_methodology.parameters_used`
for each run, ensuring reproducibility even as grid intensity changes.

### Why INFERRED

Carbon calculation uses an **external constant** (grid intensity) that:
- Varies by country, region, and time of day
- Is not measured by A-LEMS hardware
- May change between experiments

This makes it `INFERRED` rather than `CALCULATED` — the formula is
deterministic but the inputs include external estimates.

### Provenance

- **Provenance**: `INFERRED`
- **Method ID**: `carbon_calculation`
- **Confidence**: `0.7`

### References

- Ember. *Global Electricity Review 2026*.
  https://ember-climate.org/insights/research/global-electricity-review-2026/

---

## Water Consumption Calculation

### Formula

$$W = E_{pkg} \cdot WUE \cdot 10^3$$

Where $WUE$ = Water Usage Effectiveness in L/kWh.

**Source**: UN-Water 2025 global average data centre WUE.

### Provenance

- **Provenance**: `INFERRED`
- **Method ID**: `water_calculation`
- **Confidence**: `0.7`

---

## Methane Emission Calculation

### Formula

$$CH_4 = E_{pkg} \cdot I_{methane} \cdot 10^3$$

CO₂-equivalent via Global Warming Potential:
- GWP-20: 86 (methane 86× more potent than CO₂ over 20 years)
- GWP-100: 34

**Source**: IEA World Energy Outlook 2026.

### Provenance

- **Provenance**: `INFERRED`
- **Method ID**: `methane_calculation`
- **Confidence**: `0.7`

---

## LLM Timing Measurement

### Overview

LLM API call timing is measured via wall clock at the application layer,
capturing the full round-trip time from request dispatch to response receipt.

### Formula

$$T_{api} = t_{response} - t_{request}$$

Using `time.perf_counter()` for sub-millisecond precision.

### Metrics Captured

| Metric | Description | Provenance |
|--------|-------------|------------|
| `api_latency_ms` | Full API round-trip | MEASURED |
| `total_tokens` | Total tokens in response | MEASURED |
| `prompt_tokens` | Input tokens | MEASURED |
| `completion_tokens` | Output tokens | MEASURED |
| `compute_time_ms` | LLM inference time (no network) | CALCULATED |
| `dns_latency_ms` | DNS resolution overhead | MEASURED |

### TTFT vs TPOT

For streaming responses:
- **TTFT** (Time To First Token): $t_{first\_token} - t_{request}$
- **TPOT** (Time Per Output Token): $t_{total} / N_{tokens}$

### Provenance

- **Provenance**: `MEASURED` (timing) / `CALCULATED` (derived ratios)
- **Method ID**: `ttft_tpot_wall_clock`
- **Confidence**: `1.0`
## CPU Fraction Attribution

**Method ID:** `cpu_fraction_attribution`
**Layer:** OS
**Provenance:** CALCULATED
**Confidence:** 0.95

### Formula

$$E_{attr} = \frac{\Delta ticks_{pid}}{\Delta ticks_{total}} \times E_{dyn}$$

Where:
- $\Delta ticks_{pid}$ = `utime + stime` delta from `/proc/[pid]/stat` (fields 14–15)
- $\Delta ticks_{total}$ = `user + nice + system` delta from `/proc/stat` (fields 1–3)
- $E_{dyn}$ = `dynamic_energy_uj` (pkg energy minus idle baseline)

### Why This Method

Without process isolation, energy attribution includes all background
processes running during the experiment (cron, sshd, systemd timers,
journald, etc.). On a lightly loaded server this background load
typically consumes 5–30% of CPU ticks. CPU fraction attribution
removes this bias deterministically using kernel tick counters.

### Data Sources

| Variable | Source | Fields |
|---|---|---|
| `pid_ticks` | `/proc/[pid]/stat` | utime (col 14) + stime (col 15) |
| `total_ticks` | `/proc/stat` | user + nice + system (cols 1–3) |
| `dynamic_energy_uj` | RAPL pkg delta minus idle baseline | — |

Idle time, iowait, irq, and softirq are **excluded** from the total
denominator. This ensures the fraction reflects active CPU competition,
not wall-clock time.

### Limitations

- Tick resolution is USER_HZ (100 ticks/s on most Linux systems).
  For sub-10ms experiments, quantisation error can be significant.
- Multi-process workloads (spawned subprocesses) are not captured —
  only the top-level PID is tracked.
- On INFERRED mode (ARM VM), `dynamic_energy_uj` is zero, so
  `attributed_energy_uj` will also be zero until Chunk 1.2.

### References

See `config/methodology_refs/cpu_fraction_attribution.yaml`.

## Phase Energy Attribution

**Method ID:** `phase_attribution_cpu_v1`
**Layer:** orchestration
**Provenance:** CALCULATED
**Confidence:** 0.95

### Formula

**Step 1 — Raw phase energy:**
$$E_{raw,i} = \max(0,\ \max(pkg_{end}) - \min(pkg_{start}))$$

**Step 2 — Phase CPU fraction:**
$$f_i = \frac{\max(proc_{ticks,end}) - \min(proc_{ticks,start})}{\max(total_{ticks,end}) - \min(total_{ticks,start})}$$

**Step 3 — Signal score:**
$$S_i = f_i \times E_{raw,i}$$

**Step 4 — Normalized allocation:**
$$w_i = \frac{S_i}{\sum_j S_j}, \qquad E_{phase,i} = w_i \times E_{attributed}$$

**Guarantee:** $\sum_i E_{phase,i} = E_{attributed}$

### Why Normalization

Direct attribution (`cpu_fraction x raw_energy`) does not sum to run total
because raw phase energy and attributed energy use different baselines.
Normalization uses phase scores as relative weights only — the absolute
value comes from the already-correct run-level `attributed_energy_uj`.

### Data Sources

| Variable | Table | Column |
|---|---|---|
| `pkg_start_uj`, `pkg_end_uj` | `energy_samples` | RAPL cumulative counters |
| `proc_ticks_start/end` | `interrupt_samples` | `/proc/[pid]/stat` utime+stime |
| `total_ticks_start/end` | `interrupt_samples` | `/proc/stat` sum(all fields) |
| Phase window | `orchestration_events` | `start_time_ns`, `end_time_ns` |
| Run total | `runs` | `attributed_energy_uj` |

### Fallback

When phase-level proc ticks unavailable, `attribution_method = fallback_run_level`
and `cpu_fraction_per_phase = runs.cpu_fraction`. Normalization still applies.

### Known Limitations

- `synthesis_energy = 0` for local provider runs (synthesis < 2ms, no samples)
- Old runs (pre-Chunk 5) have `phase_sum = 0` — no proc_ticks captured
- Only top-level PID tracked — spawned subprocesses excluded

### References

See `config/methodology_refs/phase_attribution.yaml`.
## Hardware Telemetry Metrics (Chunk 12)

### L1d / L2 / L3 Cache Counters

**Method ID:** `perf_cache_counters`
**Layer:** silicon
**Provenance:** MEASURED
**Confidence:** 1.0

Cache miss counters read via Linux `perf stat` using hardware PMU events.
Collected once per run (not per sample) and distributed evenly across `cpu_samples`.

| Metric | perf Event | Availability |
|--------|-----------|--------------|
| `l1d_cache_misses` | `L1-dcache-load-misses` | Intel (model-specific) |
| `l2_cache_misses` | `l2_rqsts.miss` | Intel ✅ |
| `l3_cache_hits` | `cache-references` (LLC) | Intel ✅ |
| `l3_cache_misses` | `cache-misses` (LLC) | Intel ✅ |

**Note:** `l1d_cache_misses = 0` on ThinkPad Intel — PMU event not exposed on this CPU model. Correct graceful degradation behavior.

**Run-level aggregates** (in `runs` table):
- `l1d_cache_misses_total` = SUM from cpu_samples
- `l2_cache_misses_total` = SUM from cpu_samples
- `l3_cache_hits_total` = SUM from cpu_samples
- `l3_cache_misses_total` = SUM from cpu_samples

**References:** See `config/methodology_refs/perf_cache_counters.yaml`

---

### Disk I/O Metrics

**Method ID:** `disk_io_stats`
**Layer:** os
**Provenance:** MEASURED
**Confidence:** 1.0

**Formula:**
$$\Delta bytes_{read} = (\text{read\_sectors}_{end} - \text{read\_sectors}_{start}) \times 512$$

Source: `/proc/diskstats` — delta between consecutive snapshots at 10Hz.
Device auto-detected: prefers `nvme*`, `sd*`, `vd*` — skips `loop*`, `zram*`, `ram*`.

**Note:** `disk_read_bytes = 0` is expected when Linux page cache absorbs I/O.
Force real disk activity: `sudo sh -c "echo 3 > /proc/sys/vm/drop_caches"`

**Run-level aggregates:**
- `disk_read_bytes_total` = SUM from io_samples
- `disk_write_bytes_total` = SUM from io_samples

**References:** See `config/methodology_refs/disk_io_stats.yaml`

---

### Voltage & Fan Sensors

**Method ID:** `sensors_voltage`
**Layer:** silicon
**Provenance:** MEASURED
**Confidence:** 1.0

**Formula:**
$$V_{core} = \frac{\text{in}i\text{\_input}}{1000}\ \text{(V)}$$

Source: `/sys/class/hwmon/hwmon*/in*_input` — millivolt values from hwmon sysfs.
Fan RPM from `/sys/class/hwmon/hwmon*/fan*_input`.

**Platform availability:**
- ThinkPad Intel: `voltage_vcore = NULL` (not exposed via hwmon on laptops)
- Desktop Intel/AMD: `voltage_vcore > 0` (motherboard hwmon exposes Vcore)
- `fan_rpm > 0` on ThinkPad via `thinkpad` hwmon driver ✅

**Run-level aggregate:**
- `voltage_vcore_avg` = AVG from thermal_samples

**References:** See `config/methodology_refs/sensors_voltage.yaml`
