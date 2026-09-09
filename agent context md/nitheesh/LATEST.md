# Latest published context: nitheesh

[Immutable turn record](turns/20260909T220406Z-ed04-ledger.md)

## Task and current understanding

The user requested implementation of ED-04's resumable fixture execution ledger and explicitly prohibited commits to `research/energy-diagnosis`. The untouched integration checkout remains on `research/energy-diagnosis` at `03d078227feb7808df1950ced913ebc2a9cce188`. Work was performed in an isolated worktree on `nitheesh/ed-04-run-ledger`, based on the same fetched integration commit. Issue #4 is the NI1 entry milestone, not completion of Nitheesh's NI1–NI5 role.

The study asks whether bounded profiling can select an execution change that reduces measured energy per independently verified completion while preserving success and latency. Nitheesh owns the auditable campaign path: ledger, bounded scheduling/data validation, Grace pilot coordination, selector isolation, and approved evaluation exports. This turn is local fixture evidence only.

## Ideas and hypotheses

A standard-library SQLite ledger provides atomic plan claiming, stable identities, restart persistence, and uniqueness constraints without adding a runtime dependency. Keeping the planning generator unchanged preserves the distinction between planned slots and realized observations. A lossless JSONL export plus an inspectable CSV disposition table makes retries, failures, and missing measurements visible.

Stephen's latest contract audit identified positive infinity, duplicate measurement domains, and endpoint-touch windows as unsafe for analysis exports. The ledger rejects non-finite numeric values, duplicate domains, and measurements not fully bounded by the execution window without changing the shared v0.1 contract.

## Decisions and rationale

- Persist immutable plan provenance and append-preserved attempt outcomes in SQLite.
- Require explicit fixture labels for simulated session and clock identities.
- Make restart recovery explicit: persisted running attempts become `incomplete`, remain in history, and are requeued only within the retry limit.
- Require explicit retry requests after other terminal outcomes; every retry receives new execution and attempt IDs.
- Verify portable artifact paths, file presence, and SHA-256 before finalization.
- Preserve partial covered energy while unavailable energy remains null with a reason.
- Export all plans, including pending/running/terminal dispositions, and all realized attempts in deterministic order.
- Do not modify `contracts.py`, the planning generator, runtime, workload executor, hardware collector, or scientific selector.
- Do not use the direct-integration context publisher because the user's explicit branch-only instruction overrides that publication path for this work.

## Changes and artifacts

Implementation commit: `e683fcd07a1d221b525f326efb9b3f6f3a3f4d4f` on `nitheesh/ed-04-run-ledger`.

Changed:
- `studies/energy_diagnosis/campaign/ledger.py`: `PlannedRun`, `ArtifactRef`, `AttemptLease`, and `RunLedger` with registration, claim, finalization, recovery, retry, validation, and export.
- `studies/energy_diagnosis/campaign/demo.py`: five-slot simulated demonstration.
- `studies/energy_diagnosis/campaign/__init__.py` and README: public exports and usage/evidence boundaries.
- `tests/test_campaign_ledger.py`: fixture, restart, integrity, artifact, and export coverage.

The local ignored demonstration export contains five terminal plan slots and six attempts: success, model failure, verifier failure, interruption plus retry, and missing telemetry. Its validation report has no errors or warnings. It is not committed experimental data.

## Tests and evidence

Evidence level: fixture-tested only.

- Isolated Python 3.12 test environment: `python -X utf8 -m pytest -q tests/test_campaign_ledger.py tests/test_study_contracts.py tests/test_data_analysis_workload.py` — 32 passed, 3 subtests passed.
- `python -X utf8 scripts/check_energy_diagnosis_setup.py` — passed portable links, provenance, planner CSV/report, and readiness behavior.
- `python -m unittest discover -s tests -p test_campaign_ledger.py -v` — 9 passed before the final partial-energy/path additions; the final pytest run covers 10 campaign tests.
- `python -m py_compile studies/energy_diagnosis/campaign/ledger.py studies/energy_diagnosis/campaign/demo.py tests/test_campaign_ledger.py` — passed.
- `git diff --cached --check` before implementation commit — passed.

No live model, actual tool execution, Grace job, hardware sensor, energy measurement, or campaign ran.

## Open questions and disagreements

The shared contract does not carry a top-level attempt ID or artifact-reference collection, so ED-04 stores those in its ledger envelope while preserving the nested `ExecutionRecord` unchanged. Verifier artifact SHA-256 is retained in plan provenance because `VerifierResult` exposes a version but not an implementation hash. Stephen should decide whether those fields belong in a later shared-contract revision.

NI2 still needs the concrete Aldric executor callable and Stephen's frozen scheduling protocol. NI3 requires Alex's runtime/collector evidence, Aldric's controls and pilot assets, ED-07 acceptance, and an assigned Grace session/budget. NI4 can begin with a dummy selector, but final semantics belong to Stephen. NI5 remains conditional on pilot approval and a frozen method/evaluation plan.

## Next actions and handoff

Milestone status:
- NI1 / ED-04: fixture-tested in commit `e683fcd`; pending PR review/acceptance by Stephen.
- NI2 / ED-04/09: not started; next independent software milestone after this bounded PR.
- NI3 / ED-07/09: not started; externally dependent on accepted runtime, collector, executor, tasks, controls, pilot assets, and Grace authorization.
- NI4 / ED-10/11 support: not started; dummy-selector boundary can proceed independently, final method/freeze depends on Stephen.
- NI5: conditional on the validated pilot and approved frozen evaluation.

Push only `nitheesh/ed-04-run-ledger` and open a draft PR targeting `research/energy-diagnosis`. Do not merge or push directly to integration. The PR should identify commit `e683fcd`, the fixture-only evidence level, the simulated demo, and remaining hardware/integration limits.
