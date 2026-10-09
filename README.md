# A-LEMS: Agentic LLM Energy Measurement System

A-LEMS is a research platform for measuring the energy consumption, latency,
correctness and execution behavior of LLM and agentic workloads. This repository
extends the upstream platform with bounded task execution, independent verifiers,
CPU/GPU measurement, MoE inference and expert preparation controls, and campaign
recovery and result export.

The repository supports two uses:

- inspect saved experimental records and regenerate available analyses;
- run new experiments with explicit models, tasks, configurations and measurement
  boundaries.

This guide describes the integrated baseline at `6a49455` with the approved
cleanup. Additional functionality and data in PRs #62–75 remain unmerged.
The integration branch is `research/energy-diagnosis`; `main` preserves the
upstream baseline.

## Install and run

Obtain the [study repository](https://github.com/stephen122204/alems-energy-diagnosis)
with the required access. From the repository root, create a dedicated study
environment and install its dependencies:

```bash
python3 -m venv .venv-study
source .venv-study/bin/activate
python -m pip install -r requirements-study.txt
```

On Windows PowerShell, activate it with `.\.venv-study\Scripts\Activate.ps1`.
The study requirements specify version ranges, not a frozen historical environment.
Use a separate environment for the upstream GUI/server dependencies in
`requirements.txt`, whose constraints differ.

Run the portable checks:

```bash
python scripts/check_energy_diagnosis_setup.py
python scripts/check_study_runtime.py
python scripts/check_moe_pipeline.py
```

The setup checker validates planning/context integrity. Runtime and MoE checks
exercise fixtures; native lifecycle tests also need a C++17 compiler. These checks
do not qualify physical measurements or model correctness.

To exercise the complete local workflow with simulated model responses and counters:

```bash
python -m studies.energy_diagnosis.local_run --mode fixture \
  --settings C00,C01,C10,C11 --max-runs 12 --output /tmp/alems-local-smoke
```

Use a new output directory initially; rerun the identical command to check resume.
The command performs real tool computation but produces no physical energy evidence.
It is source-supported and was not executed for this documentation update.

For new measurements, follow [RUN_LOCAL.md](studies/energy_diagnosis/RUN_LOCAL.md)
for local vLLM/Ollama serving, or the [MoE guide](studies/energy_diagnosis/moe/README.md)
for the pinned native backend and its separate Python 3.11/CUDA environment.
Both require prepared models and qualified hardware/counters. The
[operations guide](studies/energy_diagnosis/moe/OPERATIONS.md) covers bounded runs,
recovery and verified output collection. Original Chameleon allocations have expired.

## Reproducibility

The [reproduction guide](studies/energy_diagnosis/reproduction/README.md) separates
**regenerating reported results** from **running new experiments**. It provides
verified CSV-to-summary/figure instructions, source-supported commands that remain
untested, and the steps needed to obtain and verify original artifacts. Different
hardware may reproduce the methodology without identical numerical measurements.

Complete raw-to-summary-to-paper reproduction is not yet possible here. Raw
campaign archives are inaccessible, some configurations and analysis scripts are
missing, and final manuscript outputs are unavailable. The
[artifact manifest](studies/energy_diagnosis/reproduction/artifact-manifest.json)
records available evidence, known hashes, unmerged revisions and remaining gaps.
A future Zenodo release has not been completed. Installation and full runtime/GPU
validation were not repeated for this documentation update; see the guide for
verified checks and limitations.

## Repository layout

- `core/`, `alems/`, `gui/`: platform execution, measurement, databases and interfaces.
- `studies/energy_diagnosis/`: study runtime, tasks/verifiers, MoE controls, campaigns,
  diagnostics and reproduction documentation.
- `config/`, `tests/`, `scripts/`: configurations, validation and operator utilities.
- `docs/`, `docs-src/`: technical and historical documentation. Team contributors
  start at [START_HERE.md](START_HERE.md).

## Citations

Until a versioned release citation is available, identify this repository and the
exact source revision used for an experiment. No final paper citation or Zenodo
DOI is established by this documentation.

A-LEMS originates from [Deepak Panigrahy's upstream platform](https://github.com/deepakpanigrahy03/alems-platform);
its baseline is recorded in [provenance.json](studies/energy_diagnosis/provenance.json).
The repository uses the [MIT license](LICENSE). Models, external datasets and
backend dependencies retain their own licenses and citation requirements.
