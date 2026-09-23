## Task and current understanding
Stephen owns native runtime correctness and shared integration. Alex supplies measurement interfaces, Aldric task/checker interfaces, and Nitheesh durable execution/export interfaces. The current integration baseline is a9a1ff4; the fresh repair checkout is /tmp/alems-aio-repair-20260923. Existing integrated components are retained. Live runtime qualification and final end-to-end acceptance remain outstanding; fixture success alone is not readiness.

## Ideas and hypotheses
Native AIO request completion changes its atomic predicate without the waiting mutex. Scheduler queue publication likewise does not synchronize with the schedule condition-variable mutex. Both permit a notification between a false predicate check and sleeping. These are source-level defects; they are not yet proven to explain every observed initialization failure.

## Decisions and rationale
Use a shared small update-and-notify helper that updates under the waiter's mutex and notifies afterward. Apply it to both request completion paths, scheduler enqueue with schedule-then-queue lock ordering, and exit notification synchronization. Preserve model arithmetic and task contracts. Keep the existing runtime unchanged and build a separate candidate for validation.

## Changes and artifacts
Draft PR 53, stephen/aio-wakeup-repair, commit 2d8f9c1. Updated native lifecycle header, backend patch, synchronization regression, and CI test list. Private launch/configuration records and raw outputs remain outside GitHub.

## Tests and evidence
Four local focused tests pass: native lifecycle plus synchronization tests, including a negative control that removes the predicate-update lock and must fail. Linux MoE CI passed; remaining CI and separate native build qualification are pending. The tests exercise the exact helper and verify all patched AIO call sites, but do not alone prove the whole native scheduler is race-free or validate live model execution.

## Open questions and disagreements
Native initialization reliability, model-reference agreement, actual transfer behavior, and full combined output checks still require the new build. Do not reuse the old build fingerprint or silently promote the candidate. No full execution-readiness claim is made.

## Next actions and handoff
Inspect PR CI and the separate candidate build, qualify model arithmetic without relaxed tolerances, then check repeated startup and the complete task/measurement/export path on a new version. Preserve prior failures and do not overwrite existing manifests. Continue the maintained full-role assignments; this scoped repair does not replace their remaining acceptance gates.
