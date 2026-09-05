# First issues and dependency order

These are ready to copy into the team issue tracker. They have not been created remotely. Each issue should name an owner and link its PR, evidence note and actual baseline.

| ID | Owner | Concrete issue | Depends on | Definition of done |
|---|---|---|---|---|
| ED-01 | Stephen | Establish repository, baseline and v0 interfaces | None | Remote/visibility recorded, root instructions merged, model/runtime decision path and types agreed |
| ED-02 | Student 1 | Reproduce and repair local provider response/timing | ED-01 | Provider fixtures, minimal fix, actual resolved registry shown, live check when available |
| ED-03 | Student 2 | First data goal and independent verifier | ED-01 | Correct/wrong/malformed fixtures and immutable input contract |
| ED-04 | Student 3 | Resumable fixture run ledger | ED-01 | Restart/error/missing-measurement checks with complete dispositions |
| ED-05 | Student 1 | Grace telemetry preflight and endpoint validation | ED-01, assigned access | Domain/permission report, raw sample, delayed-teardown check and isolation status |
| ED-06 | Student 2 | Four controls and bounded dependency execution | ED-03 | Real worker effect, eligibility checks, stable result mapping and trace/fidelity records |
| ED-07 | All; Stephen integrates | One full verified goal on Grace | ED-02–06 | Real inference + tools + verifier + valid linked CPU/GPU observations |
| ED-08 | Student 2 | Repository family and four pilot goal assets | ED-03 | Independent verifier, meaningful controls and lineage metadata |
| ED-09 | Student 3 | Pilot campaign runner | ED-07–08 | Complete randomized pilot ledger and validation report |
| ED-10 | Stephen | Diagnostic opportunity and fair baselines | ED-09 | Written evidence for method opportunity or explicit direction change |
| ED-11 | Stephen + Student 3 | Frozen held-out selection/evaluation boundary | ED-10 | Frozen policy/splits, budget tracking and no-reference-leak fixture |

## Parallel work that is useful

ED-02, ED-03 and ED-04 can proceed independently after interfaces are agreed. ED-05 can proceed while local software work continues. Student 2 can develop the second task family before GPU integration. Do not block all students on one hardware reservation.

## Short weekly working rhythm

- Each student submits a small PR plus 12-progress-template.md, with exact evidence rather than an agent-generated percentage complete.
- Review one real end-to-end trace together; check that what is being measured is the workload the task claims to execute.
- Book measured runs separately from exploratory development. Record actual allocation/host/device and session conditions.
- Stephen updates the decision log when changing method, model, candidate, verifier or energy scope.

## Gates

**Engineering gate:** correct local output, independent verification, meaningful controls, credible measurement boundaries and joins. Mock-only success does not pass this gate.

**Research gate:** evidence that a diagnostic decision is useful beyond straightforward profiling. If this fails, continue bounded investigation or revise scope rather than automatically expand to other clusters.

**Campaign gate:** frozen assets/runtime/policies, valid isolation and telemetry, adequate measured resource budget, held-out separation and runnable analysis.

The repository bootstrap and documentation are not authority to launch ED-09 or the main campaign automatically. Each operator uses the agreed reservation and budget.
