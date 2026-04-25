# Researcher Guide — Designing and Running Energy Experiments

## Overview

This guide covers everything a researcher needs to design, run, and query
A-LEMS experiments. It assumes the platform is installed and verified.

The platform's unit of analysis is the **goal** — one task executed by one
workflow type in one experiment. Every energy measurement, quality score,
and failure event traces back to a goal.

---

## 1. Paper Thesis and What to Measure

**Thesis:** Orchestration structure — NOT active compute — is the dominant
driver of energy consumption in agentic AI workloads.

To prove this, every experiment must produce:

| Metric | Table | Column |
|---|---|---|
| Energy per goal | goal_execution | total_energy_uj |
| Overhead fraction | goal_execution | overhead_fraction |
| Orchestration fraction | goal_execution | orchestration_fraction |
| Wasted retry energy | goal_execution | overhead_energy_uj |
| Failure taxonomy | tool_failure_events | failure_type, wasted_energy_uj |

---

## 2. Experiment Types

| experiment_type | Purpose | Paper Figure |
|---|---|---|
| normal | Standard baseline run | Figure 1 — energy per goal |
| overhead_study | Measures orchestration_fraction directly | Figure 2 — overhead breakdown |
| retry_study | Forced retries, measures retry_energy_uj | Figure 3 — wasted energy |
| failure_injection | Injected failures, measures recovery cost | Figure 3 — failure taxonomy |
| quality_sweep | Varying difficulty vs quality-adjusted energy | Figure 4 — quality frontier |
| calibration | Idle baseline — excluded from analysis | — |
| ablation | Component removal | Supplementary |
| pilot | Early feasibility | Excluded from main analysis |
| debug | Development only | Always excluded |

**Rule:** Always filter with positive inclusion, never exclusion:
```sql
WHERE experiment_type IN ('normal','overhead_study','retry_study',
                          'failure_injection','quality_sweep','ablation')
```

---

## 3. Experiment Config YAML — Full Reference

Every experiment is defined in a YAML file under `config/experiment_configs/`.

```yaml
# ── Study identity ────────────────────────────────────────────────────────────
study:
  name: "Human-readable name"
  experiment_type: "normal"          # one of the 9 valid types
  experiment_goal: "Research question this run answers"
  experiment_notes: "Any notes about conditions, run order, dependencies"
  workflow_modes: ["linear", "agentic"]  # or just one: ["linear"]

# ── Tasks ─────────────────────────────────────────────────────────────────────
# List of task IDs from config/tasks.yaml
# test_harness.py uses first task only. run_experiment.py loops all tasks.
tasks:
  - id: gsm8k_basic
  - id: factual_qa
  - id: code_fibonacci

# ── Providers ─────────────────────────────────────────────────────────────────
# List of providers from config/models.yaml
# test_harness.py uses first provider only. run_experiment.py loops all.
providers:
  - name: llama_cpp
    model_id: tinyllama-1b-gguf
  - name: groq
    model_id: llama-3.3-70b-versatile

# ── Execution ─────────────────────────────────────────────────────────────────
execution:
  repetitions: 10          # how many times each task runs per provider
  cool_down_seconds: 30    # seconds between repetitions
  save_db: true

# ── Retry policy ──────────────────────────────────────────────────────────────
# Matches a row in retry_policy table by name.
# Four policies: no_retry, default, aggressive, conservative
retry_policy:
  name: "no_retry"
  max_retries: 0
  retry_on_timeout: false
  retry_on_tool_error: false
  retry_on_api_error: false
  retry_on_wrong_answer: false
  backoff_seconds: 0.0

# ── Quality scoring ───────────────────────────────────────────────────────────
quality:
  enabled: false   # set true for quality_sweep experiments

# ── Failure injection ─────────────────────────────────────────────────────────
# Only active when experiment_type is 'failure_injection' or 'retry_study'
failure_injection:
  enabled: false
  tool_failure_rate: 0.3   # 0.0–1.0
  timeout_rate: 0.1        # 0.0–1.0
```

---

## 4. Available Tasks

List all tasks:
```bash
PYTHONPATH=. python -m core.execution.tests.test_harness --list-tasks
```

Tasks are defined in `config/tasks.yaml`. Each task has:
- `id` — unique identifier used in experiment configs
- `level` — difficulty 1 (easy) to 3 (hard)
- `tool_calls` — number of tool calls required (0 = pure inference)
- `prompt` — the actual task text sent to the model

---

## 5. Running Experiments

### Quick verification (single task, single provider):
```bash
PYTHONPATH=. python -m core.execution.tests.test_harness \
    --config config/experiment_configs/baseline_study.yaml \
    --save-db
```

### Production overnight run (all tasks, all providers):
```bash
PYTHONPATH=. python -m core.execution.tests.run_experiment \
    --config config/experiment_configs/baseline_study.yaml \
    --save-db
```

### After every run — always run ETLs:
```bash
python scripts/etl/goal_execution_etl.py --backfill-all
python scripts/etl/energy_attribution_etl.py --backfill-attribution
```

---

## 6. Data Collection Schedule for Paper

### Night 1 — Baseline + Overhead (~4-6 hours each):
```bash
python -m core.execution.tests.run_experiment \
    --config config/experiment_configs/baseline_study.yaml --save-db

python -m core.execution.tests.run_experiment \
    --config config/experiment_configs/overhead_study.yaml --save-db
```
Produces: Paper Figures 1 and 2.

### Night 2 — Retry + Failure Injection (~3-4 hours each):
```bash
python -m core.execution.tests.run_experiment \
    --config config/experiment_configs/retry_study.yaml --save-db

python -m core.execution.tests.run_experiment \
    --config config/experiment_configs/failure_injection_study.yaml --save-db
```
Produces: Paper Figure 3.

### Night 3 — Quality Sweep (~4-5 hours):
```bash
python -m core.execution.tests.run_experiment \
    --config config/experiment_configs/quality_sweep.yaml --save-db
```
Produces: Paper Figure 4.

---

## 7. Schema Map — What Table Covers What

### experiments
One row per experiment run. Research classification lives here.
Key columns: `exp_id`, `experiment_type`, `provider`, `workflow_type`, `experiment_goal`.

### goal_execution
**The paper's unit of analysis.** One row per task per workflow side per experiment.
Key columns: `goal_id`, `workflow_type`, `task_id`, `difficulty_level`, `success`,
`total_energy_uj`, `successful_energy_uj`, `overhead_energy_uj`,
`overhead_fraction`, `orchestration_fraction`.

### goal_attempt
One row per execution attempt. Multiple rows per goal when retries occur.
Key columns: `attempt_id`, `goal_id`, `attempt_number`, `is_retry`,
`retry_of_attempt_id`, `outcome`, `failure_type`, `energy_uj`.

### runs
One row per hardware measurement window. Low-level energy data lives here.
Key columns: `run_id`, `pkg_energy_uj`, `duration_ns`, `workflow_type`.

### energy_attribution
Energy decomposed by layer per run.
Key columns: `run_id`, `orchestration_energy_uj`, `compute_energy_uj`,
`retry_energy_uj`, `failed_tool_energy_uj`, `rejected_generation_energy_uj`.

### tool_failure_events
One row per tool failure within one attempt.
Key columns: `failure_id`, `attempt_id`, `goal_id`, `tool_name`,
`failure_type`, `wasted_energy_uj`.

### output_quality
One row per attempt — LLM answer correctness score.
Key columns: `quality_id`, `attempt_id`, `normalized_score`, `pass_fail`.

### hallucination_events
One row per hallucination detected within one attempt.
Key columns: `hallucination_id`, `attempt_id`, `hallucination_type`,
`severity`, `wasted_energy_uj`.

### retry_policy
Four canonical retry policies. Referenced by experiment configs.
Key columns: `policy_name`, `max_retries`, `retry_on_*`, `backoff_seconds`.

### normalization_factors
Structural factors per run for cross-paper normalisation.
Key columns: `run_id`, `successful_goals`, `attempted_goals`,
`hallucination_count`, `failed_tool_calls`.

---

## 8. Canonical Paper Queries

### Paper core query — overhead fraction by workflow type:
```sql
SELECT
    ge.workflow_type,
    AVG(ge.overhead_fraction)        AS avg_overhead_fraction,
    AVG(ge.orchestration_fraction)   AS avg_orchestration_fraction,
    AVG(ge.successful_energy_uj)/1e6 AS avg_energy_per_goal_j,
    COUNT(*)                         AS goals
FROM goal_execution ge
JOIN experiments e ON ge.exp_id = e.exp_id
WHERE e.experiment_type IN ('normal','overhead_study','retry_study',
                             'failure_injection','quality_sweep','ablation')
GROUP BY ge.workflow_type;
```

### Energy wasted by failure type (Figure 3):
```sql
SELECT * FROM v_failure_energy_taxonomy LIMIT 20;
```

### Quality vs energy frontier (Figure 4):
```sql
SELECT * FROM v_quality_energy_frontier LIMIT 20;
```

### Retry overhead per workflow type:
```sql
SELECT
    ge.workflow_type,
    COUNT(DISTINCT ga.goal_id)          AS total_goals,
    SUM(CASE WHEN ga.is_retry=1 THEN 1 ELSE 0 END) AS retry_attempts,
    AVG(ga.energy_uj)/1e6               AS avg_attempt_energy_j
FROM goal_attempt ga
JOIN goal_execution ge ON ga.goal_id = ge.goal_id
JOIN experiments e ON ge.exp_id = e.exp_id
WHERE e.experiment_type = 'retry_study'
GROUP BY ge.workflow_type;
```

### Failure taxonomy:
```sql
SELECT
    tfe.failure_type,
    ge.workflow_type,
    COUNT(*)                          AS occurrences,
    AVG(tfe.wasted_energy_uj)/1e6     AS avg_wasted_energy_j
FROM tool_failure_events tfe
JOIN goal_attempt ga ON tfe.attempt_id = ga.attempt_id
JOIN goal_execution ge ON ga.goal_id = ge.goal_id
WHERE tfe.wasted_energy_uj IS NOT NULL
GROUP BY tfe.failure_type, ge.workflow_type
ORDER BY avg_wasted_energy_j DESC;
```

### Task difficulty vs overhead:
```sql
SELECT
    ge.difficulty_level,
    ge.workflow_type,
    AVG(ge.overhead_fraction)   AS avg_overhead,
    COUNT(*)                    AS goals
FROM goal_execution ge
JOIN experiments e ON ge.exp_id = e.exp_id
WHERE e.experiment_type IN ('normal','overhead_study')
  AND ge.difficulty_level IS NOT NULL
GROUP BY ge.difficulty_level, ge.workflow_type
ORDER BY ge.difficulty_level;
```

---

## 9. Confound Control

Reviewers will challenge energy differences by arguing:
- Agentic workflows used harder tasks → always set `difficulty_level` in tasks.yaml
- Different model sizes used → always record `provider` and `model_name`
- Different run conditions → always record `experiment_type` and separate runs by type

Stratified analysis commands:
```sql
-- Check task difficulty balance across workflow types
SELECT workflow_type, difficulty_level, COUNT(*) AS goals
FROM goal_execution
GROUP BY workflow_type, difficulty_level;

-- Check provider consistency
SELECT provider, workflow_type, COUNT(*) AS runs
FROM experiments e
JOIN runs r ON e.exp_id = r.exp_id
GROUP BY provider, workflow_type;
```

---

## 10. Data Validation Before Paper Submission

Run all three checks before using data in paper:

```bash
# 1. Provenance — all columns have method attribution
bash scripts/test_provenance.sh   # must pass 34/34

# 2. Schema integrity
sqlite3 data/experiments.db "PRAGMA integrity_check;"   # must be ok
sqlite3 data/experiments.db "PRAGMA foreign_key_check;" # pre-existing only

# 3. ETL completeness — no NULL energy columns on completed goals
sqlite3 data/experiments.db "
SELECT COUNT(*) FROM goal_execution
WHERE success=1 AND total_energy_uj IS NULL;"
# must be 0

# 4. Paper core query returns data
sqlite3 data/experiments.db "
SELECT workflow_type, COUNT(*), AVG(overhead_fraction)
FROM goal_execution ge
JOIN experiments e ON ge.exp_id = e.exp_id
WHERE e.experiment_type IN ('normal','overhead_study')
GROUP BY workflow_type;"
```
