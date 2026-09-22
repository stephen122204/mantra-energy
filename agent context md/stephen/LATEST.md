# Latest published context: stephen

[Immutable turn record](turns/20260922-pr40-repair-and-node-pilot.md)

# PR #40 repair, integrated interruption path, and node pilot

## Task and current understanding

Fresh clone at integration 3664414. PR #40 (expanded MoE task suite, contributor head c9f908d) was reviewed, its reported defects reproduced and repaired on the same branch, the integrated software was exercised locally through interruption/recovery/resume, and the allocated Chameleon A100 node was prepared under the shared account with the pinned checkpoint and backend build. A bounded native smoke, a ten-slot pilot batch and the fixed-input qualification were executed. Final PR head 0e753e3; CI 9/9 green; merge left to Stephen. Hardware artifacts, addresses and raw numbers stay outside Git.

## Ideas and hypotheses

- Restart safety is asset identity, not regeneration: an existing asset directory is reused only when identical (SQLite compared by logical dump) and refused otherwise; a rerun never rewrites a changed input.
- Recovery after an interruption yields a ledger attempt whose checkpointed artifacts predate the recovery record; summary and audit must treat that explicitly instead of as evidence loss or as a completed goal.
- A process-group signal cannot reach the owned model worker or isolated tool processes (own sessions); the launcher must terminate descendants recorded before the stop.
- A killed and reaped worker cannot own device work: `owned_work_terminated` means exactly that, while a forced stop before idle confirmation remains visible and invalidates the captured energy.
- Hypothesis for the one initialization hang (worker log ends after topology setup, >600 s, memory not exhausted): backend-internal; not diagnosed. The batch now tolerates it.

## Decisions and rationale

- Repairs were pushed onto the PR branch to preserve the contributor's commit (934a9a8, 82c1011, 7780a84, 353a6af, 5446dad, 0e753e3). Task/verifier version stays `moe-tools-v4` as the PR declared.
- Hidden ETL checker now enforces its declared language (annotations, type comments, non-int/str literals, comprehension filters rejected); both checkers parse with type comments visible; reference DB opened read-only.
- Prompt-visible tool contracts (`TOOL_CONTRACTS`) restored for the original families and declared for database/ETL/numerical tools with argument schema, example call and ordering text.
- The campaign command keeps the ledger default retry limit (0) after recovery; retry policy belongs to the run definition.
- Tolerances for the fixed-input reference comparison were not changed.

## Changes and artifacts

- `studies/energy_diagnosis/moe/workloads.py`: restart-safe `create_tasks`, `TOOL_CONTRACTS`, stricter checkers.
- `moe/summary.py`, `moe/audit_windows.py`: recovered attempts (with or without checkpointed artifacts) summarized as unknown cost and audited as `recovered`, never as measured.
- `moe/run.py`: SIGTERM/SIGINT unwind through cleanup, exit 130, attempt left for recovery.
- `moe/backend.py`, `local_run.py`: termination vs idle accounting; descriptive RPC timeout error.
- `diagnostics/run_bounded.py`: descendant termination, `--grace-seconds`, `surviving_pids`.
- `moe/OPERATIONS.md`: launch/inspect/stop/recover/resume/export/copy commands; README/CI updated; tests added in `tests/test_moe_expanded_tasks.py`, `tests/test_moe_pipeline.py`, `tests/test_session_diagnostics.py`.
- Node work directory (private): study and backend environments, hashed checkpoint manifest, patched backend build manifest, private configuration, launcher helper.

## Tests and evidence

- Fixture-tested: local 207 runtime tests + 5 subtests; 151 MoE/launcher/recovery tests; setup checker; CI 9/9 at 0e753e3. On the node at the execution commit: runtime 207, MoE/launcher 74.
- Hardware-tested (execution commit 7780a84 for smoke/pilot, 0e753e3 for qualification; node identity, GPU UUID, boot id, driver/CUDA, checkpoint and build manifests recorded in the artifacts):
  - Counter preflight: two RAPL package domains and NVML board energy readable.
  - Smoke: 2/2 goals correct via real inference, all domains valid, replayed audit reconciles, prefetch completed 56 experts under budget and all were later requested; exit 0.
  - Pilot: 10/10 slots realized (9 completed, 1 recovered after an initialization timeout); 5 verifier passes, 4 genuine verifier failures retained; campaign validation valid; window audit passed with 9/10 fully measured; identical prompts and greedy responses across settings for 3/4 comparable tasks.
  - Second pilot at the final commit: 10/10 slots realized without interruption, validation valid, audit passed for all attempts, same task failures; per-goal wall time consistent with the first pilot.
  - Interruption path on hardware: launcher status with cleanup evidence, guarded recovery, resume without duplicate attempts, verified off-node copies (all copies hash-verified from the laptop with rsync 3).
  - Qualification: demand repeatability exact; preparation effective with identical scores; reference comparison FAILS the declared tolerances while argmax agrees at every position. Numbers and captures are stored privately.
- Not tested: induced interruption on hardware; `exact_prefix` mode.

## Open questions and disagreements

- Standard-model agreement remains failed under the existing criteria; Stephen owns the diagnosis.
- Reservation cutoff was not readable from the node; launcher cutoffs were conservative operator choices.
- The shared node account was used concurrently by another actor: a repository clone and environment build ran during the later goals of the second pilot (their socket-wide CPU readings are therefore not clean), and a qualification job started seconds after the batch released the GPU lock. The lock serialised the GPU; per-person accounts or one agreed operator are needed for attributable measured work.
- One unexplained worker initialization hang; prefetch transfers complete after the very short tool bodies of these tasks (charged in the resume barrier); two tasks fail on model behavior (assignment in the constrained repair, by-hand regression arithmetic) and the linear-fit responses diverge between settings during generation despite exact fixed-forward repeatability.

## Next actions and handoff

Stephen: merge PR #40 (or request changes), read the lease end time, decide on the reference-agreement result and the run definition (repeats, byte budget, tool durations). Operators: use `moe/OPERATIONS.md` with the private node runbook. Code is pushed; nothing pending locally except private notes.
