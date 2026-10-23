# Transfer replay and verified backup integration

## Task and current understanding
PR49 and PR50 are merged on integration, through 6a757096ef32750874d9d453dc2c674e3ea728c5. The node execution checkout is pinned to that commit. Alex owns backend and measurement behavior, Aldric owns workload inputs and independent verifiers, Nitheesh owns durable records and recovery, and Stephen verifies the integrated stack. A passing component is not whole-system qualification.

## Ideas and hypotheses
Repeated complete copies can exhaust the receiving disk even when individual batches are small. Incremental hash manifests should bound duplicated bytes while preserving recovery history.

## Decisions and rationale
Back up only between terminal bounded batches. Use compressed incremental snapshots to avoid repeatedly copying unchanged raw files. Every receipt identifies the complete current manifest and its predecessor. Preserve all bundles and receipts; unchanged files may live in an earlier bundle. Never delete older snapshots because the latest archive looks complete.

Transfer replay checks host-side admission/placement brackets, actual tool-body bounds, clock uncertainty, later requests and first-dispatch residency. Logical placement bytes are not physical PCIe traffic, and a partial host bracket overlap is not proof that DMA overlapped useful computation. Unavailable observations remain explicit.

## Changes and artifacts
- `studies/energy_diagnosis/moe/audit_transfers.py` independently checks registered trace artifacts and their hashes.
- `studies/energy_diagnosis/diagnostics/archive_results.py` provides terminal-only snapshot export, verified SSH reception, chain validation and restoration into a new directory. Supply the explicit remote repository/interpreter plus the identity and known-hosts file. `--restore-receipt` and `--destination` restore a chain without SSH.
- Archive export rejects symlinks, a changing tree and an active status. Reception rejects transport truncation, invalid paths, non-file or duplicate members, missing files and hash mismatch.

## Tests and evidence
17 focused archive tests pass. Existing session diagnostics pass. All 15 PR50 CI jobs pass, including native Windows recovery and CLI coverage. An initial Windows path-validation failure was fixed using native paths on the archive server, while the SSH receiver retains POSIX remote paths.
- Real SSH snapshot, unchanged incremental snapshot, and full-chain restoration were exercised successfully against completed node artifacts. No result values are published here.
- The grouped reference implementation passed the required fixed-input checks without changing tolerances. That remains limited numerical evidence; closed-loop tasks and unattended output acceptance are separate checks.

## Next actions and handoff
A bounded guarded task-validation job is active. Do not start another node test, build, download or backup during its protected measurement windows. New SSH sessions may be temporarily unavailable during a window and are restored between batches, with a fallback timer. Do not bypass that arrangement by logging in another way. The receiver automatically verifies a terminal batch before proceeding.

## Open questions and disagreements
The full campaign is not declared ready by this note. Remaining acceptance includes the current task-validation outputs, clean counter/trace/ownership audits, final frozen configuration and reservation budget, and first complete campaign output verification. Preserve failed attempts and stop invalid batches; do not revise checks merely to obtain green status. Detailed research decisions and raw outputs stay private.
