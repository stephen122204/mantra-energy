# Latest published context: stephen

[Immutable turn record](turns/20260922-combined-task-pack-handoff.md)

# Combined task-pack implementation handoff

## Task and current understanding

PR43 (https://github.com/stephen122204/alems-energy-diagnosis/pull/43), branch `stephen/task-pack-interface`, commit `3dcd92ccca72f894ac2571d3ab897a67a3870f55`, combines the PR40 catalog/recovery repairs at 353a6af with the PR41 numerical and PR42 database components and the additional task-pack/SQL-repair implementation. It is not yet merged into integration or deployed. Fetch this branch in a separate checkout for review; preserve current node checkouts and running jobs.

## Changes and artifacts

Read `studies/energy_diagnosis/moe/TASK_PACK_HANDOFF.md` for generated/prepared task specifications, input bounds, immutable assets, CLI selection and tokenizer audit. Read `studies/energy_diagnosis/moe/OPERATIONS.md` for bounded launch, inspect, stop, recovery, resume and verified copy commands. The default catalog and optional task pack are different selections. An older-catalog native run does not qualify the added task pack.

## Tests and evidence

The actual campaign launcher dispatches each task to its matching tool/verifier and records its asset/checker identity. Added families are grouped numerical regression, three business-query intents, and bounded SQL repair checked on additional inputs. Prepared numerical assets are checksum-pinned and copied before execution. No source datasets or raw run outputs are included in Git.

The combined local regression suite passed 126 tests. Tests cover runtime integration, catalog/repair contracts, actual fixture worker execution, task pack, independent component checks, prepared-input rejection, resume and token-budget boundaries. Linux/Windows CI is separate and should be checked on the exact head. Fixture evidence uses scripted responses and simulated sensors, not hardware qualification.

## Next actions and handoff

Aldric: check selected task prompts, answer schemas, independent verifiers and meaningful failure examples. Alex: check the supplied configuration's measurement domains, raw-counter evidence, lifecycle boundaries and actual transfer/tool timing. Nitheesh: reconcile every planned slot and attempt, retain failures and verify off-node copies/restoration. Stephen: integrate reviewed interfaces, qualify model/reference agreement, provide exact configuration/session budget and approve expansion. Continue the full existing role assignments; this is a path update, not a new first-task-only assignment.

The launcher defaults to 512 output tokens. Larger grouped answers can exceed it. Use `audit_token_budget` with the pinned local tokenizer and explicit proposed budgets, then check actual native responses and alternate tool paths. A fitting scripted transcript does not guarantee all model paths fit. Do not silently truncate answers, weaken correctness checks or change a frozen configuration while resuming.

Before further native work, use the supplied allocation, isolation rules and bounded budget. Do not launch competing jobs or modify the checkout underneath an active batch. Keep private dataset paths, credentials, raw evidence and research discussion outside GitHub.


## Ideas and hypotheses

Recorded conversations can expose token-budget overflow before native execution. This is a software preflight check, not a model-performance prediction.

## Decisions and rationale

The components share one combined review branch to avoid deploying partial interfaces. Frozen task metadata and independent checker identities make resume and saved-record validation explicit.

## Open questions and disagreements

Actual-model execution for the new task families, reference agreement and the supplied hardware configuration remain to be qualified. Do not infer them from the local test count or older-catalog runs.
