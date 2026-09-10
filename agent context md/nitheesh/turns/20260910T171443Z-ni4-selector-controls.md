# Turn summary: Nitheesh — 20260910T171443Z-ni4-selector-controls

## Task and current understanding

Continue Nitheesh's complete assignment after delivering NI2 draft PR #25. The next independent milestone is NI4 support for ED-10/11: profiling-budget accounting, a restricted selector capability, immutable recommendation/abstention sealing, and a post-seal hidden-reference/live-evaluation boundary. Stephen retains ownership of the scientific selector, uncertainty/abstention semantics, baselines, estimands, freeze, and conclusions.

Work is on `nitheesh/ni4-selector-controls`, based directly on integration commit `d4f8616443651bb81f15da46f7720a4027d6987d`. It is independent of NI2 PR #25. The existing integration checkout was not switched, edited, committed, merged, or pushed.

## Ideas and hypotheses

A useful early interface does not require inventing the final selector. A dummy selector can receive only declared candidates, an allowlisted profile result, remaining budget, and seal methods. Reference outcomes need not exist in the selector process/state until after the seal. This makes forbidden access and post-hoc replacement testable now.

Observed time/energy caps cannot know a query's final cost before it runs. The implementation records the cost-bearing query even if it reaches or crosses the threshold, then blocks subsequent queries. Unknown energy under an active energy budget also blocks further queries rather than silently treating cost as zero.

## Decisions and rationale

- Use a standard-library SQLite store for immutable session definitions, every profile attempt, sealed decisions, separately opened references, and live-evaluation evidence.
- Freeze eligible candidates, allowed profile feature names, selector revision, development-data hash, and query/time/energy budgets per session.
- Convert undeclared profiler fields into a failed cost-bearing query and withhold those values from the selector.
- Persist failed profile results and profiler exceptions with duration, energy or explicit unavailability, and failure reason.
- Supply selectors only `RestrictedSelectorAPI`; no reference loader/result is present on that capability.
- Seal recommendation or abstention exactly once with linked query IDs, complete aggregate costs, timestamp, provenance, rationale/reason, and a content hash.
- Reject reference loading/export before sealing and reject incomplete candidate coverage.
- Allow live evaluation only for the exact sealed recommendation; abstention has no selected live setting.
- Keep selection exports reference-free even after separate reference results are opened.
- Document that this is a Python capability boundary, not an operating-system sandbox for hostile code. Stephen owns final process/storage isolation.

## Changes and artifacts

Implementation commit: `78d055c`.

Draft PR: https://github.com/stephen122204/alems-energy-diagnosis/pull/26

- `studies/energy_diagnosis/analysis/selector_boundary.py`: budgets, profile result contract, restricted selector API, durable session/query ledger, decision sealing, reference opening, sealed-setting live evaluation, integrity validation, and deterministic separate exports.
- `studies/energy_diagnosis/analysis/__init__.py`: public NI4 interfaces.
- `studies/energy_diagnosis/analysis/README.md`: behavior, observed-cost semantics, evidence limits, and ownership boundaries.
- `tests/test_selector_boundary.py`: dummy-selector fixtures for leakage attempts, budget/failure paths, abstention, immutable reopen, tamper detection, reference separation, and live setting enforcement.

No reference datasets, hidden outcomes, model results, hardware readings, campaign data, or generated exports were committed.

## Tests and evidence

Evidence level: fixture-tested only.

- `python -m pytest tests/test_selector_boundary.py tests/test_campaign_ledger.py tests/test_study_contracts.py tests/test_data_analysis_workload.py -q` — 45 passed, 5 subtests passed.
- `python -X utf8 -m py_compile studies/energy_diagnosis/analysis/selector_boundary.py tests/test_selector_boundary.py` — passed.
- `python -X utf8 scripts/check_energy_diagnosis_setup.py` — passed.
- PR #26 `handoff-and-plan` — passed.
- PR #26 `windows-ledger` — passed.
- `git diff --cached --check` before the implementation commit — passed.

These fixtures prove interface behavior only. They do not establish selector quality, fair-baseline performance, held-out generalization, energy savings, hardware validity, campaign validity, novelty, or paper readiness.

## Open questions and disagreements

- Stephen must freeze the actual selector inputs/features, query budget, uncertainty and abstention behavior, candidate eligibility, development/held-out lineages, and process/storage isolation. The current values are caller-provided fixture declarations.
- NI4's observed duration/energy thresholds retain a crossing query and stop the next query. Stephen should confirm that policy or define reservable per-query limits before frozen evaluation.
- The final selector implementation must replace the dummy callback and pass the same no-reference/budget/seal tests. No recommendation in these tests is a scientific decision.
- NI2 PR #25 still needs review and eventual Aldric executor/protocol integration. NI3 is blocked on accepted producers, pilot assets, an assigned Grace session/budget, and Stephen's pilot approval.

## Next actions and handoff

Milestone status:

- NI1 / ED-04: accepted and merged in PR #22.
- NI2 / ED-04/09: fixture-tested in draft PR #25 at implementation commit `aa94c61`; checks passed. Await Stephen review and producer-interface coordination.
- NI3 / ED-07/09: blocked on actual component integration and hardware/session gates. No cluster run was launched.
- NI4 / ED-10/11 support: fixture-tested in draft PR #26 at implementation commit `78d055c`; checks passed. Await Stephen's interface/freeze review.
- NI5: conditional on validated pilot evidence and approved frozen evaluation.

Stephen retains merge authority for PRs #25 and #26. Continue with NI3 only when its concrete dependencies are available; otherwise address review feedback without combining the two branches. Per the user's restriction, this record and `LATEST.md` are committed to the NI4 feature branch, not pushed directly to integration by the context publisher.

