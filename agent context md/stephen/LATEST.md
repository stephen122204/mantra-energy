[Turn record](turns/20260909-implementation-only-publication.md)

# Turn summary: Stephen — implementation-only publication

## Task and current understanding

Restrict shared repository context to implementation and preserve the full assigned coding scope. Keep private research discussion outside repository publication.

## Ideas and hypotheses

Implementation concern: broad legacy publication instructions could cause agents to copy material outside the allowed scope. All active entry points must state the narrower boundary, including named kickoff prompts.

## Decisions and rationale

Update instructions and the turn template consistently. Retain legacy linked document paths with implementation-only content to avoid breaking kickoff links. Remove the recent research memos and replace this author's latest snapshot. This changes the current tree; it does not erase earlier Git history.

## Changes and artifacts

Root and nested agent instructions, shared protocol, named prompts and guides now scope publication to implementation turns. The template limits hypotheses to software alternatives and debugging. Research-only turns do not trigger context publication. Implementation contracts, complete role assignments and runtime code remain intact.

## Tests and evidence

Documentation-only update. The existing portable setup/link checker passed, covering handoff links, provenance and planner behavior; Git whitespace checks passed. No runtime or hardware behavior is changed or newly validated.

## Open questions and disagreements

This is an instruction-level publication boundary, not an automated semantic content filter. Agents must inspect staged content and PR/issue text before publishing. Older Git commits retain prior content.

## Next actions and handoff

Review and integrate this scoped cleanup through a PR. Contributors should refresh the integration branch and reread the publication boundary before publishing their next implementation update. Continue the remaining assigned coding and testing milestones.
