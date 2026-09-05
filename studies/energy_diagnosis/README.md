# Energy-diagnosis study workspace

Start at [the team entry point](../../START_HERE.md). This directory reserves implementation boundaries; the runner, task suite and selector are not implemented here yet.

| Directory | Owner | Scope |
|---|---|---|
| runtime/ | Student 1 | Study configuration and capability exports; reuse core adapters/readers |
| workloads/ | Student 2 | Task assets, independent verifiers and bounded trace execution |
| campaign/ | Student 3 | Execution ledger, orchestration and export validation |
| analysis/ | Stephen | Diagnostic method, fair baselines and evaluation |
| fixtures/ | Shared through review | Small synthetic examples for CI; clearly labeled simulated |

The common record contract is in [the handoff](../../docs/agent-context/04-interfaces-and-data.md). Stephen must review exact API/schema decisions in ED-01 before dependent implementations diverge. Proposed API names are not implemented contracts.

The planning-only manifest and generator remain in [starter](../../docs/agent-context/starter/README.md) as a single source of truth. Do not create competing copies. Large model/task assets, actual measurements and personal configuration stay in approved storage with hashes, not here.
