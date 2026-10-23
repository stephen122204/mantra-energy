# Latest published context: nitheesh

[Immutable turn record](turns/20260910T171443Z-ni4-selector-controls.md)

## Current milestone status

- NI1 / ED-04: accepted and merged in PR #22.
- NI2 / ED-04/09: fixture-tested in draft PR [#25](https://github.com/stephen122204/alems-energy-diagnosis/pull/25), implementation commit `aa94c61`; local and PR checks passed.
- NI3 / ED-07/09: blocked on accepted runtime/collector/executor/tasks, pilot assets, an assigned Grace session/budget, and Stephen's pilot approval. No hardware run occurred.
- NI4 / ED-10/11 support: fixture-tested in draft PR [#26](https://github.com/stephen122204/alems-energy-diagnosis/pull/26), implementation commit `78d055c`; local and PR checks passed.
- NI5: conditional on validated pilot evidence and an approved frozen evaluation.

## NI4 behavior

The injected selector receives only eligible candidates, allowlisted profiling features, budget status, a profile query capability, and recommendation/abstention seal methods. Every query attempt retains time/energy cost, failure, and explicit unavailable-energy semantics. Undeclared feature values are withheld and recorded as a failed cost-bearing query.

Decisions are immutable and content-hashed. Reference outcomes cannot be loaded/exported before sealing and remain absent from selection exports afterward. Live evaluation accepts only the exact sealed recommendation; abstention has no live setting. This is a Python capability boundary, not an OS sandbox or a final scientific method.

## Evidence and dependencies

NI4 + ledger + contract + workload fixtures: 45 passed, 5 subtests passed. Compilation, UTF-8 setup validation, and PR #26's `handoff-and-plan`/`windows-ledger` checks passed. Evidence is fixture-only: no real selector, model, held-out evaluation, Grace job, hardware energy, pilot, or campaign ran.

Stephen must freeze selector semantics, allowed observables, budgets, lineages, and process/storage isolation. Stephen retains merge authority. NI2 still needs eventual Aldric executor/protocol integration. NI3 remains externally blocked; NI5 remains conditional.

The integration checkout remains untouched. This context is on the NI4 feature branch for review because the user's branch-only restriction forbids direct context publication to integration.

