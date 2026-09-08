# Alex: complete assignment

**This is the full role for humans and agents, not just the first issue.** Read it together with your [human guide](HUMAN_START_HERE.md), [technical specification](../../docs/agent-context/06-alex-runtime-measurement.md) and [team dependency/merge plan](../COMPLETE_ASSIGNMENTS.md).

Your responsibility runs through: **model adapter → trustworthy measurement session → real Grace validation → integration and campaign measurement support → reproducible measurement evidence**.

## Execution expectation: finish the whole implementation

Work through ALL milestones continuously, including implementation, debugging, meaningful tests, cross-component integration and reproducible handoff. Do not return after a milestone asking what to do next. Status/context publication and separate PRs are checkpoints, not stop signals. Build later-stage software using agreed fixtures where necessary; keep actual physical campaigns and scientific decisions within their stated dependencies. Follow [the standing execution instruction](../COMPLETE_ASSIGNMENTS.md#standing-instruction-execute-the-whole-role-to-completion). When one item is externally blocked, continue another; escalate only the specific dependency, not the whole assignment.

## Milestones, evidence and dependencies

| Milestone | Deliverable | Required implementation | Acceptance evidence | Dependency / handoff |
|---|---|---|---|---|
| AX1 · ED-02 | Model adapter and configuration | Resolve the active registry/provider; normalize real content, tool-plan data, request IDs, timings, tokens and partial/retry outcomes. Preserve existing provider compatibility. | Streaming/non-streaming, terminal metadata, malformed/interrupted responses and override fixtures; one real response for full ED-02 completion. | Start locally now; Stephen supplies shared types. Aldric consumes model outcomes. |
| AX2 · ED-05 | Measurement session and endpoint correctness | Reuse existing collectors/readers; provide session start, goal endpoints and finish; retain raw samples, acquisition brackets, domain/device identity and validity. | Constant/wrapping/reset counters, dropped reads, unsupported/denied values and delayed shutdown. Shutdown must not extend the goal boundary. Missing is not zero. | Develop with sensor fixtures alongside AX1. Nitheesh consumes session/sample artifacts. |
| AX3 · ED-05/12 | Early Grace capability and real-model check | Use an assigned account and bounded session to establish model/runtime operation, actual assigned GPU, readable CPU packages/GPU domains, tool compatibility and isolation. | Source/runtime/configuration record, real output and raw observations; characterize refresh/coverage and collector timing overhead. Team-confirmed no-sudo RAPL access is not a substitute for this evidence. | Can happen before the full runner is ready. Stephen coordinates budget; advise Aldric on tool installation, not task ownership. |
| AX4 · ED-07/09 | Integrated goal and pilot measurement support | Connect to the shared local integration path and then real Grace execution. Fix adapter/collector defects; inspect physical windows and coverage during the bounded pilot. | Linked real response, goal endpoints, raw CPU/GPU records and failure/missingness cases on the integrated revision; no whole-machine claim from partial domains. | Real integrated goal needs Aldric executor and Nitheesh ledger. Pilot additionally needs four task assets. |
| AX5 · after pilot approval | Campaign and paper measurement evidence | Maintain the frozen runtime/collector; diagnose invalid sessions, assess which results a repair invalidates, and supply reproducible environment and measurement-method evidence. | Document versions, commands, domain scope, isolation, overhead, coverage and limitations; reruns are targeted and budgeted. | Stephen authorizes campaign/freeze changes; Nitheesh owns runs/exports. Supply factual methods evidence to Stephen. |

## What the human and agent each do

Inspect a real model answer and raw sensor examples, understand which physical domains are covered, coordinate your authorized session, and check measurement boundaries and isolation. Your agent implements adapters, collectors, focused tests, reproducible examples and PR/context updates.

Develop on your existing computer, including Windows for portable software work. Primary measurements run inside the assigned Grace Linux compute allocation: one A100 runs the selected model; host CPUs run tools/verifiers and supporting code. The 16-CPU/64GB target is proposed, not a booking. Alex has reported RAPL reads without sudo; validate the actual session, device/domain coverage and isolation. Local or simulated tests are not GPU energy evidence. No new hardware purchase is assigned.

## Progress and completion

These milestones are assigned scope. Continue the next ready software milestone in a separate PR without waiting for another assignment. Keep blocked work visible and work on an independent milestone. Hardware requires an individually authorized account, assigned allocation/session and budget. Expansion beyond the pilot requires Stephen’s scientific gate; do not treat elapsed time or a planning manifest as approval.

At the next session, produce a status table for EVERY milestone ID above: not started / in progress / fixture-tested / hardware-tested / accepted / blocked / conditional. Include PR and tested commit, evidence, exact missing dependency, next action and owner. Explain the whole role back to the human. Update this table in your own published turn context as evidence changes; do not edit immutable historical notes. “First PR merged” never means “all assigned work complete.”

The adapter and collector work through the integrated experiment; real Grace evidence establishes what is measured; measurement failures are represented honestly; and the approved campaign has reproducible runtime/measurement documentation. Parser tests or a capability report alone do not finish this role.

You do not own the task collection, tool scheduler, experiment ledger, decision method, or a new thermal subsystem.

Fix defects in your component discovered during shared integration. Keep changes to frozen definitions/versioned artifacts explicit and coordinate their evidence impact with Stephen. Supply factual methods and reproducibility details; software completion does not establish novelty or acceptance.

## Timing

Working targets: first component PRs September 10; integrated measured goal September 11–12; usable pilot September 15; research/development gate September 18; core evaluation data September 25; September 26–October 1 gap/retest buffer. Draft while collecting data. The project targets October 2 abstract and October 9 paper submission; Stephen owns submission. These are planning targets, not permission to skip checks or a claim that the full role takes 5–8 hours. See [Fall timeline](../FALL_TIMELINE.md).
