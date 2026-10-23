# Task-Level Energy of Locally Hosted AI Agents

Python software for measuring the energy that AI agents spend to complete
verifiable tasks on locally hosted language models. It runs an agent on coding
and data-analysis tasks, reads CPU-package and GPU-board energy counters every
0.1 s, attributes the energy to model calls, tool calls and waiting, and checks
each attempt with a hidden verifier. The measurement layer builds on the
[A-LEMS](https://github.com/deepakpanigrahy03/a-lems) platform.

The repository supports two papers that share this code:

| Paper | Question | Code | Release branch |
| --- | --- | --- | --- |
| *Measuring the Energy Cost of Completing Tasks with Quantized Language-Model Agents* | Does the precision that is cheaper per token also complete tasks with less energy? | `studies/energy_diagnosis/` | [`paper-1`](../../tree/paper-1) |
| Paper 2 (in preparation) | Which weight precision completes tasks with the least energy when many agents share one GPU? | `studies/paper2/` | [`paper-2`](../../tree/paper-2) |

Each release branch is pinned by tags to the exact commits that ran the
experiments (see [Releases](#releases)).

## Install

Clone the repository:

```bash
git clone https://github.com/stephen122204/alems-energy-diagnosis.git
cd alems-energy-diagnosis
```

Create a Python 3.11 environment and install the study dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-study.txt
```

Optional task dependencies are in `requirements-task-screen.txt` and
`studies/energy_diagnosis/moe/requirements-query.txt`. Measured runs need a
Linux node with an NVIDIA GPU, readable powercap (RAPL) counters, Docker for
repository tasks, and a model server (llama.cpp for Paper 1, vLLM 0.10.2 for
Paper 2).

## Check the installation

Run one agent attempt against the built-in fixture model. It needs no GPU or
model download and writes the same records as a measured run:

```bash
python -m studies.energy_diagnosis.moe.run --mode fixture --output output/fixture
```

`output/fixture/summary.json` lists the attempt, its verifier decision and the
energy-window audit. Run the test suites with:

```bash
python -m pytest -q tests/test_business_workload.py tests/test_moe_query_workload.py tests/test_paper2_cohort.py
python scripts/check_energy_diagnosis_setup.py
```

## Paper 1: one agent, 4-bit versus 8-bit

Each attempt runs one agent on one task at one precision of a GGUF model served
by llama.cpp. A campaign plan fixes the tasks, precisions, seeds and execution
budgets before any run:

```bash
python -m studies.energy_diagnosis.diagnostics.campaign_plan --plan PLAN.json --output batches/
python -m studies.energy_diagnosis.moe.run --mode native --config CONFIG.json --output output/run
```

Each attempt records its settings, raw counter readings, the time span of every
model and tool call, token counts, the verifier decision and its validity
checks. Failed and invalid attempts are kept with their reason. The tasks and
verifiers are under `studies/energy_diagnosis/moe/` (one `*_WORKLOAD.md` file
per task family).

## Paper 2: many agents sharing one GPU

A cohort runs N agents at once against one vLLM server and measures the whole
cohort. The driver reads a frozen plan, qualifies the node, starts each server
configuration in turn and stops before the given cutoff:

```bash
python -m studies.paper2.cohort.qualify_node --out node.json
python -m studies.paper2.cohort.pilot --plan PLAN.json --out runs/main --budget-s 3600 --cutoff-utc 2026-01-01T00:00:00Z --dry-run
```

`--dry-run` prepares and checks every task and asset without starting a server.
Remove it to measure. `studies/paper2/README.md` describes the task suite,
models and server settings.

## Repository Layout

- `core/`: energy readers (powercap, NVML), sampling and measurement windows.
- `studies/energy_diagnosis/`: Paper 1 runtime, task families, verifiers, campaign planning and diagnostics.
- `studies/paper2/`: Paper 2 cohort driver, server control, task preparation and records.
- `tests/`: unit and fixture tests for both studies.
- `scripts/`: setup checks, node provisioning and data tools.
- `alems/`, `gui/`, `dashboard/`, `server.py`, `config/`, `migrations/`, `queries/`: the A-LEMS platform (database, dashboard and API), described in [docs/alems-platform.md](docs/alems-platform.md).
- `docs/`: platform documentation; `docs/team/` holds team onboarding and handoff notes.

## Releases

| Tag | Commit | Contents |
| --- | --- | --- |
| `paper1-qwen-187c227` | `187c227` | Paper 1 source named by the Qwen3-30B-A3B and held-out benchmark plans |
| `paper1-devstral-7dfd892` | `7dfd892` | Paper 1 source named by the Devstral Small 2 plan |
| `v1.0.0-paper1` | release | Paper 1 source archives and processed records ([release page](../../releases/tag/v1.0.0-paper1)) |
| `paper2-exec-d554bd1` | `d554bd1` | Paper 2 source used for the measured campaigns |

## Citation

Paper 1 preprint: arXiv link to be added. Authors: Stephen Abkin, Aldric Yang, Alex Flesher, Nitheesh Kodarapu, Deepak Panigrahy, Aakash Tyagi and David Kebo Houngninou (Texas A&M University).

```bibtex
@misc{abkin2026quantized,
  title  = {Measuring the Energy Cost of Completing Tasks with Quantized Language-Model Agents},
  author = {Abkin, Stephen and Yang, Aldric and Flesher, Alex and Kodarapu, Nitheesh and Panigrahy, Deepak and Tyagi, Aakash and Kebo Houngninou, David},
  year   = {2026},
  note   = {arXiv preprint arXiv:TODO}
}
```

The software is distributed under the [MIT license](LICENSE).

## Acknowledgments

The measurement platform is based on [A-LEMS](https://github.com/deepakpanigrahy03/a-lems)
by Deepak Panigrahy. Experiments ran on bare-metal NVIDIA A100 nodes provided
by [Chameleon Cloud](https://www.chameleoncloud.org).
