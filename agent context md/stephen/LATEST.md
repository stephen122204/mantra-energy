# Latest published context: stephen

[Immutable turn record](turns/20260922-explicit-tools-and-batch-checkpoints.md)

## Task and current understanding

Stephen owns shared integration and the bounded launch path. Alex's measurement interfaces, Aldric's task/checker interfaces and Nitheesh's durable records/export interfaces must work together. Completion remains an end-to-end checked output, not merely an open PR or fixture pass. Execution definitions and hardware scheduling remain supplied separately and private.

## Ideas and hypotheses

Model-facing tool descriptions should expose mandatory action-specific arguments explicitly. A serial remote coordinator needs a durable launch identity and verified backup checkpoints to avoid duplicate work or premature advancement after transport failures.

## Decisions and rationale

PR 51 adds explicit action schemas and examples, schema-before-query instructions and ordered ETL read/write/test guidance. It validates required fields before dispatch; it does not change correct answers or model arithmetic. PR 52 adds a POSIX coordinator with durable dispatch intents, bounded transport retries, source-checked incremental backups and integrity checks on resume. Its remote wrapper must independently enforce measurement isolation, cleanup and timeout; the coordinator does not make SSH polling harmless.

## Changes and artifacts

PRs 51 and 52 are merged into research/energy-diagnosis; combined implementation commit 1bff0466cdf147522b623960394d2c848031d3b8. New modules are moe/tool_contracts.py and diagnostics/batch_coordinator.py. Archive chain verification is reusable without extraction. Existing public handoff remains the startup point; no research discussion or raw results are included here.

## Tests and evidence

All 15 GitHub checks passed on each merged PR's tested head, including Linux and Windows coverage. Combined focused task-contract, coordinator and archive tests passed 35/35 locally and on the target Linux environment. A Windows test's one-second deadline sometimes expired during spawned worker startup before its intended injected tool timeout. Its fixture budget is now eight seconds against the unchanged twenty-second injected tool sleep; timeout and drain assertions remain. No experiment deadline or numerical tolerance changed.

## Open questions and disagreements

Passing fixture tests is not qualification of live model behavior, measurement isolation or a full batch. Remote launch outcome ambiguity deliberately stops automatic re-launch; inspect the preserved dispatch intent rather than deleting it. Coordinator receivers need uninterrupted host/network availability, and remote wrappers need independent cutoff and access restoration.

## Next actions and handoff

Use the exact supplied clean execution revision and new output directory after prompt/contract changes. Preserve earlier failures and terminal records. Verify live task calls, raw counters, transfer records, cleanup and off-node receipts before expanding. Keep all private execution specifications and raw evidence outside GitHub. Continue each full role against the maintained assignments; no new first-task prompt is required.
