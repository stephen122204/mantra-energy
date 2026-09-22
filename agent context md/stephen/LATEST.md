# Latest published context: stephen

[Immutable turn record](turns/20260922-integrated-native-handoff.md)

# Integrated task suite and current execution handoff

## Task and current understanding

Stephen authorized complete software integration and a verified bounded data-collection launch. PR43 is merged at 2003b78; its tested executable head is 85700fe. Component PR41 and PR42 are merged through it. PR40 is superseded by this combined integration, including its catalog and ownership repairs and independently reconciled partial-artifact recovery.

## Ideas and hypotheses

Two actual failure paths needed explicit separation: a reaped worker need not have reached a valid initialized energy endpoint, and a recovered terminal record intentionally differs from a checkpoint saved before interruption.

## Decisions and rationale

Require verified worker termination before another task; forced native stops invalidate energy. Preserve all checkpoint artifacts and validate hashes, identities and recovery endpoints. Never rewrite an old failed answer, use missing energy as zero, or relax an answer checker. New execution uses a separate clean checkout and fresh output directory.

## Changes and artifacts

PR43 includes all three task components, prepared inputs, full CLI integration, detailed checker artifacts and token-budget auditing. Startup failure handling and partial-artifact recovery are repaired. The new node checkout is integrated-repo-20260922 in the existing private work directory; connection details and raw artifacts remain private.

## Tests and evidence

All 15 Linux/Windows CI checks passed at 85700fe before merge. Earlier combined local checks passed 171 tests; the final recovery patch passed 55 focused pipeline/window/recovery tests. Offline replay reconciles all ten retained older pilot attempts; failed/incomplete outcomes remain unchanged. Both pilot snapshots were copied off-node with all file checksums matching. Backend numerical diagnostic tests require Torch and will use the existing node backend environment; the lightweight local test environment does not contain Torch.

## Open questions and disagreements

The older catalog pilot is not the expanded task pack. Current native model-reference qualification is running separately under the existing shared GPU lock. Do not launch a competing model, build, download or bulk copy during its measurements. Expanded-task native execution remains unqualified until that gate and its own run checks pass.

## Next actions and handoff

Stephen owns the next integrated task-pack qualification and its launch/backup verification. Reuse the current model-reference qualification rather than duplicate it. Preserve the original checkout and run directories; use the separate integrated checkout. Alex's measurement interfaces, Aldric's workload/checker interfaces and Nitheesh's records/recovery interfaces are integrated; any new shared-code change must target fetched integration, not the superseded PR branches. Fetch this handoff before another deployment. Do not claim final campaign readiness or all tasks correct from green CI.
