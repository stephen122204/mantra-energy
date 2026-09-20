# Integrated code and current team instructions

## Task and current understanding

Stephen authorized review, repair and integration of all open PRs. Fresh clone /tmp/alems-pr-integration-EGOOT0 started at d71cc4c. PR34 runtime, PR35 query workload, PR36 session diagnostics and PR37 plain-language handoff are all merged into research/energy-diagnosis. The reviewed merged code commit is 33daf571c2b36656da79e47adac058e304a4a65d. No open PR remained at final inspection.

## Ideas and hypotheses

A concrete result-backup defect was reproduced: OpenSSH parses -o values separately, so a known-hosts path with spaces can split into multiple filenames despite correct subprocess argv handling. This was a software issue, not a hardware measurement finding.

## Decisions and rationale

Fixed the path inside OpenSSH's option parser and retained strict host checking. Merged in dependency order using merge commits, retargeting dependent PRs to integration without rewriting shared history. Experimental code integration is distinct from model-reference/hardware acceptance. No native numerical tolerance or scientific definition changed.

## Changes and artifacts

- PR34 merged at 961777fc52cd39dc4831dd0026d399c9e4288c37.
- PR35 merged at b06c814e99a911f2ac06ccd54cb5d0a66b1130ed.
- PR36 includes repair 367753a199ca9a47f4697ed6b5c5c77d26572828 and merged at 1176b976bd7d9cc03c99f82c09179cba6b44f7a9.
- PR37 includes current-state wording aa3a323 and merged at 33daf571c2b36656da79e47adac058e304a4a65d.

Read agent context md/CURRENT_HANDOFF.md, BATCH_ACCEPTANCE.md and your named HUMAN_START_HERE.md from fetched integration. The previous latest note's feature-branch links are superseded by these now-merged paths. Root instructions, startup, full assignments and named prompts point to them. Preserve local changes while fetching; do not reset working branches.

## Tests and evidence

On the combined executable code: 190 integrated runtime tests plus 5 subtests; 118 MoE/query/CPU numerical/session tests, including actual OpenSSH config parsing without network, small real DuckDB/PyArrow fixtures, native C++ lifecycle and optional CPU Transformers-prefix cases; 6 context-publisher tests; setup checker, shell syntax and diff checks passed. No GPU/model download or hardware session was used.

PR36 repaired exact-head CI 35537484128 passed all 9 jobs. PR37 follow-up CI 35537554989 passed all 8 jobs, including Linux/Windows integration and MoE fixtures. Final merged source, tests, scripts, workflow and handoff files match the locally combined reviewed tree. Integration-push CI is separate from these completed pre-merge checks.

## Open questions and disagreements

Software integration does not establish model-reference agreement, current-node access, physical validity for every configuration or readiness of a full batch. Standard-model score differences remain unresolved; zero-transfer preparation remains unqualified. Current-node setup and supplied execution settings/budget still need confirmation. No unmeasured result has been promoted to accepted hardware evidence.

## Next actions and handoff

Students fetch integration, read current handoff and inspect completed code before extending it. Alex checks measurement records and transfer timing; Aldric tasks and independent answers; Nitheesh complete run records, recovery and exports. Stephen owns native model agreement, starting-state rules and shared configuration acceptance. Continue ready software work against fixtures; use one coordinated measured queue once the bounded session is assigned. Do not reconstruct the old stacked branches or restart first issues. Keep research discussion and raw result files outside GitHub.
