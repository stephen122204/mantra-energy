# Integrated native qualification and guarded-run handoff

## Task and current understanding

PR43/44/45/46/47/48 are merged. The execution checkout is integration f3499c886c13f54d2ff427c3e95251b184425fbc. There are no open PRs at this checkpoint. Older notes calling PR40 or PR45 merge-pending are superseded. This is a software/native-qualification checkpoint, not a claim that every task or unattended campaign is qualified.

Alex's scope is backend/measurement readiness, Aldric's is workload contracts and independent correctness checks, Nitheesh's is durable records/recovery/export, and Stephen integrates and verifies the complete stack. Completion of one component does not certify the others.

## Ideas and hypotheses

The full pinned framework model selects grouped_mm experts, while a standalone expert can default differently. Native arithmetic must match the full model's actual implementation. OS background work and unrelated processes can contaminate valid-looking counter records, so arithmetic validity is distinct from measurement isolation.

## Decisions and rationale

Keep the existing numerical tolerances. The new native mode restores grouped BF16 projection boundaries, FP32 weighting and token/top-k reduction order. Require explicit configuration and the matching rebuilt extension. Preserve old builds and failed captures. No mutation of an installed fingerprinted backend environment.

Use the bounded launcher, reviewed process baseline, operating-state artifacts and balanced-pair option where their prerequisites hold. The process guard is sampled detection, not access control or perfect isolation. Operators must coordinate exclusive periods; do not log into the measurement node to build, download, copy, run another test or repeatedly poll during the protected window. Backups and inspection occur between bounded batches. Do not kill other users' jobs without identifying ownership and scope.

## Changes and artifacts

- PR45: grouped reference arithmetic, pinned implementation declaration, native microcheck and fixed-input reference capture support.
- PR46: seeded complementary policy order with even repetitions and immutable comparison mode.
- PR47: hashed operating-state artifacts with acquisition timestamps, sensor provenance and explicit unavailable fields.
- PR48: optional Linux process guard, terminal interference status, retained descendant cleanup and copy/recovery recognition. Windows fixture readiness waits for readable PID markers; termination checks remain strict.
- Private hardware outputs, addresses, credentials, run definitions and research interpretation remain outside Git.

## Tests and evidence

The integrated PR head passed all 15 CI checks. Local combined task/measurement/order/token-verifier checks passed (62 tests); reference/session/process checks passed (35, with two Linux-only tests skipped on macOS and exercised by Linux CI). Six native expert cases matched the actual grouped framework implementation exactly. The full fixed-input qualification completed successfully: repeated demand, demand/preparation with nonzero completed preparation, and standard-reference scores agreed exactly at all captured positions without changing tolerances. Capture and diagnostic bundles were copied off-node and hash-verified.

This qualification covers its fixed-input cases, not arbitrary prompts, actual tool-overlap or energy efficacy. The target-node operating-state reader was exercised; unsupported CPU throttle counters remain unavailable. Earlier pilots are not clean effect evidence where concurrent setup activity was possible.

## Open questions and disagreements

Expanded real-model task paths, actual token margins, longer request/state qualification, target-node task durations, induced interruption/recovery, and complete output-bundle audits remain launch dependencies. Reservation budget and final run-definition freeze are separate operator checks. Sensor readings and raw-counter reconciliation are not external electrical calibration.

## Next actions and handoff

Stephen is running the guarded node preflight and then the expanded task and unattended checks. Other agents may continue local code review but must not launch work on the shared node during that sequence. Use `studies/energy_diagnosis/moe/OPERATIONS.md` for current flags and limitations. Keep failures and missing readings; stop and diagnose invalidity rather than silently replacing records or weakening checks.
