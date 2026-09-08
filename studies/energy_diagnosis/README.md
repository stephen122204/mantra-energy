# Energy-diagnosis study workspace

Start at [the team entry point](../../START_HERE.md). This directory reserves implementation boundaries; the runner, task suite and selector are not implemented here yet.

| Directory | Owner | Scope |
|---|---|---|
| runtime/ | Alex | Study configuration and capability exports; reuse core adapters/readers |
| workloads/ | Aldric | Task assets, independent verifiers and bounded trace execution |
| campaign/ | Nitheesh | Execution ledger, orchestration and export validation |
| analysis/ | Stephen | Diagnostic method, fair baselines and evaluation |
| fixtures/ | Shared through review | Small synthetic examples for CI; clearly labeled simulated |

The common record contract is implemented in [`contracts.py`](contracts.py) (ED-01, v0.1) with worked examples in [`fixtures/contract_examples/`](fixtures/contract_examples/) and tests in `tests/test_study_contracts.py`. Design rationale: [the handoff](../../docs/agent-context/04-interfaces-and-data.md). Producers and consumers use these types; changes go through a PR against the module (additive fields in minor versions, renames bump `CONTRACT_VERSION`). Callable/module names for the runner, executor and collector are still owned by their milestones.

The planning-only manifest and generator remain in [starter](../../docs/agent-context/starter/README.md) as a single source of truth. Do not create competing copies. Large model/task assets, actual measurements and personal configuration stay in approved storage with hashes, not here.
