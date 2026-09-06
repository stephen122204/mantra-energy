# Alex: shared agent context

Use the issue assigned by Stephen; this folder name does not assign a student role or a GitHub account.

Read [the shared protocol](../README.md), [the latest summary](LATEST.md), the root instructions and your assigned issue at the start of every turn. Read other contributors' latest records from the remote integration branch before making dependent decisions.

Keep a local note during work. Before ending every completed turn, publish your reviewable understanding, ideas/hypotheses, decisions with concise rationale, evidence, tests, questions and next steps using `scripts/publish_agent_context.py --author alex` with the turn ID and note path. Use [the template](../TURN_TEMPLATE.md). Remote pushes are already authorized within the protocol's scope.

Immutable records will appear under `turns/`. `LATEST.md` is a full snapshot of the latest published summary plus a link to its immutable record. A turn that makes no code change still needs a context record. Report failed publication honestly and retain the pending note for retry.

For a fresh agent session, supply [alex.txt](alex.txt). It contains the proposed role, first issue, code/test expectations and context-publication workflow.
