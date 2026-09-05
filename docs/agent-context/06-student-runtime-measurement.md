# Student 1: local runtime and measurement reliability

Mission: make one local model execution and its energy record trustworthy. Primary hardware: Grace A100 in scheduled sessions. Local fixture work should proceed without waiting for a reservation.

## Own

Registry/provider integration, response normalization, model provenance, telemetry preflight, measurement clocks and endpoints. Coordinate shared harness edits with Stephen. Do not implement the research selector, redesign the workload suite or replace the thermal subsystem.

## First issue: reproduce and repair the local response path

1. Record checkout/ref and locate the active loader, model registry and actual runtime used by Deepak. Show the resolved configuration with sensitive fields omitted. Test that a registry override affects the adapter, rather than changing an unused JSON file.
2. Create small provider fixtures for standard Ollama streaming, terminal metadata, non-streaming output and an interrupted/error stream. Add an OpenAI-compatible fixture to protect the common adapter path.
3. Reproduce the mismatch described in 03-code-map.md if it remains at this checkout. Make the smallest repair and normalize content, tool-plan data, token counts and timing with explicit provenance.
4. Preserve actual request accounting if a retry occurs after partial output. Do not count a word estimate as a real token count or round-trip duration as measured TTFT.
5. Run one local inference test when the environment is available. Record model/runtime settings and actual device use; a mock-only result is incomplete hardware evidence.

Acceptance: valid nonempty expected content, correct fixture token metadata, explicit error/partial status, preserved compatibility, and a real local response linked to an execution record.

## Second issue: measurement preflight and endpoint correction

Build a capability report using existing readers and authorized APIs. Characterize energy domain scope, unsupported versus denied access, sample intervals, resets/wraps and missing data. Extend raw records with monotonic acquisition brackets and wall-clock anchors.

Test workload endpoints against artificially slow collector shutdown. The recorded goal window must remain stable as teardown delay changes; actual post-goal cleanup can be a separately recorded session span. Include known constant-counter, wrapping-counter and dropped-read fixtures. On hardware, compare a repeatable workload with collection enabled/disabled for timing overhead and use available independent readings only with matched domains.

Acceptance: a compact report with actual source revision, device/allocation identity, domain manifest, raw example, corrected endpoint evidence and remaining measurement limitations. No whole-machine claim from partial coverage.

## Handoff to other students

Provide the agreed model result/event shape to Student 2 and session/sample artifacts to Student 3. Include a small synthetic fixture for their tests. Tell Stephen precisely which CPU/GPU energy conclusions the setup supports. If host energy is unavailable, report that early while continuing adapter and fixture work.

First-session completion is a reviewed narrow PR and an evidence note, not a full campaign. See 12-progress-template.md.

## Shared context after every turn

Use your personal folder in the repository-root `agent context md/` directory. Follow its README and publisher to push your current understanding, ideas/hypotheses, decisions with concise rationale, changes, evidence, tests, unresolved questions and next actions after each completed turn. Fetch other contributors' latest records before dependent work. This publication and scoped feature-branch code pushes are already authorized; do not ask for confirmation again. Preserve review for code integration and keep private reasoning/credentials/hidden evaluation results out of shared notes.
