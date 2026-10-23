**Current implementation handoff:** Read [the 20 September team handoff](CURRENT_HANDOFF.md) first. It updates the active platform, named responsibilities and acceptance checks; historical first-task instructions and proposed run counts are not current launch instructions.

# Complete team assignments and merge gates

**Before starting or resuming:** follow the [required context-loading checklist](STARTUP_CHECKLIST.md). Read the complete current shared and named context; demonstrate all-role understanding, then continue implementation in the same session. This applies even with an old kickoff attachment or an agent that does not automatically load AGENTS.md.

Updated 7 September 2026. **The first issue is the entry point, not the full assignment.** Humans and agents must read their complete role below. Ready software milestones within these roles are already assigned; continue them in separate PRs without waiting for another assignment. Hardware/session budgets, reviewed integration, evaluation freezes and the decision to expand after the pilot remain explicit gates. This replaces earlier kickoff language that made all later work conditional on a new assignment.

## Standing instruction: execute the whole role to completion

Stephen explicitly assigns the WHOLE role, not one milestone per human message. Inspect current progress, then implement, test, debug and integrate every assigned component that can be completed with available dependencies. A status report is a checkpoint during work, not the deliverable by itself.

- Do not stop after the first PR, a passing test suite, a context update, a plan, or the current milestone. Do not ask whether to continue, offer to do the next item, or wait for a new assignment for work already in the full-role checklist.
- Continue the implementation → focused tests → inspect actual artifacts → repair → cross-component checks cycle until acceptance evidence is complete. Push scoped commits, keep PRs reviewable and publish concise evidence/context; then move directly to the next item.
- Keep all milestones visible, but spend the session executing them rather than repeatedly restating the plan. A long task is not itself a blocker. Debug failed tests and integration errors within your ownership instead of returning them as a handoff for Stephen to solve.
- While a PR is under review, continue independent work or a clearly documented dependent branch. Test against the named prerequisite revision; never call an unmerged dependency integrated. Separate PRs are review boundaries, not reasons to pause implementation. Stephen still decides merges.
- Build the full software path now, including later campaign, replay, validation and evaluation-interface code assigned to your role. Use declared fixtures/dummy policies while real dependencies are unavailable. The pilot decision limits large physical campaigns and scientific freezes; it is not a reason to postpone independent software implementation or tests. Do not claim fixture results are real measurements.
- Once an individually authorized hardware session, allocation and budget are actually supplied, execute the assigned bounded checks without requesting the same permission again. Missing credentials, a not-yet-defined scientific decision or an exhausted budget cannot be invented away. Record the precise missing dependency and continue every independent item.
- Stop only when the complete currently authorized role has its required evidence and handoff, the human explicitly stops/reassigns it, or all remaining work is blocked by specific external dependencies and no useful independent work remains. A completion claim lists each milestone's evidence and outstanding conditional campaign work separately.

If the agent runtime itself ends a session, retain a resumable record with exact branch/commit, completed evidence, remaining milestones and the next executable action. On resumption, continue from it rather than restarting or asking for a new assignment. These instructions do not create an always-running process or extend a model provider's execution limits.

## Read your full role

| Person | Full responsibility | Complete checklist for human and agent |
|---|---|---|
| Alex | Model adapter; measurement sessions; real Grace capability/endpoint/overhead validation; integration repairs; campaign measurement and reproducibility evidence | [AX1–AX5](alex/FULL_ASSIGNMENT.md), [human guide](alex/HUMAN_START_HERE.md), [agent prompt](alex/alex.txt) |
| Aldric | Verifiable tasks; single-goal executor and real controls; four pilot tasks; traces and physical replay; Grace integration; conditional expanded task suite and workload evidence | [AL1–AL6](aldric/FULL_ASSIGNMENT.md), [human guide](aldric/HUMAN_START_HERE.md), [agent prompt](aldric/aldric.txt) |
| Nitheesh | Resumable ledger; bounded randomized scheduling and data validation; integrated pilot; selector budget/reference isolation; approved evaluation and reproducible exports | [NI1–NI5](nitheesh/FULL_ASSIGNMENT.md), [human guide](nitheesh/HUMAN_START_HERE.md), [agent prompt](nitheesh/nitheesh.txt) |
| Stephen | Concrete common contracts; local integration acceptance; reviews; hardware coordination; method/baselines; pilot decision; evaluation freeze; analysis and manuscript | Shared coordination milestones below; [technical role](../agent-context/09-stephen-method-integration.md) |

Stephen's private human guide stays outside this repository. This document records only team-facing ownership and interfaces. Existing ALBEM, platform-port or other advisor assignments are separate commitments; coordinate bandwidth rather than silently replacing them.

## Mandatory acknowledgment and ongoing progress

At the next session, each agent reads the current full role and reports EVERY milestone ID with: status, PR/tested commit, evidence, missing dependency with owner, and next action. Use not started / in progress / fixture-tested / hardware-tested / accepted / blocked / conditional, and retain the exact evidence level. Explain the whole role to the human in a short paragraph. Do not claim an issue is accepted without review evidence.

Publish this full-scope status in that person's next immutable turn note and keep it current in subsequent notes. A merged first PR does not justify “all done.” If a milestone is blocked, name the missing artifact and continue a ready independent milestone. These files do not automatically update an already-running remote chat: that agent must fetch/read them. Stephen can verify uptake from each person's published acknowledgment and evidence rather than assuming delivery equals understanding.

As of this audit, the first Aldric task/checker is merged (PR #16); other shared study runtime/campaign implementation was not present in the inspected integration tree. Alex/Nitheesh had no published work-turn records. This is a dated repository observation, not proof of no local progress. Inspect current code/PRs before assigning status.

## Merge and verification sequence

### G0 — Stephen: concrete common interfaces (ED-01)

Implement the smallest shared callable/types and example records for task/candidate, normalized model response, linked events, verifier outcome, collector session/artifacts and execution ledger. The interface document currently describes proposed shapes; do not mistake it for an installed API. Alex, Aldric and Nitheesh exercise producer/consumer examples before dependent code spreads. Stephen owns schema decisions and shared Windows bootstrap maintenance. Fixtures can proceed while this PR is reviewed.

### G1 — three parallel component streams

- Alex AX1/AX2: provider and collector PRs with deterministic success/failure/endpoint tests. AX3 early assigned Grace smoke check runs alongside development, not after every component is finished.
- Aldric AL1/AL2/AL3: existing verifier, executor/real controls, and pilot assets in bounded PRs. Aldric selects/adapts tools with meaningful worker settings; Alex advises on runtime/installation compatibility. AL4 trace/replay can follow the executor and is required before replay-based claims.
- Nitheesh NI1/NI2: ledger, ordering, validation and exports using the agreed fixtures; does not implement a second task executor. NI4 can use a dummy selector while Stephen specifies the method.

Merge ready independent component PRs in any order after their contract dependencies. If hardware acceptance is pending, explicitly split a completed software milestone for review; do not close the hardware requirement or silently lower acceptance. Keep dependent PR bases/commits explicit, test on branches, and do not force-push shared history.

### G2 — Stephen coordinates; all owners repair: local integration (part of ED-07)

Provide one reproducible command from a fresh checkout joining task → actual model/tool adapter/executor → collector boundary → independent verifier → durable ledger/artifacts. Use the real component implementations together; external model/sensor fixtures may substitute only in clearly simulated checks. Tools must actually compute. The full Grace path later uses actual inference and sensors.

Before the main integrated Grace test, demonstrate:

1. Correct output and complete linked artifacts.
2. Wrong output recorded as incorrect, not successful.
3. Model/tool failure and timeout with owned work terminated and failure retained.
4. Missing sensor data recorded as null with a reason.
5. Interruption/resume without losing observations or duplicate execution.
6. Real control behavior and equivalent answers across eligible settings.
7. Stable recorded goal endpoints despite delayed collector teardown.

The author repairs defects in their own component; Stephen owns cross-component glue/decisions. Three independently passing test suites do not pass this gate. Fresh-checkout setup must work on the declared development platforms; simulated Windows behavior must not be described as native Windows validation.

### G3 — Alex + Stephen, with both other owners: actual Grace goal (ED-07)

Use an individually authorized allocation/session and budget. First run one task through actual inference, tool computation, verification, measurements and ledger. Confirm runtime/device allocation, actual CPU/GPU energy domains, raw data, clocks/endpoints, isolation and durable artifacts. Then compare eligible controls on that task. Alex validates physical measurement/model behavior; Aldric validates useful work and real controls; Nitheesh validates accounting/exports; Stephen decides acceptance. No-sudo RAPL readability has been reported by Alex; session coverage/isolation and overhead still need evidence.

### G4 — Nitheesh coordinates execution; all verify: bounded pilot (ED-09)

Requires G3 and AL3's four goals. Proposed initial design: two goals per family × four candidate settings × three repetitions, up to 48 executions before eligibility/budget adjustments. Retain failures, missing measurements and actual run order. This count is a plan, not a booking or automatic campaign authorization. Alex checks domains/overhead; Aldric checks correctness/control semantics and realism; Nitheesh checks complete dispositions and exports; Stephen checks record quality and integration.

### G5 — Stephen: supplied policy integration (ED-10)

Build and validate the assigned software components using the shared contracts. Research planning is maintained privately.

### G6 — frozen evaluation and research handoff (ED-11)

Stephen freezes task-selection/lineage splits, model/runtime, candidates, measurement boundaries, preparation, policies, service constraints and analysis. Nitheesh NI4 proves budget and hidden-reference separation before held-out evaluation. Aldric AL6 expands only after approval (proposed main suite: 10 development + 20 held-out goals per family). Alex AX5 preserves/validates the measurement environment. Nitheesh NI5 executes only the approved plan and exports reproducible evidence. Stephen checks the completeness and validity of the exported records with evidence from each owner. Changes after freeze need a version and impact assessment.

## Whole-role completion versus first-week work

Each role ends with its checklist satisfied for the approved study scope, tested integration and reproducible handoff—not a first PR, one CSV, a parser repair or a fixture ledger. Campaign support means bounded repairs and evidence work, not indefinite unassigned platform expansion. Hardware validity, engineering completeness and scientific significance remain separate judgments.

Follow the engineering schedule and approved session budgets. Research and submission planning remain private.

## What a PR must show

Name the milestone and its bounded deliverable; give prerequisite PRs and the exact tested integration revision; provide reproducible commands, result artifacts, failure cases and producer/consumer compatibility evidence; state hardware checks still pending and all remaining role milestones. Mark work draft until its stated acceptance criteria are satisfied. Stephen decides merges. Update the full-role status after merge and continue the next ready item.

