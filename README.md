# Measuring the Energy Cost of Completing Tasks with Quantized Language-Model Agents

Code and experiment records for the paper of the same name. The software runs
coding and data-analysis agents, checks whether they complete their tasks
correctly, and measures the energy used by the CPU and GPU. It compares energy
per output token with energy per correctly completed task, counting the energy
spent on failed attempts as well.

The study covers 29 tasks in six families and compares 4-bit and 8-bit versions
of Qwen3-30B-A3B and Devstral Small 2, served by llama.cpp on NVIDIA A100 GPUs.
Task checks are kept separate from the files the agent can access.

## Choose the code and data

This branch contains the Qwen implementation. The Devstral implementation has
separate tool-call handling and is available from the
[release downloads](https://github.com/stephen122204/mantra-energy/releases/tag/v1.0.0-paper1).
The release also includes records for 2,747 attempts across seven sets of
experiments, available experiment settings, and a guide to the downloads.

## Install

Clone this branch and install the Python dependencies:

```bash
git clone --branch paper-1 https://github.com/stephen122204/mantra-energy.git paper-1
cd paper-1
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-study.txt
```

Additional dependencies for particular tasks are listed in
`requirements-task-screen.txt` and
`studies/energy_diagnosis/moe/requirements-query.txt`.

## Try it without a GPU

The following test uses simulated model responses and energy readings to check
that the software runs and saves its results. It does not download a model:

```bash
python -m studies.energy_diagnosis.moe.run --mode fixture --output output/fixture
```

Open `output/fixture/summary.json` to inspect the recorded outcomes. These are
test results, not measurements of a real model.

## Measure a model

Real measurements require a Linux machine with an NVIDIA GPU, access to CPU
energy counters through RAPL and GPU counters through NVML, model weights, and
llama.cpp. Repository repair tasks also require Docker. The measurements cover
the CPU packages and GPU board, rather than total power drawn at the wall.

An experiment configuration specifies the model, tasks, repeated attempts,
random seeds, and limits on turns, generated tokens and execution time. Follow
[the experiment-running guide](studies/energy_diagnosis/CAMPAIGN_OPERATIONS.md)
for preparing the machine and running a configured experiment. Download model
weights and benchmark inputs separately under their respective licenses.

The software saves model and tool calls, token counts, energy readings and task
check results. Failed or interrupted attempts are retained with their reasons.

## Read the saved results

Download `paper1-processed-artifacts-9e564de.tar.gz` from the release page.
It contains CSV files with one row per attempt, along with the available
experiment settings and machine checks. The release also provides:

- `provenance.json` describes which machine, model, settings and code version
  are associated with each experiment, and identifies missing records.
- `VALIDATION.md` lists the checks performed on the packaged files.
- `SHA256SUMS` lets you check that downloaded files match the release.

Recreating all paper figures still requires raw measurement logs, some original
settings and analysis scripts, and a mapping from saved experiments to figures.
The recorded configurations identify intended code versions; the version used
for every individual attempt has not been verified.

## Find the implementation

| Directory | Contents |
| --- | --- |
| `studies/energy_diagnosis/moe/` | Agent execution, model integration, tasks and correctness checks |
| `studies/energy_diagnosis/diagnostics/` | Experiment scheduling and validation tools |
| `core/` | CPU and GPU energy readers and sampling |
| `tests/` | Automated software tests |

The underlying measurement platform is described in
[the A-LEMS documentation](docs/alems-platform.md).

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
