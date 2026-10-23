**Current handoff (20 September 2026):** Read [CURRENT_HANDOFF](../CURRENT_HANDOFF.md) and [BATCH_ACCEPTANCE](../BATCH_ACCEPTANCE.md) first. They supersede older first-task, platform and run-count directions. Keep this checklist for full-role coverage; reuse completed work and identify remaining evidence.

# Nitheesh: complete assignment

**This is the full role for humans and agents, not just the first issue.** Read it together with your [human guide](HUMAN_START_HERE.md), [technical specification](../../agent-context/08-nitheesh-campaign-reproducibility.md) and [team dependency/merge plan](../COMPLETE_ASSIGNMENTS.md).

Your responsibility runs through: **resumable ledger → randomized bounded runner and data validation → integrated Grace pilot → selector budget/information boundary → approved evaluation and reproducible exports**.

## Execution expectation: finish the whole implementation

Work through ALL milestones continuously, including implementation, debugging, meaningful tests, cross-component integration and reproducible handoff. Do not return after a milestone asking what to do next. Status/context publication and separate PRs are checkpoints, not stop signals. Build later-stage software using agreed fixtures where necessary; keep actual physical campaigns and scientific decisions within their stated dependencies. Follow [the standing execution instruction](../COMPLETE_ASSIGNMENTS.md#standing-instruction-execute-the-whole-role-to-completion). When one item is externally blocked, continue another; escalate only the specific dependency, not the whole assignment.

## Milestones, evidence and dependencies

| Milestone | Deliverable | Required implementation | Acceptance evidence | Dependency / handoff |
|---|---|---|---|---|
| NI1 · ED-04 | Resumable execution ledger | Separate execution from planning. Record every planned slot, realized attempt, status, identity/hash, actual candidate and artifact link. Keep retries as new linked executions. | Interruption/restart, model failure, verifier failure, missing telemetry and duplicate prevention. No overwritten observations, fabricated devices or zero-filled missing energy. | Start with fixtures using Stephen contract. Real task/model/collector are not prerequisites for ledger tests. |
| NI2 · ED-04/09, separate PR | Bounded scheduling and data integrity | Invoke Aldric executor; apply declared seeded ordering within paired/session blocks; preserve actual order, resource/preparation settings and every disposition. Validate inputs, clocks, gaps, domains and fidelity; durable raw/derived exports. | Tiny randomized schedules reproduce their order, failures remain accounted for, invalid records are flagged with reasons, and export links resolve. One writer or tested store concurrency. Owned work terminates before next measured goal. | Can develop with fixtures alongside others. Stephen freezes protocol; no concurrent independent goals in the initial energy study. |
| NI3 · ED-07/09 | Local integration and real bounded pilot | Connect the actual components, then execute the approved Grace plan. First one measured/verified goal, then four pilot goals across eligible settings/repetitions within the assigned budget. | Fresh-checkout integrated examples including failures; complete planned-to-realized accounting, verified artifacts, raw readings/coverage, resume behavior and actual session/time costs. Up to 48 pilot runs is a proposal, not authorization. | Real runs require Alex runtime/collector, Aldric executor/tasks and Stephen acceptance. Four-task pilot additionally needs AL3. |
| NI4 · supports ED-10/11, separate PR | Selector budget and hidden-reference boundary | Consume Stephen selector through a restricted interface. Track all profiling queries and time/energy costs, including failures. Seal recommendation/abstention before reference outcomes are exposed; separate reference evaluation. | Access test rejects hidden-reference leakage; budget exhaustion/failure tests; actual policy choice used in live evaluation, never post-hoc best setting. CSV order is not isolation. | Use dummy selectors to build the interface early; final semantics depend on Stephen method and freeze. |
| NI5 · after pilot approval | Main evaluation, reproducible export and campaign evidence | Execute only approved frozen plans; preserve versions/raw data, provide validation summaries and regenerable derived tables, failure/coverage/cost reporting and factual methods evidence. | Every slot has a disposition; outputs regenerate from retained inputs; profiling and failures remain included; invalid data is preserved and flagged. Document repairs and their impact on existing observations. | Needs approved expanded tasks, validated measurements and Stephen frozen method/analysis/budget. A second platform is only a later explicit assignment. |

## What the human and agent each do

Inspect one success, incorrect result, interruption/resume and missing-measurement example; confirm records are not lost or duplicated; coordinate budget/storage and verify a sample export against its raw evidence. Your agent builds and tests ledger, scheduling, validation, selector boundary and reproducible exports.

Develop on your existing computer, including Windows for portable software work. Primary measurements run inside the assigned Grace Linux compute allocation: one A100 runs the selected model; host CPUs run tools/verifiers and supporting code. The 16-CPU/64GB target is proposed, not a booking. Alex has reported RAPL reads without sudo; validate the actual session, device/domain coverage and isolation. Local or simulated tests are not GPU energy evidence. No new hardware purchase is assigned.

## Progress and completion

These milestones are assigned scope. Continue the next ready software milestone in a separate PR without waiting for another assignment. Keep blocked work visible and work on an independent milestone. Hardware requires an individually authorized account, assigned allocation/session and budget. Expansion beyond the pilot requires Stephen’s scientific gate; do not treat elapsed time or a planning manifest as approval.

At the next session, produce a status table for EVERY milestone ID above: not started / in progress / fixture-tested / hardware-tested / accepted / blocked / conditional. Include PR and tested commit, evidence, exact missing dependency, next action and owner. Explain the whole role back to the human. Update this table in your own published turn context as evidence changes; do not edit immutable historical notes. “First PR merged” never means “all assigned work complete.”

The runner survives failures, drives the integrated experiment, enforces selection/evaluation boundaries and delivers complete reproducible records for the approved campaign. A fixture ledger or generated run plan alone does not finish the role.

You do not implement Aldric single-goal tool executor, Alex model/collector internals, or Stephen scientific decision rule/statistical conclusions. No automatic second-platform campaign.

Fix defects in your component discovered during shared integration. Keep changes to frozen definitions/versioned artifacts explicit and coordinate their evidence impact with Stephen. Supply factual methods and reproducibility details; software completion does not establish novelty or acceptance.

## Timing

Follow the engineering schedule and approved session budgets. Research and submission planning remain private.
