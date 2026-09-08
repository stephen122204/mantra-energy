# Nitheesh: campaign execution and reproducibility

Mission: turn validated single-goal executions into a complete, auditable experiment. Develop the ledger/validation against synthetic fixtures locally. Use Grace only after the runtime and task interfaces are ready.

## Own

Manifest resolution, planned-to-realized run ledger, blocked randomization, resumable execution, data-quality validation and portable exports. Stephen owns the diagnostic decision rule and statistical conclusions; Aldric owns task execution. Do not start a second hardware campaign while integration is unfinished.

## First issue: build the ledger around fixture execution

Read `starter/make_run_plan.py`, `campaign.json` and `data-contract.md`. The generator is existing planning code. Add an execution layer in the agreed study namespace, not hidden execution side effects inside the planner.

For every planned slot, record pending/running/terminal state, actual candidate, source/task/model/verifier hashes, session and attempt links, execution/verifier/measurement status and artifact locations. A failed or interrupted run is retained; a repeat gets a new linked execution ID. Resume must not silently overwrite completed observations or execute duplicate jobs.

Acceptance: a tiny fixture schedule survives deliberate interruption, restart, model failure, verifier failure and missing telemetry; every realized record has valid links and every plan entry has a disposition. Export contains no fabricated hardware identity or zero-filled missing energy.

## Second issue: candidate blocks and data integrity

Randomize within the declared paired/session blocks and retain the seed and actual order. Use the same resources and preparation protocol across candidates. Record actual sessions; a planning `session_slot` is not a reservation. Wait for owned work termination before transitioning between measured goals.

Validate task assets and hashes, dependency/fidelity flags, clock domains, sensor gaps, domain overlap and runtime settings. Reject invalid analysis inputs with reasons while preserving raw artifacts. Keep a single writer per execution store or use a tested concurrency mechanism; do not have every worker append to one uncoordinated SQLite file.

## Third issue: selector boundary

Accept Stephen's frozen selector through the shared interface. Limit its queries and information to the allowed profiling budget. Store every query and its cost, including failures. Seal each recommendation before loading independent reference outcomes. Implement a test that fails if reference results leak through the supplied selector interface. CSV order alone does not meet this requirement.

Expose reference evaluation separately from selection. Live policy slots use the actual frozen policy's result, never an ex-post best candidate chosen from the test outcomes.

## Handoff and reporting

Produce a manifest, run ledger, validation summary, small reproducible export and commands for regenerating derived tables from immutable inputs. Report collection coverage by policy, failures and elapsed/reservation cost. Leave statistical interpretation to the agreed analysis plan.

After the primary finding and pipeline are stable, you may own a bounded second-platform reproduction if Stephen assigns it. Its purpose must be a concrete transfer claim, with runtime/hardware differences documented.

## Shared context after every turn

Use your personal folder in the repository-root `agent context md/` directory. Follow its README and publisher to push your current understanding, ideas/hypotheses, decisions with concise rationale, changes, evidence, tests, unresolved questions and next actions after each completed turn. Fetch other contributors' latest records before dependent work. This publication and scoped feature-branch code pushes are already authorized; do not ask for confirmation again. Preserve review for code integration and keep private reasoning/credentials/hidden evaluation results out of shared notes.

## PR lifecycle and independent progress

Follow the repository-root `agent context md/PR_WORKFLOW.md`. Open a draft PR early and continue implementing/testing on its branch. Mark it ready when issue-specific evidence is complete; Stephen reviews and decides merges. While waiting, start independent work on a separate branch or explicitly document a dependent PR and tested commit. Agree on shared interfaces, and keep simulated checks distinct from real hardware evidence. Context updates remain autonomous after every turn.
