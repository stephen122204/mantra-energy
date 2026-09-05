# Diagnostic study data contract v0.1

Planning contract, 4 September 2026. Sidecar export design, not a live database migration. All timestamps below are monotonic nanoseconds within a recorded clock domain. Store wall-clock anchors separately. Retain original source values and units; normalize in derived exports with versioned conversions.

## Records and required links

| Record | Required fields / meaning |
|---|---|
| Session | `session_id`, reservation/allocation ID, host/device UUIDs, boot ID, clock domain/anchors, source revision, environment/model/tokenizer hashes, CPU allocation, GPU sharing state, power settings, collector config, start/end, termination reason |
| Energy domain | `domain_id`, session ID, sensor/source identifier, physical coverage, parent/inclusion relationships, unit, counter range, native refresh observations, precision/uncertainty evidence, access status; no ambiguous `total_energy` |
| Goal contract | `task_id`, `task_asset_sha256`, lineage/family, split, task inputs, verifier hash, expected-result asset, deadline, retry limit, permissible outputs and candidate eligibility rules |
| Goal execution | `goal_execution_id`, task ID, session ID, planned run ID, candidate/policy, admission/end markers, service deadline, terminal status, verifier outcome, attempt count, residual-work termination status |
| Attempt | `attempt_id`, goal execution ID, attempt number, start/end, terminal status/error, retry reason, outcome, observation completeness; retain failed/censored attempts |
| Span | `span_id`, attempt ID, kind (`model`, `tool`, `verify`, `wait`, `cleanup`), ready/start/end, worker/resource config, request ID, input/output artifact hashes, status and error |
| Dependency | parent/child span or request IDs, dependency type, evidence/source of independence; check cycles, missing parents and stable tool-result ordering |
| Model request | span/request ID, prompt/messages asset hash, model/tokenizer/runtime hashes, decoding settings/seed, request arrival and generation boundaries, actual prompt/completion tokens, generated output hash, prefix/cache observations when exposed |
| Tool request | span/request ID, tool implementation/version, input/data hash, configured and observed workers/threads, output hash plus semantic-equivalence rule, exit status, side effects/sandbox ID |
| Sensor read | `sample_id`, session/domain IDs, acquisition start/end, raw value/unit, source timestamp if available, status, quality flags, counter generation/reset ID; invalid values are null with a reason |
| Intervention/replay | reference trace ID/hash, candidate controls, eligibility, call/input/dependency checks, token/output divergence, fidelity status/reason, preparation protocol, starting-state record |
| Diagnostic decision | decision ID, task/trace ID, selector revision, development-data hash, allowed profiling budget, query IDs, feasibility/service constraints, predicted effects/uncertainty, recommendation or abstention, seal time/hash |
| Derived measurement | run/goal/session scope, domain ID or explicit nonoverlapping domain set, integration/counter method, start/end brackets, energy, measured coverage, uncertainty, valid/invalid status, analysis version |

Raw prompts/tool output can be stored as content-addressed compressed assets; hashes alone are insufficient for reproducible replay. Retain permitted source artifacts, licenses and a redaction manifest. Exclude private correspondence from public campaign artifacts.

## Outcome semantics

- `execution_status`: completed, crashed, timed_out, cancelled, incomplete/unknown. Completion is not correctness.
- `verifier_outcome`: pass, fail, unavailable/error. Persist verifier execution and version independently of the agent's self-report.
- `measurement_status`: valid, partial, invalid, unavailable. Unknown energy is never zero energy.
- `replay_fidelity`: valid under declared conditional contract, divergent, ineligible, unknown. This does not override live task outcomes.
- `planned_record_status`: planned until the runner writes an actual immutable execution record. Placeholder task IDs are not benchmark data.

Attempt windows need not cover retries' backoff or session idle time. Integrate the enclosing goal/session stream for totals; do not reconstruct total cost only by summing successful attempt rows. For concurrent goals, a shared domain's joules are counted once at session/batch level. Any per-goal allocation of that shared energy must be labeled an accounting convention.

## Objectives and estimands

For a prespecified task set and policy, report `sum(E_all_attempts_and_owned_waits) / N_verified`, completion rate and task latency. Count all submitted tasks in success-rate denominators. If energy is invalid for any tasks, disclose coverage and missingness by policy, and do not present the observed-subset ratio as the complete-campaign quantity. A missing-energy run is retained and any repeat receives a new linked run ID.

Conditional effect: paired total episode energy under candidate C minus C00, given the recorded logical trace and declared initial-state protocol. Live effect: paired policy comparison on the original goal contracts with newly produced model/tool results. Report these separately.

For deployment claims, also measure a sequence/batch through all owned work termination under a common workload/horizon contract. Include fixed-horizon observations if deferred cost is part of the mechanism. Experimental preparation, model loading and diagnostic profiling remain separate measured cost categories; none is silently free.

Retain domain-specific outcomes even if a measured-domain sum is reported. No extrapolation from CPU-package + GPU-board readings to whole-node, facility energy or carbon without the additional evidence.

## Integrity checks required in the runner

1. Every realized event joins to an existing session and goal/attempt; IDs remain stable across exports and restarts.
2. All planned runs have a terminal ledger status or explicit pending/interrupted state; every retry is a new linked record.
3. Goal endpoint snapshots precede expensive measurement teardown; delayed-teardown tests cannot change task boundaries.
4. Clock mappings, read intervals, counter wrap/reset, duplicate samples and gaps are explicit; do not interpolate across unexplained outages.
5. Domain totals contain no known overlap; any missing domain narrows the reported measurement scope.
6. Failure and timeout energy are retained; a zero-success ratio is undefined; verifier failure is not converted into measurement failure.
7. Conditional replay logs input/work mismatches; live policy execution uses its actual outputs rather than the frozen trace.
8. Held-out reference results are inaccessible to the selector; decision seals precede reference-result access. Development/task lineage splits are enforced by actual assets, not just filenames.
9. All profiling queries, environment calibration and initialization have ledger entries/cost records, including failed queries.
10. Native sensor rows are correlated observations. Statistical units and splits are tasks/sessions, not individual sensor reads.

