# Shared interfaces and data contract

**Implemented contract (ED-01, v0.1):** `studies/energy_diagnosis/contracts.py` defines the shared records (`TaskSpec`, `ExecutionSetting`, `ModelResponse`, `SpanEvent`, `SensorSample`, `MeasurementRecord`, `VerifierResult`, `ExecutionRecord`) with JSON round-trip, validation and worked examples in `studies/energy_diagnosis/fixtures/contract_examples/`; `tests/test_study_contracts.py` runs in CI. Produce and consume those types; propose changes by PR against that module, not by local copies. The prose below remains the design rationale and the record-semantics reference is [starter/data-contract.md](starter/data-contract.md). The callable shapes further down are still illustrative.

## Component handoffs

| Producer → consumer | Contract | Required evidence |
|---|---|---|
| Workloads → runner | Task specification: immutable inputs, lineage/split, verifier version, deadline/retry policy, candidate eligibility | Correct and deliberately wrong fixture outputs |
| Runtime → executor | Model response: text/structured plan, actual request ID, timing, token counts with provenance, terminal error/status | Provider fixture and one real local response |
| Executor → collector/runner | Linked goal/attempt/span events with ready/start/end markers, dependencies, resource settings and artifact hashes | Dependency checks, balanced terminal events |
| Collector → runner | Session/domain metadata, raw samples, validity flags and bounded endpoint observations | Counter wrap/reset, gaps, invalid reads and teardown checks |
| Runner → analysis | Immutable execution ledger plus normalized domain measurements and verifier outcomes | Restart integrity, no missing planned-run dispositions |
| Stephen's selector → runner | Next profiling candidate or sealed recommendation/abstention, budget and decision provenance | Candidate eligibility and information-access tests |

## Suggested callable shapes

These names are illustrative and require mapping to the actual repository:

```text
preflight(environment) -> CapabilityReport
start_session(metadata) -> SessionHandle
execute_goal(task_spec, candidate, mode, event_sink) -> ExecutionOutcome
verify(task_spec, output_artifact) -> VerifierOutcome
snapshot_endpoint(session, marker) -> EndpointObservation
finish_session(session) -> SessionArtifacts
select_next(task_features, allowed_profile_results, remaining_budget) -> QueryOrDecision
validate_run(run_record, artifacts) -> ValidationReport
```

The runner must emit an attempted execution record even if the model, collector or verifier fails. Verifier outcome is not copied from an agent's self-assessed success. `finish_session` must not redefine an already recorded goal endpoint.

## Identity and clocks

Minimum links: session → goal execution → attempt → span/request. Include planned-run ID, source/environment/model/verifier hashes and actual allocation/device IDs. Store event timestamps in monotonic nanoseconds with clock domain and boot/session identity. Wall-clock anchors support human correlation; clocks on distinct hosts cannot be directly subtracted.

Sensor records need acquisition start/end, raw value and unit, sensor/domain ID, source timestamp if exposed, and status/quality flags. Polling rate is not native sensor refresh rate. Keep counter resets/wraps explicit; do not interpolate across unexplained outages.

## Energy and outcome semantics

- An energy-domain manifest states what each counter includes and its parent/overlap relationships. GPU-board and CPU-package energy are distinct measured scopes; neither means wall energy.
- End-to-end goal measurement includes verification and owned work until termination under the declared protocol. Define inference-only/attempt-only windows separately where useful.
- Continuous session energy captures waits and work between spans. Summing successful step rows is not an adequate total.
- Failed, timed-out, cancelled and partial runs remain in the ledger. Null energy with a reason is different from measured zero. Store execution status, verifier outcome and measurement validity separately.
- Concurrent spans may overlap one sensor window; count physical energy once at the enclosing goal/session level. Any per-span allocation is an explicitly named accounting convention.
- Retain raw data; derived energy carries its method, version, boundaries, coverage and uncertainty evidence.

## Replay fidelity

Record source trace, immutable assets, actual model/tool invocations, dependency checks, output/token divergence and preparation state. A fixture replay can use stubs for software tests, but those runs must be marked simulated and excluded from hardware energy conclusions. Frozen downstream inputs are permitted only in the declared conditional experiment, never silently in live evaluation.

## Storage and held-out boundaries

Use portable relative paths or approved artifact identifiers. Hash-only exports are insufficient to replay if the permitted original assets are absent. Keep large outputs in content-addressed storage with backup and licenses recorded.

Expose a restricted selector input object rather than the full campaign database. Hidden reference results should live in a separate location/process permission boundary accessible to the evaluator. The selector's recommendation is sealed before reference outcomes are exposed. CSV row order is not an information barrier. A small access test should demonstrate that a selector cannot read the held-out reference through its normal interface.
