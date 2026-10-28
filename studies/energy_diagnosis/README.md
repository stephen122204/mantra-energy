# Energy-diagnosis study workspace

This directory contains the measurement runtime, task families, and campaign tools.

| Directory | Owner | Scope |
|---|---|---|
| runtime/ | Alex | Study configuration and capability exports; reuse core adapters/readers |
| workloads/ | Aldric | Task assets, independent verifiers and bounded trace execution |
| campaign/ | Nitheesh | Execution ledger, orchestration and export validation |
| analysis/ | Stephen | Diagnostic method, fair baselines and evaluation |
| fixtures/ | Shared through review | Small synthetic examples for CI; clearly labeled simulated |

The common record contract is implemented in [`contracts.py`](contracts.py) (ED-01, v0.1) with worked examples in [`fixtures/contract_examples/`](fixtures/contract_examples/) and tests in `tests/test_study_contracts.py`. The record fields are documented in `contracts.py`. Producers and consumers use these types; changes go through a PR against the module (additive fields in minor versions, renames bump `CONTRACT_VERSION`). Callable/module names for the runner, executor and collector are still owned by their milestones.

The planning-only manifest and generator remain in [starter](planning/README.md) as a single source of truth. Do not create competing copies. Large model/task assets, actual measurements and personal configuration stay in approved storage with hashes, not here.

[`integration.py`](integration.py) provides the single-goal producer/consumer
seam used by local AX4 fixtures. Runtime and measurement providers are injected
through the documented shared shapes; simulated providers remain explicitly
labeled and are not Grace evidence.

## Integrated execution

Use [RUN_LOCAL.md](RUN_LOCAL.md) for installation, portable regression checks, the complete fixture run, node preflight and a bounded live-model invocation. Hardware acceptance is separate from fixture success.
