# Latest published context: alex

[Immutable turn record](turns/20260911T000852Z-ax4-local-integration.md)

# Turn summary: Alex — 20260911T000852Z-ax4-local-integration

**Publication boundary:** This record contains implementation requirements, decisions, tests, hardware setup dependencies and handoff details only.

## Task and current understanding

AX4 / ED-07 requires the shared task, real runtime, collector, independent verifier and durable ledger to produce one linked goal record locally and then on Grace. This turn completes only the explicitly simulated local producer/consumer seam. The branch `alex/ed-07-local-integration` starts from fetched integration `18d712d78801169ff74527dbc6a8d85fda31cfc5`; exact tested and pushed head is `a906906605568a28225e2cfbc14ee1d026a81ccf`. Draft PR #28 targets `research/energy-diagnosis`: https://github.com/stephen122204/alems-energy-diagnosis/pull/28.

The current integration branch contains ED-01 contracts, Aldric's ED-03 task/verifier and Nitheesh's ED-04 ledger. It does not contain Aldric's bounded executor/controls, Alex's ED-02 repair (draft PR #24) or Alex's ED-05 session implementation (draft PR #27). This AX4 branch does not copy or depend on those unfinished branches. Instead, runtime and measurement providers are injected through the documented shared callable/record shapes and marked simulated.

Alex clarified that he has individual Grace access and can run experiments. Access alone is therefore not a blocker. Repository requirements still call for a booked/assigned compute session, named allocation and bounded run budget for hardware work, and ED-09/main campaign expansion remains gated. A single controlled capability/integration run can be prepared once its exact allocation, installed model/runtime and run budget are recorded.

Milestone status:

| Milestone | Status/evidence | Remaining |
|---|---|---|
| AX1 / ED-02 | Fixture/fix checkpoint confirmed by Stephen; draft PR #24 head `d0d4e85` | One real response with actual configuration/runtime/device evidence |
| AX2 / ED-05 | Fixture-tested draft PR #27 head `47472d4` | Review/integration and actual sensor evidence |
| AX3 / ED-05/12 | Local capability software prepared; Alex confirms Grace access | Record exact allocation/session/budget, then actual domains, refresh/coverage, isolation and overhead |
| AX4 / ED-07/09 | Local simulated integration fixture-tested in PR #28 at `a906906` | Reviewed runtime/measurement dependencies, Aldric executor/controls, then one real Grace goal; bounded pilot still gated |
| AX5 / post-pilot | Conditional | Validated pilot and frozen runtime/measurement definition |

## Ideas and hypotheses

The safe local seam is a narrow orchestrator consuming only the merged contracts. It should reject producer identity or clock mismatches before a record can enter the ledger. Runtime and measurement implementations can later replace simulated providers without changing the durable `ExecutionRecord` consumer boundary. Repeated exports of the same finalized attempt should remain byte-identical even though newly claimed attempts receive unique IDs.

## Decisions and rationale

Added a single-goal orchestrator that validates task/plan/verifier identities, claims a ledger attempt, calls an injected runtime, independently verifies completed structured output, closes an injected measurement window, validates response/sample/measurement timing and identity, writes integrity-pinned model-output/raw-sample artifacts and finalizes the ledger. Failed runtime responses retain model status, error and partial token counts; verification becomes unavailable rather than pass. Wrong completed output remains a completed execution with verifier failure. Missing CPU/GPU energy remains null with reasons.

The implementation does not define Aldric's executor or controls, alter the workload, change the frozen contract, change Nitheesh's ledger, or absorb open PR code. It does not claim that simulated runtime or sensor providers are real components.

## Changes and artifacts

- `studies/energy_diagnosis/integration.py`: integration protocols, identity/timing validation, single-goal orchestration and deterministic artifact writing.
- `tests/test_integrated_goal.py`: simulated success, wrong answer, runtime failure, missing energy, identity mismatch, timing and deterministic export checks.
- `studies/energy_diagnosis/README.md`: local seam and evidence boundary.
- Exact commit: `a906906605568a28225e2cfbc14ee1d026a81ccf`.
- Draft PR: https://github.com/stephen122204/alems-energy-diagnosis/pull/28.
- No model execution, tool-control execution, Grace job, physical sensor measurement or pilot ran.

## Tests and evidence

Evidence level: **fixture-tested local integration**, not hardware-tested or campaign-validated.

- `python3 scripts/check_energy_diagnosis_setup.py` — passed; setup/planning only.
- `python3 -m pytest -q tests/test_integrated_goal.py tests/test_campaign_ledger.py tests/test_data_analysis_workload.py tests/test_study_contracts.py tests/test_energy_collector.py` — 52 passed, 5 subtests passed in 0.88s at exact commit `a906906605568a28225e2cfbc14ee1d026a81ccf`.
- `python3 -m py_compile studies/energy_diagnosis/integration.py tests/test_integrated_goal.py` — passed.
- `git diff --check` — passed.
- PR #28 GitHub checks `handoff-and-plan` and `windows-ledger` — passed at the exact head.
- An attempted command included `tests/test_openai_compat_adapter.py`, but integration does not contain that unmerged PR #24 file; pytest stopped before running tests. No adapter-regression pass is claimed from that command. The available merged suites were then run successfully as listed above.

Local fixtures prove linked success, independent rejection of wrong output, model failure with partial accounting, null unavailable CPU/GPU measurements, exact goal boundaries, runtime metadata preservation, artifact references, producer/consumer mismatch rejection and byte-identical repeat exports. They do not prove actual model/tool execution, physical energy, device/domain coverage or isolation.

## Open questions and disagreements

Full local G2 still lacks Aldric's merged single-goal executor/real controls, and the reviewed Alex runtime/measurement implementations are not on integration. Therefore PR #28 is a contract integration seam, not a complete real-component local gate. Full ED-07 requires actual inference and tool computation plus valid linked CPU/GPU observations.

The repository's model registry declares `ollama_local/tinyllama-1b` and `vllm_local/Mistral-7B-Instruct-v0.3`, but registration is not installation. The exact existing model artifact/runtime on Grace must be inspected before choosing a command; no model should be downloaded merely to run the smoke check. Grace CPU package energy support is also not established by the x86-oriented RAPL reader names or by prior access reports; actual node APIs and physical scope must be recorded.

## Next actions and handoff

For one smallest controlled Grace validation, first record an explicit short session budget, account/allocation, actual assigned CPU/GPU resources and sharing state. In the allocation capture source commit, environment/package lock, hostname/boot ID, scheduler job/account, `nvidia-smi` GPU UUID/model/driver/CUDA/process state, CPU topology/allocation, readable powercap or operator-provided CPU-energy domains, and the installed local runtime/model list without downloading anything. Select one already-installed loopback runtime/model, start one server if needed, and issue one task response through the reviewed adapter. Run the merged data-analysis task through Aldric's reviewed executor when available, bracket it with the reviewed session provider, verify independently, finalize one ledger attempt and retain raw samples plus exported records. Compare one short repeatable no-op/control workload with collection disabled/enabled only for overhead; do not start ED-09.

Before executing, the exact commands must be adapted to Grace's scheduler account/partition and the actually installed runtime. Required evidence includes command transcript, source/runtime/model/tokenizer hashes, request/response metadata, actual device residency, raw CPU/GPU samples and units, acquisition/goal/session times, domain manifest/overlap, duplicate/refresh coverage, sharing/isolation, overhead procedure, verifier result, ledger validation and artifact hashes. This one bounded run can address ED-02 live response, ED-05/AX3 capability evidence and ED-07 integrated live validation, but only if the missing reviewed executor/runtime/measurement dependencies are present on the tested revision.
