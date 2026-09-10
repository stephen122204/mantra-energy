# Required startup: load the complete current context

**Publication boundary (Stephen, 9 September 2026):** GitHub context is implementation-only: concrete build requirements, interfaces, code decisions with concise rationale, debugging hypotheses, tests, hardware setup, dependencies and handoffs. Keep research ideas, proposed scientific contributions, literature/novelty analysis, mathematical research proposals and venue strategy in private local notes or the conversation, outside Git-tracked paths. Do not copy that material into commits, PRs, issues, context records or attachments. Research-only turns require no repository publication. For mixed turns, publish only the implementation portion. This supersedes earlier instructions to publish all ideas or every turn; it does not reduce the complete assigned coding scope. Before any push, inspect the staged diff and publication text for this boundary.

Use this checklist when starting OR resuming an agent for this study, including when an old email attachment, old issue prompt or older branch started the session. Read the current maintained assignment from `origin/research/energy-diagnosis`; do not rely only on memory, an old prompt, an issue title or a latest-note summary. These requirements apply even if your model/tool does not automatically load AGENTS.md.

## 1. Inspect and refresh without losing work

Confirm the person's name, private team repository remote, branch, source commit, working changes and any existing PRs. Fetch integration. Preserve uncommitted work and do not reset a feature branch merely to read new instructions. Use `git show 'origin/research/energy-diagnosis:path/to/file'` to read current maintained context from the fetched ref if your worktree is older. Record the fetched integration commit separately from the code commit being tested. Update/merge branch code only through the normal reviewed dependency workflow.

Never use the separate public upstream repository as the study integration target. Do not infer credentials or GitHub usernames from first names. If identity is genuinely unknown, resolve that before selecting a person's assignment.

## 2. Required shared context for every agent

Read these documents, not only this list:

| Read | What the agent must understand |
|---|---|
| [Root instructions](../AGENTS.md), [technical agent rules](../docs/agent-context/AGENTS.md), [START_HERE](../START_HERE.md) | Scope, repository, permissions, preservation and continuous full-role execution |
| [Setup status](../docs/agent-context/00-setup-status.md), [project brief](../docs/agent-context/01-project-brief.md), [code map](../docs/agent-context/03-code-map.md) | What already exists, what is proposed, implementation objective and current implementation boundaries |
| [Complete assignments](COMPLETE_ASSIGNMENTS.md), [human overview](HUMAN_START_HERE.md) | Entire team responsibility, dependencies, first milestone versus full role, G0–G6 acceptance |
| [Shared interfaces](../docs/agent-context/04-interfaces-and-data.md), [full data contract](../docs/agent-context/starter/data-contract.md) | Producer/consumer types, IDs, errors, verification, clocks, energy domains, raw data and hidden-reference boundaries; distinguish proposed shapes from implemented APIs |
| [Hardware/access](../docs/agent-context/05-hardware-and-access.md), [dependencies/hardware](DEPENDENCIES_AND_HARDWARE.md) | Grace model/GPU versus CPU tools, actual session requirements, measurement scope and ownership. Alex has reported no-sudo RAPL access; session identity/coverage/isolation still require evidence |
| [Fall timeline](FALL_TIMELINE.md), [implementation validation boundaries](SIGMETRICS_ASSESSMENT.md) | Evidence deadlines, pilot/expansion decisions and implementation validation limits |
| [PR workflow](PR_WORKFLOW.md), [shared publication protocol](README.md), [turn template](TURN_TEMPLATE.md), [progress template](../docs/agent-context/12-progress-template.md) | Small PRs without stopping implementation, tests, exact evidence, autonomous scoped pushes and review ownership |

Read the actual code, task issues and relevant open/merged PRs as well. An issue describes a reviewable unit; it does not replace the full assignment. Planning rows are not experiment results. Older setup instructions describe historical preparation; do not recreate existing repos/branches or restart completed work.

## 3. Required named context

| Person | Read all of these |
|---|---|
| Alex | [Personal instructions](alex/AGENTS.md), [human guide](alex/HUMAN_START_HERE.md), [FULL_ASSIGNMENT](alex/FULL_ASSIGNMENT.md), [technical role](../docs/agent-context/06-alex-runtime-measurement.md), [alex.txt](alex/alex.txt) |
| Aldric | [Personal instructions](aldric/AGENTS.md), [human guide](aldric/HUMAN_START_HERE.md), [FULL_ASSIGNMENT](aldric/FULL_ASSIGNMENT.md), [technical role](../docs/agent-context/07-aldric-workloads-verifiers.md), [aldric.txt](aldric/aldric.txt) |
| Nitheesh | [Personal instructions](nitheesh/AGENTS.md), [human guide](nitheesh/HUMAN_START_HERE.md), [FULL_ASSIGNMENT](nitheesh/FULL_ASSIGNMENT.md), [technical role](../docs/agent-context/08-nitheesh-campaign-reproducibility.md), [nitheesh.txt](nitheesh/nitheesh.txt) |
| Stephen | [Personal instructions](stephen/AGENTS.md), [technical role](../docs/agent-context/09-stephen-method-integration.md), [stephen.txt](stephen/stephen.txt), all three full-role checklists above for coordination. Stephen's private human guide remains outside this repo |

Read all four latest team context records from the fetched integration ref: [Stephen](stephen/LATEST.md), [Alex](alex/LATEST.md), [Aldric](aldric/LATEST.md), [Nitheesh](nitheesh/LATEST.md). Follow their linked evidence/turn records where relevant to current work, dependencies or changed decisions. Report absent records as unknown progress, not proof that a person did nothing. Immutable notes are evidence of their date, not overrides of later maintained scope or user instructions. Do not load every historical file indiscriminately or expose hidden evaluation results.

## 4. Demonstrate understanding, then execute in the same work session

Your first substantive update must include:

1. Person/role, inspected code commit and fetched integration commit; identify any older local instructions or prompt that were superseded.
2. Files actually read from sections 2 and 3, with any unread/unavailable required context identified. Do not claim a read based on filenames or this checklist alone.
3. A short explanation of the implementation objective, complete role, owned component, hardware placement and who produces/consumes its interfaces.
4. EVERY role milestone with status, evidence/PR/tested commit, precise dependency and owner, and next action. Stephen maps the G0–G6 coordination/research responsibilities.
5. The tests/artifacts that must pass before your component and the shared build can be called ready for Grace, plus the next concrete implementation action.

This is an acknowledgment checkpoint, NOT a request for approval and NOT a reason to stop. Immediately continue implementing/testing/debugging the next ready item, publishing scope/evidence in your own context as required. Continue through the complete role. Only actual external blockers constrain dependent work; continue all useful independent work.

## 5. What the human verifies

The human reads the overview and personal human/full-assignment guide. Confirm that the agent's explanation matches the complete role, that it used current shared instructions, and that it named the correct hardware, dependencies and acceptance checks. Inspect representative outputs and failures during work. Stephen verifies the published full-role acknowledgment for each person before assuming they are oriented. No acknowledgment is recorded automatically by these files, and a correct startup explanation is not proof of working code or measured energy.

