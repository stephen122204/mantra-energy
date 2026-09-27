# Preparing and qualifying the task inventory

This is a software handoff, not a campaign launch plan. It prepares task assets
and checks tools, verifiers and saved records without touching an active node.
It is based on the campaign-operations branch (PR #66). Do not replace a running
node checkout with this branch while measurements are in progress.

## Available tasks

| Behavior | Task definitions | Correctness check |
|---|---:|---|
| Business SQL | 3: segment totals, orphan rows, declining segments | Independent CSV reference, filters/NULLs/threshold traps |
| Versioned-record SQL repair | 1 | Original data plus irregular hidden tables; latest record before filtering |
| Python data transformations | 2: conditional deduplication, user histogram | Independent implementation, unseen data and edge cases |
| Repository repair | 9 NetworkX cases | Original test module, withheld tests and independent checks |
| Numerical tool use | 1 grouped regression | Exact arithmetic reference and finite-value checks |

This is a **16-definition inventory**, not 16 independent domains. Repository
cases share NetworkX, the business tasks share a schema, and changing seed or
size adds an input variant. The numerical tool itself computes the regression.
The optional real-data air-quality task uses the existing prepared-numerical
loader; it needs a verified asset directory and hash and is not silently included.
See `PROGRAM_TASKS.md` for benchmark attribution and adaptation details.

## Local setup

Use Python 3.11 or newer and an isolated environment. Install
`requirements-study.txt` and `requirements-task-screen.txt`. Clone NetworkX into
a separate directory and check out exactly
`2acf1590f82757c01a57b81b8c5dfb79e60aa416` (3.4.2).
Do not install another NetworkX version into the tool environment: the tool runs
against the pinned source snapshot.

Set `ALEMS_NETWORKX_SOURCE` to the absolute checkout path and
`ALEMS_REPO_TOOL_PYTHON` to the absolute environment Python executable. Then run:

```sh
python -m pytest -q tests/test_program_workload.py tests/test_program_pipeline.py tests/test_repo_workload.py tests/test_business_workload.py tests/test_etl_workload.py tests/test_numerical_workload.py tests/test_task_pack.py tests/test_task_pack_cli.py tests/test_task_pack_pipeline.py
```

The nine repository integration checks must **run, not skip**. Missing packages,
collection failures and worker setup failures are infrastructure failures, not
model mistakes. See the CI workflow for Linux/Windows execution of new task tests
and Linux repository qualification. Local macOS checks are not Linux hardware
validation. The repository tool uses Linux address-space limits; local platforms
have different limits, and CPU affinity requests must be supported explicitly.

## Prepare assets without running models

Replace the example paths with local absolute paths. This command creates all
16 task definitions and freezes their hashes; it does not start inference:

```sh
python -m studies.energy_diagnosis.moe.prepare_task_screen \
  --output /absolute/path/task-inventory \
  --networkx-source /absolute/path/networkx \
  --tool-python /absolute/path/venv/bin/python \
  --rows 8192 --seed 7
```

Outputs:

- `specifications.json`: accepted directly by the existing `--task-pack` option.
- `inventory.json`: task IDs, families, lineage, versions, verifier and asset hashes.
- `assets/task-pack.json`: immutable preparation manifest.
- `assets/`: materialized inputs and private verifier assets. Only the per-attempt
  workspace is model-facing; do not give the model the asset/verifier directory.

Repeat `--repo-case NAME` to prepare an explicit subset; omitted means all nine.
Use separate output directories for different seeds, sizes or code revisions.
Do not choose the subset based on which model won. An inventory is a pool, not a
requirement to run every case immediately.

## What counts as ready

1. Known-correct solutions pass; deliberately wrong solutions and edited tests
   fail. A simulated model's pass checks plumbing, not model capability.
2. A saved attempt retains model calls, tool work, verification, outcome, errors,
   configuration and measurement status. Failed attempts remain in exports.
   Missing telemetry remains missing, not zero energy.
3. Restarting a completed fixture does not duplicate it; changed assets or
   specifications are rejected rather than silently reused.
4. Before live collection, qualify each selected task with the actual backend:
   serialization, prompt/tool compatibility, context and token limits, complete
   goal deadline, tool budgets and correctness. Five fixture turns do not justify
   a five-turn live budget. Freeze equal budgets across comparison settings using
   separate calibration inputs, including enough time for the intended tools and
   final verification. Keep calibration attempts separate from evaluation.
5. On the measurement node, check timing and CPU/GPU counters under the actual
   configuration. Local software checks do not certify sensor calibration or
   establish an energy effect. Record all attempts and separate invalid
   instrumentation from wrong answers, truncation and budget failures.

The existing fixture CLI supports the business, ETL, numerical and Python tasks.
Repository qualification uses real pytest subprocesses with known buggy and
repaired source. Repository cases are not supported by the scripted fixture model;
use their integration tests locally and the actual backend for live qualification.
