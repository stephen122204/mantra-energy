# Aldric: complete assignment

**This is the full role for humans and agents, not just the first issue.** Read it together with your [human guide](HUMAN_START_HERE.md), [technical specification](../../docs/agent-context/07-aldric-workloads-verifiers.md) and [team dependency/merge plan](../COMPLETE_ASSIGNMENTS.md).

Your responsibility runs through: **first task/checker → single-goal execution and four controls → four pilot tasks → trace/replay fidelity → Grace integration → conditional expanded task suite and workload evidence**.

## Milestones, evidence and dependencies

| Milestone | Deliverable | Required implementation | Acceptance evidence | Dependency / handoff |
|---|---|---|---|---|
| AL1 · ED-03 | First fixed data task and independent verifier | Immutable licensed data, natural-language goal, structured answer, independently recomputed reference, versioned assets and meaningful control eligibility. | Correct/wrong numeric/malformed/missing-evidence and invalid-input checks; hashes establish asset identity, not answer correctness. | Initial fixture merged in PR #16 as of 7 September. Inspect current code; do not rebuild it or call the whole role finished. |
| AL2 · ED-06 | Single-goal executor and real execution controls | Own execution of one goal, using Alex model interface. Use meaningful existing tools; implement 1/2 concurrent ready calls and 1/4 workers per tool, dependency order, result mapping and termination. | Actual tool computations; observable worker/concurrency effects; dependencies never start early, cap never exceeded, correct results under each eligible setting, failure/timeout cleanup. A generic environment variable is not proof. | Needs Stephen contract for integration. Start local tool/fixture work now. You select/adapt tools; Alex advises Grace compatibility. Nitheesh calls your executor. |
| AL3 · ED-08 | Second family and four pilot goals | Two local data-analysis goals and two repository-analysis goals total, with immutable licensed inputs, independent checks, lineage metadata, eligibility and representative useful work. | Check representative expected answers yourself; wrong answers fail; show different dependency/resource behavior. Tiny fixtures alone do not establish measurable or representative energy work. Report ineffective controls rather than manufacturing favorable tasks. | Can proceed alongside AL2 after task contract is stable. Pilot needs all four goals; first integrated goal only needs one. |
| AL4 · ED-06, separate bounded PR | Trace capture and conditional replay | Record actual model/tool inputs, hashes, readiness/start/end, dependencies, controls and outputs. Replay physically executes inference and tools; declare frozen downstream inputs and divergence. Live mode uses newly generated outputs throughout. | Fixture dependency/fidelity checks; unambiguous mode labels; real inference/tool evidence before any energy-replay claim. Saved output playback alone does not qualify. | Build after the executor. Does not block the first live integration smoke check; required before replay-based experiments/claims. |
| AL5 · ED-07/09 | Grace integration and pilot workload validation | Supply portable task specs, verifier versions, success/failure fixtures and the executor. Fix task/control defects in the integrated path and validate actual behavior on Grace. | Same useful goal correctly completed under eligible settings; real worker evidence, preserved failures and trace links on the tested revision. Energy savings are not component acceptance. | Real model uses Alex runtime; Nitheesh orchestrates executions. Participate in local integration first, then assigned Grace sessions. |
| AL6 · after pilot approval / ED-11 | Expanded task suite and evaluation support | Proposed 10 development + 20 held-out tasks per family: 60 total in the main suite. Build diverse lineage-separated assets only after Stephen approves expansion and freezes selection/split rules. Support campaign task failures and workload-method documentation. | Include naturally low-parallelism/low-tool-cost cases; distinct seeds are not automatically task diversity. Version task/verifier changes; never choose tasks using hidden reference performance. Supply reproducible task/checker evidence and limitations. | Conditional on pilot decision, frozen rules and available budget; not an initial-week commitment. Stephen owns scope/freeze/claims; Nitheesh runs the campaign. |

## What the human and agent each do

Check a small expected answer independently, make sure incorrect outputs fail, assess task realism/licensing and which operations are independent, and inspect evidence that controls really change execution. Your agent builds tasks, verifiers, executor, traces/replay, tests and scoped PRs.

Develop on your existing computer, including Windows for portable software work. Primary measurements run inside the assigned Grace Linux compute allocation: one A100 runs the selected model; host CPUs run tools/verifiers and supporting code. The 16-CPU/64GB target is proposed, not a booking. Alex has reported RAPL reads without sudo; validate the actual session, device/domain coverage and isolation. Local or simulated tests are not GPU energy evidence. No new hardware purchase is assigned.

## Progress and completion

These milestones are assigned scope. Continue the next ready software milestone in a separate PR without waiting for another assignment. Keep blocked work visible and work on an independent milestone. Hardware requires an individually authorized account, assigned allocation/session and budget. Expansion beyond the pilot requires Stephen’s scientific gate; do not treat elapsed time or a planning manifest as approval.

At the next session, produce a status table for EVERY milestone ID above: not started / in progress / fixture-tested / hardware-tested / accepted / blocked / conditional. Include PR and tested commit, evidence, exact missing dependency, next action and owner. Explain the whole role back to the human. Update this table in your own published turn context as evidence changes; do not edit immutable historical notes. “First PR merged” never means “all assigned work complete.”

Tasks, verifiers, execution controls and replay support satisfy their evidence requirements and work in the shared experiment; the approved task suite and workload evidence are handed off. The small sales CSV and checker finish only the first milestone.

You do not own CPU/GPU collectors, scheduling the whole experiment, the diagnostic selector, model training, or an ALEMS Windows/Android port. Separate ALBEM/port commitments with Deepak are not replaced by this assignment.

Fix defects in your component discovered during shared integration. Keep changes to frozen definitions/versioned artifacts explicit and coordinate their evidence impact with Stephen. Supply factual methods and reproducibility details; software completion does not establish novelty or acceptance.

## Timing

Follow the engineering schedule and approved session budgets. Research and submission planning remain private.
