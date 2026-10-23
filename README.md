# MANTRA: Energy Measurement for Language-Model Agents

Python software for measuring the energy that AI agents spend to complete
verifiable tasks on locally hosted language models. It runs an agent on coding
and data-analysis tasks, reads CPU-package and GPU-board energy counters every
0.1 s, attributes the energy to model calls, tool calls and waiting, and checks
each attempt with a hidden verifier. The measurement layer builds on the
[A-LEMS](https://github.com/deepakpanigrahy03/a-lems) platform.

The repository supports two papers that share this code:

| Paper | Question | Code | Release branch |
| --- | --- | --- | --- |
| *Measuring the Energy Cost of Completing Tasks with Quantized Language-Model Agents* | Does the precision that is cheaper per token also complete tasks with less energy? | `studies/energy_diagnosis/` | [`paper-1`](https://github.com/stephen122204/mantra-energy/tree/paper-1) |
| Paper 2 (in preparation) | Which weight precision completes tasks with the least energy when many agents share one GPU? | `studies/paper2/` | [`paper-2`](https://github.com/stephen122204/mantra-energy/tree/paper-2) |

Use the release branches for the paper-specific code and setup instructions.
[Releases](#releases) provide downloadable code and saved experiment records.

## Install

Clone the repository:

```bash
git clone https://github.com/stephen122204/mantra-energy.git
cd mantra-energy
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

Check the installation with simulated model responses and energy readings.
This test needs no GPU or model download:

```bash
python -m studies.energy_diagnosis.moe.run --mode fixture --output output/fixture
```

`output/fixture/summary.json` contains the simulated outcomes and measurement
checks. Run the automated software tests with:

```bash
python -m pytest -q tests/test_business_workload.py tests/test_moe_query_workload.py tests/test_paper2_cohort.py
python scripts/check_energy_diagnosis_setup.py
```

## Paper 1: one agent, 4-bit versus 8-bit

The software runs one agent on one task at a chosen model precision, then
checks its answer and records the energy used. The experiment settings specify
the tasks, repeated attempts, random seeds, and limits on turns, tokens and time.
Saved records include model and tool calls, token counts, energy readings and
correctness checks, including failed attempts.

See the [Paper 1 setup guide](https://github.com/stephen122204/mantra-energy/tree/paper-1)
for installation, hardware requirements and the available results. The
[release page](https://github.com/stephen122204/mantra-energy/releases/tag/v1.0.0-paper1)
provides separate code downloads for Qwen and Devstral, along with the saved
experiment records.

## Paper 2: many agents sharing one GPU

The software runs a group of agents at once against one vLLM model server and
measures the energy used by the group. It checks the machine, loads the
experiment settings, starts each server configuration in turn, and stops at
the configured time limit:

```bash
python -m studies.paper2.cohort.qualify_node --out node.json
python -m studies.paper2.cohort.pilot --plan PLAN.json --out runs/main --budget-s 3600 --cutoff-utc 2026-01-01T00:00:00Z --dry-run
```

`--dry-run` prepares and checks the tasks and required files without starting a server.
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
| `paper1-qwen-187c227` | `187c227` | Archived Qwen code, including BIRD and EvalPerf experiments |
| `paper1-devstral-7dfd892` | `7dfd892` | Archived Devstral code |
| `v1.0.0-paper1` | release | Paper 1 code downloads and saved experiment results ([release page](https://github.com/stephen122204/mantra-energy/releases/tag/v1.0.0-paper1)) |
| `paper2-exec-d554bd1` | `d554bd1` | Paper 2 source used for the measured campaigns |

## Citation

Paper 1 preprint: arXiv link to be added.

```bibtex
@misc{paper1-arxiv,
  title  = {Measuring the Energy Cost of Completing Tasks with Quantized Language-Model Agents},
  author = {Abkin, Stephen and Yang, Aldric and Flesher, Alex and Kodarapu, Nitheesh and Panigrahy, Deepak and Tyagi, Aakash and Houngninou, David Kebo},
  year   = {2026},
  note   = {Preprint}
}
```

The software is distributed under the [MIT license](LICENSE).

## Acknowledgments

The measurement platform is based on [A-LEMS](https://github.com/deepakpanigrahy03/a-lems)
by Deepak Panigrahy. Experiments ran on bare-metal NVIDIA A100 nodes provided
by [Chameleon Cloud](https://www.chameleoncloud.org).
