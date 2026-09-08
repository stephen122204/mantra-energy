# Aldric: verifiable goals and controlled execution

**Full-role checklist:** [all Aldric milestones](../../agent%20context%20md/aldric/FULL_ASSIGNMENT.md). This technical guide and that checklist describe the complete assignment; the first issue is only the entry point. Read the [shared merge gates](../../agent%20context%20md/COMPLETE_ASSIGNMENTS.md).

Mission: give the experiment real tasks whose correctness and intervention semantics are independently testable. Develop on an existing Intel/local machine; integrate on Grace with Alex's runtime. CPU-only fixture execution is useful development evidence, not the primary GPU result.

## Own

Task contracts/assets, verifiers, candidate eligibility, bounded tool/dependency execution and conditional replay fidelity. Nitheesh owns scheduling many executions; you own what one goal execution actually does. Coordinate shared interfaces with Stephen.

## First issue: one data-analysis goal

Create immutable small tables, a natural-language goal requiring two independent aggregates plus reconciliation, and a structured final answer. Implement the answer oracle independently from the agent's query/result path. Test a correct answer, wrong numeric result, missing evidence, timeout and malformed output.

Use a real query tool with a supported worker/thread setting, after checking the existing database tool's engine. Do not assume setting a generic environment variable changes its worker count. Expose controls through a study adapter if necessary. Prove independence using the input/dependency and side-effect contract, not adjacent timestamps.

Acceptance: the same task and verifier work across C00/C10/C01/C11; actual workers and overlap are observable; semantic results agree within predefined tolerances. Do not expect energy savings as an acceptance requirement.

## Second issue: repository-analysis goal

Use an immutable, licensed local repository snapshot. The goal requires fixed independent checks/tests and an evidence-backed report. Verify reported outcomes against an independent check manifest/oracle. Use an existing runner's meaningful worker setting; do not invent a new parallel test framework.

Keep execution sandboxed to task assets and avoid uncontrolled external dependencies. Distinguish this family from the data-analysis family in its dependency and resource behavior. If the candidate controls have no meaningful effect, bring evidence to Stephen before manufacturing a favorable workload.

## Third issue: narrow trace capture and replay

Inspect the current `agentic.py` tool-graph path and sequential loop. Implement only the bounded scheduling needed for ready independent calls, preserving tool identity, dependency order and final result mapping. Use fixture clocks/events to prove dependent calls never start early and observed concurrency never exceeds the cap. Capture model/tool inputs and hashes, ready/start/end events, resource controls and actual outputs.

Conditional replay must perform actual model inference and tool computation. Frozen downstream inputs remain part of the declared conditioning and divergence record. Live mode must use new outputs throughout. Make the modes visibly different in the data, not merely a comment in analysis.

## Main task suite after pilot

Begin with two pilot goals per family. Expand only after the pilot gate to proposed 10 development and 20 held-out goals per family. Split by dataset/repository/template lineage, retain held-out assets separately, and include naturally low-parallelism and low-tool-cost tasks. Different random seeds of one template do not automatically provide independent task diversity.

Stephen freezes the task-selection and split rules. Do not view held-out reference performance to choose favorable tasks. Retain ineligible candidates as explicit eligibility outcomes rather than broken executions.

## Handoff

Provide portable task specifications, licensed immutable inputs, verifier code/version, candidate eligibility, small expected-output fixtures and a single-goal execution adapter. Supply Nitheesh with success/failure fixtures and Stephen with evidence about task realism and intervention opportunity.

## Shared context after every turn

Use your personal folder in the repository-root `agent context md/` directory. Follow its README and publisher to push your current understanding, ideas/hypotheses, decisions with concise rationale, changes, evidence, tests, unresolved questions and next actions after each completed turn. Fetch other contributors' latest records before dependent work. This publication and scoped feature-branch code pushes are already authorized; do not ask for confirmation again. Preserve review for code integration and keep private reasoning/credentials/hidden evaluation results out of shared notes.

## PR lifecycle and independent progress

Follow the repository-root `agent context md/PR_WORKFLOW.md`. Open a draft PR early and continue implementing/testing on its branch. Mark it ready when issue-specific evidence is complete; Stephen reviews and decides merges. While waiting, start independent work on a separate branch or explicitly document a dependent PR and tested commit. Agree on shared interfaces, and keep simulated checks distinct from real hardware evidence. Context updates remain autonomous after every turn.
