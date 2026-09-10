# Latest published context: nitheesh

[Immutable turn record](turns/20260910T164434Z-ni2-bounded-runner.md)

## Task and current understanding

NI1 is merged. NI2's independent fixture-ready scheduler/runner portion is implemented on `nitheesh/ni2-bounded-runner` from integration commit `d4f8616443651bb81f15da46f7720a4027d6987d`. It adapts an injected one-goal executor and does not duplicate Aldric's executor. The original integration checkout remains untouched.

## Decisions and implementation

- Deterministic seeded ordering is confined to declared preparation blocks.
- Every claim receives a transactionally persisted global actual order, including retries.
- Requested and observed settings/resources, preparation hash, costs, fidelity, sensor gaps, overlap reports, cleanup confirmation, and failure reason are retained outside the unchanged shared contract.
- Executor callbacks can durably checkpoint partial artifacts and metadata.
- Unexpected exits and surviving work keep the attempt running and block all new goals.
- Known original-clock termination becomes an immutable incomplete attempt with policy-bounded retry. Unknown endpoints are explicitly checkpointed without a fabricated end time and remain unresolved/running.
- Deterministic raw/summary exports retain all attempts and plan dispositions. Campaign validation flags structural mismatches and records per-attempt analysis eligibility/exclusion reasons.

Implementation commit: `aa94c61`.

## Tests and evidence

Fixture evidence only:

- NI2 runner + merged ledger + shared contract + workload bridge: 44 passed, 5 subtests passed.
- Python compilation: passed.
- UTF-8 setup/planning validator: passed.

No model, Grace, hardware, sensor, pilot, or campaign execution occurred.

## Open dependencies

Aldric's final executor callable/result mapping and Stephen's frozen scheduling protocol remain integration dependencies. A permanently unknown terminal endpoint still needs a shared contract representation; the runner preserves it as an unresolved checkpoint without inventing time. NI3 remains gated by accepted producers, pilot assets, a Grace allocation/session budget, and approval.

## Next actions

- Push `nitheesh/ni2-bounded-runner` and open a draft PR targeting `research/energy-diagnosis`; Stephen retains merge authority.
- Coordinate the executor adapter and final protocol fields when Aldric/Stephen publish them.
- Begin NI4 dummy-selector access/budget controls on a separate branch/PR while NI2 is reviewed.

This context update is intentionally on the feature branch for review; the user's branch-only restriction forbids the context publisher's direct integration path.

