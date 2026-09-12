# Turn summary: Nitheesh — 20260910T164434Z-ni2-bounded-runner

## Task and current understanding

Continue Nitheesh's assignment after the merged NI1 ledger by implementing the independent fixture-ready portion of NI2: seeded ordering within declared blocks, a one-goal runner that consumes an executor callback, actual execution metadata, durable checkpoints, validation, deterministic exports, and interruption/recovery behavior. Work is on `nitheesh/ni2-bounded-runner`, based on integration commit `d4f8616443651bb81f15da46f7720a4027d6987d`. The existing integration checkout was not switched, edited, or committed.

Stephen's accepted NI1 ledger remains the foundation. NI2 must adapt Aldric's eventual executor rather than implement another task executor. This turn defines and fixture-tests that callback boundary; no live model, Grace allocation, hardware collector, or campaign was invoked.

## Ideas and hypotheses

The runner can remain useful while the exact producer interfaces are pending if its boundary accepts one claimed goal and requires a complete `ExecutionOutcome`. Declared schedule facts belong in an immutable schedule manifest; observed settings, resources, fidelity, costs, and failures belong beside each ledger attempt. This preserves differences instead of overwriting the plan.

An executor that disappears or reports surviving owned work must not allow another claim. Durable checkpoints can retain partial artifact references and explicit unknown-endpoint interruption facts while leaving the attempt running until an original-clock endpoint is available.

## Decisions and rationale

- Shuffle deterministically inside each declared preparation block using the campaign seed and block identity; never move runs across blocks.
- Persist a global, transactionally assigned `actual_order` for every attempt, including retries.
- Keep contract-v0.1 unchanged. Store NI2 orchestration observations in strict canonical JSON ledger metadata.
- Give the executor callback a durable checkpoint writer. Checkpointed artifact references are cumulative and survive recovery/finalization.
- Reject same-clock temporal overlap at claim time and refuse finalization unless the executor confirms all owned work terminated.
- Represent an interruption with no trustworthy endpoint as an explicit checkpoint and leave the attempt running. Do not fabricate an end time from a restarted host.
- Treat setting/preparation mismatches, reported overlapping measurement domains, missing/corrupt artifacts, and surviving work as validation errors while retaining the raw attempt.
- Give every realized attempt an explicit analysis-eligibility decision; failed, partial, unavailable, divergent, or sensor-gap observations remain exported with exclusion reasons.
- Keep NI4 selector controls out of this PR; they require a separate feature branch and review.

## Changes and artifacts

Implementation commit: `aa94c61` on `nitheesh/ni2-bounded-runner`.

- `studies/energy_diagnosis/campaign/runner.py`: immutable seeded schedules, executor request/outcome types, bounded runner, checkpoint callback, interruption delegation, deterministic schedule export, and campaign validation.
- `studies/energy_diagnosis/campaign/ledger.py`: compatible NI1 database migration, global actual attempt order, claim/outcome metadata, durable partial checkpoints, explicit unknown-endpoint interruption records, same-clock overlap prevention, preserved checkpoint artifacts, and expanded JSONL/CSV exports.
- `studies/energy_diagnosis/campaign/__init__.py`: public NI2 interfaces.
- `studies/energy_diagnosis/campaign/README.md`: runner, recovery, export, and evidence boundaries.
- `tests/test_campaign_runner.py`: fixture coverage for seeded blocks, actual order, expected failures, cleanup gates, known/unknown interruption handling, retries, partial telemetry, mismatches, corrupt/missing artifacts, deterministic export, and complete dispositions.

No generated campaign data or large artifacts were committed.

## Tests and evidence

Evidence level: fixture-tested only.

- `python -m pytest tests/test_campaign_runner.py tests/test_campaign_ledger.py tests/test_study_contracts.py tests/test_data_analysis_workload.py -q` — 44 passed, 5 subtests passed.
- `python -X utf8 -m py_compile studies/energy_diagnosis/campaign/ledger.py studies/energy_diagnosis/campaign/runner.py tests/test_campaign_runner.py` — passed.
- `python -X utf8 scripts/check_energy_diagnosis_setup.py` — passed portable links, provenance, planner CSV/report, and readiness behavior.
- `git diff --cached --check` before the implementation commit — passed.

The tests use simulated fixture sessions and clocks. They do not establish model correctness, Grace compatibility, hardware energy availability, domain isolation, physical sensor coverage, or campaign validity.

## Open questions and disagreements

- Aldric's final executor callable and result mapping are still pending. The NI2 `ExecutorRequest -> ExecutionOutcome` boundary is intentionally narrow and may need a reviewed adapter once AL2 is available.
- Stephen still owns the frozen scheduling protocol and the shared representation for terminal attempts whose original-clock endpoint can never be recovered. This PR records that state durably without inventing a timestamp, but cannot make it terminal under contract-v0.1.
- Actual process discovery/termination belongs to the executor integration. The fixture runner enforces the confirmation gate but does not claim to kill unknown processes.
- NI3 remains externally gated by accepted runtime, collector, executor, tasks/controls, pilot assets, an assigned Grace session/budget, and Stephen's pilot approval.

## Next actions and handoff

Milestone status:

- NI1 / ED-04: merged and accepted after Stephen's repairs.
- NI2 / ED-04/09: fixture implementation committed on `nitheesh/ni2-bounded-runner`; push and draft PR are the next delivery actions. Live executor/collector integration remains pending producer handoffs and gates.
- NI3 / ED-07/09: blocked on integration and hardware/session prerequisites; no cluster run is authorized by this work.
- NI4 / ED-10/11 support: next independent software milestone, to be implemented with a dummy selector in a separate branch/PR.
- NI5: conditional on validated pilot evidence and an approved frozen evaluation plan.

Per the user's explicit restriction, this context record and `LATEST.md` update are committed to the feature branch for review. The direct-integration context publisher is not used.

