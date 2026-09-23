## Task and current understanding
Move serial bounded execution to the allocated node while allowing the receiver to disconnect. Keep frozen measurement wrappers unchanged.
## Ideas and hypotheses
An offline receiver should delay replication, not dictate execution. Local snapshots do not replace off-node durability.
## Decisions and rationale
Use a node owner lock and shared measurement/checkpoint/transfer lock. Preserve existing terminal failures; ambiguous launches require review instead of duplication. Retain immutable incremental bundles and compatible restore receipts.
## Changes and artifacts
PR57 adds node_batches, receive_node_batches, operational documentation, regression tests and CI inclusion. Measurement source is separate from orchestration source.
## Tests and evidence
33 focused tests passed locally and on Linux node: offline execution, reconnect/restore, corruption, interrupted transport, exclusion lock, no duplicate restart, low storage, cutoff and failure retention. Hosted CI remains unavailable due account restriction.
## Open questions and disagreements
Node-local snapshots remain vulnerable to allocation loss. No persistent object-store backup is claimed. An unrelated runtime failure remains a reason to halt measured work, never to bypass checks.
## Next actions and handoff
Use the dedicated node service and receiver specification. Retire the client dispatcher at a terminal boundary before adopting existing batches. Keep measurement validity checks and hard cutoffs intact; resume only after runtime issues are resolved.
