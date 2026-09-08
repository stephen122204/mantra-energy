## Task and current understanding

Stephen explicitly requires each agent to execute the WHOLE assigned role without stopping after a milestone, PR or status/context checkpoint. This is an instruction to complete implementation/test/debug/integration work, not merely acknowledge all milestones.

## Ideas and hypotheses

Distinguishing review checkpoints from execution stopping conditions prevents a first-PR handoff from becoming the end of the role. Missing hardware or a scientific decision should block only work that actually depends on it, not independent later-stage software preparation.

## Decisions and rationale

Added an explicit continuous whole-role execution directive. Agents must fix their own failures and continue ready independent or declared dependent PR work without asking whether to continue. Build assigned later-stage software/tests using declared fixtures when necessary. Keep real resource budgets, individual access, Stephen merge ownership and evidence-dependent scientific decisions intact. Stop only at full-role handoff, explicit human stop or specific external blockers for all remaining useful work. Provider session limits require an exact resumption record; documents do not create an always-running process.

## Changes and artifacts

Pushed 6d0e0e7 to lead/complete-assignment-handoffs, updating PR #18. Added the directive to team assignment, root/nested instructions, all three personal AGENTS/full assignments/human guides/name.txt prompts, PR workflow and Stephen coordination prompts. No merges, student messages, runtime changes or hardware jobs. Updated PR body to describe final behavior and tested revision.

## Tests and evidence

python3 scripts/check_energy_diagnosis_setup.py passed (documentation links/provenance/planning only). git diff --check passed. Inspected and staged only the 18 changed Markdown/text files. Feature push completed. Existing implementation readiness is unchanged.

## Open questions and disagreements

PR #18 is still awaiting merge. Existing agents have not been observed fetching/acknowledging the revised instructions. Cannot keep separate student model sessions running from this thread or guarantee their runtime persistence. Complete assigned work does not authorize fabricating credentials, results or scientific decisions.

## Next actions and handoff

Review/merge PR #18, then each student refreshes the updated context/prompts in their current agent session. Agent reports all milestone evidence and immediately continues implementation rather than stopping at that report. Subsequent reports accompany ongoing work, with precise external blockers only when needed. Verify actual combined software readiness before the main Grace experiment.
