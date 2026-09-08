## Task and current understanding

Stephen requested that every agent and human guide communicate the complete role, not just the first part. Audit confirmed a real contradiction: all three kickoff prompts instructed a bounded first task and labeled later work NEXT, ONLY WHEN ASSIGNED. Technical role documents contained larger responsibilities; human guides left replay, suite expansion or selector boundary/campaign support less explicit.

## Ideas and hypotheses

One named complete checklist per student, required for both human and agent, makes scope reviewable. Explicit all-milestone acknowledgment is necessary to verify uptake; repository edits do not automatically refresh active remote chats.

## Decisions and rationale

Clarify all existing roles and acceptance gates without expanding hardware authorization. Ready software milestones are already assigned and continue in separate PRs. Retain Stephen review, individual session/budget requirements, pilot decision and held-out freeze. Introduce milestone IDs AX1–AX5, AL1–AL6 and NI1–NI5 plus team G0–G6 integration gates. Explicitly distinguish a completed first contribution from a completed role.

## Changes and artifacts

PR #18: https://github.com/stephen122204/alems-energy-diagnosis/pull/18
Branch lead/complete-assignment-handoffs, commit 5762c14, isolated worktree /Users/Stephen/alems-db-exploration/alems-complete-assignments. Pushed 27 documentation/prompt files including new agent context md/COMPLETE_ASSIGNMENTS.md and each student FULL_ASSIGNMENT.md. Root/nested agent instructions, human guides, technical roles, kickoff prompts and workflow entry points require the complete scope. Updated Stephen coordination prompt but did not recreate his private human guide. No code changes, implementation merges, messages to students or mailbox actions.

## Tests and evidence

Setup/link/provenance/planning validator passed. git diff --check passed. One-time audit verified every student AGENTS.md, HUMAN_START_HERE.md and name.txt references the full assignment; obsolete stop wording removed; checklists include acceptance/dependencies/timing; private Stephen human guide absent. PR #18 was OPEN and MERGEABLE at inspection; remote checks had not yet been reported. No runtime or hardware tests performed for this documentation change.

## Open questions and disagreements

PR is not merged: shared integration still has old maintained guides until review/merge. Students may have stale email attachments or active agent sessions; no acknowledgment of the new scope has been received. Updated prompts/checklists are available on the PR branch for review. Documentation cannot guarantee autonomous execution when a chat is inactive or an agent fails to follow instructions.

## Next actions and handoff

Stephen reviews/merges PR #18. Then each student fetches current integration without discarding work and supplies the updated prompt or instructs the existing agent to read COMPLETE_ASSIGNMENTS.md, personal FULL_ASSIGNMENT.md, human guide and technical role. Each agent publishes a table for EVERY milestone: status, evidence/PR/tested commit, blocker with owner and next action, and explains full scope to the human. Verify those acknowledgments before assuming everyone has read it. Continue next ready software milestone; preserve hardware and scientific gates. Implementation priorities remain concrete contracts and integrated local success/failure tests with early Grace smoke validation in parallel.
