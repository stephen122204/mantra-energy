# Measuring the Energy Cost of Completing Tasks with Quantized Language-Model Agents

Python software and processed records for the paper of the same name. The
study runs a coding and data-analysis agent on 29 verifiable tasks in six
families with 4-bit (Q4_K_M) and 8-bit (Q8_0) GGUF versions of Qwen3-30B-A3B
and Devstral Small 2, served by llama.cpp on NVIDIA A100 nodes. For each
attempt it measures CPU-package and GPU-board energy every 0.1 s, splits it
into model calls, tool calls and waiting, and checks the result with a hidden
verifier. It then compares energy per output token with energy per completed
task.

This branch is the Paper 1 release of
[alems-energy-diagnosis](https://github.com/stephen122204/alems-energy-diagnosis).
Its code is the source named by the Qwen and held-out benchmark plans (tag
`paper1-qwen-187c227`), with stray files removed and this README added. The
Devstral plan names a sibling commit (tag `paper1-devstral-7dfd892`) that
differs in seven files, mainly tool-call format handling and its tests.

## Install

Clone this branch:

```bash
git clone --branch paper-1 https://github.com/stephen122204/alems-energy-diagnosis.git paper-1
cd paper-1
```

Create a Python 3.11 environment and install the study dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-study.txt
```

Optional task dependencies are in `requirements-task-screen.txt` and
`studies/energy_diagnosis/moe/requirements-query.txt`. Measured runs need a
Linux node with an NVIDIA GPU, readable powercap (RAPL) counters, Docker for the
repository tasks, and llama.cpp.

## Check the installation

Run one attempt against the built-in fixture model. It needs no GPU or model
download and writes the same records as a measured run:

```bash
python -m studies.energy_diagnosis.moe.run --mode fixture --output output/fixture
```

`output/fixture/summary.json` lists the attempt, its verifier decision and the
energy-window audit.

## Run an experiment

A campaign plan fixes the tasks, precisions, seeds and execution budgets before
any run. Convert it into node batches, then run an attempt natively:

```bash
python -m studies.energy_diagnosis.diagnostics.campaign_plan --plan PLAN.json --output batches/
python -m studies.energy_diagnosis.moe.run --mode native --config CONFIG.json --output output/run
python -m studies.energy_diagnosis.moe.run --help
```

Each attempt records its settings, raw counter readings, the time span of every
model and tool call, token counts, the verifier decision and its validity
checks. Failed and invalid attempts are kept with their reason.

## Records

The processed records are attached to the
[v1.0.0-paper1 release](https://github.com/stephen122204/alems-energy-diagnosis/releases/tag/v1.0.0-paper1):
seven campaigns, 2,747 processed attempt rows, and the plans, specifications and
preflight checks behind them. `provenance.json` lists each campaign's machine,
model, budget and the source revision its plan names, and `SHA256SUMS` lists
every asset hash. The release also carries both source revisions as archives
and as a Git bundle.

## Repository Layout

- `studies/energy_diagnosis/moe/`: agent runtime, llama.cpp backend, task families and verifiers (one `*_WORKLOAD.md` per family).
- `studies/energy_diagnosis/diagnostics/`: campaign planning, scheduling and audits.
- `studies/energy_diagnosis/campaign/`, `runtime/`, `analysis/`: execution ledger, run configuration and analysis helpers.
- `core/`: energy readers (powercap, NVML), sampling and measurement windows.
- `tests/`: unit and fixture tests.
- `alems/`, `gui/`, `dashboard/`, `server.py`, `config/`, `migrations/`, `queries/`: the A-LEMS platform, described in [docs/alems-platform.md](docs/alems-platform.md).

## Citation

Preprint: arXiv link to be added.

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
