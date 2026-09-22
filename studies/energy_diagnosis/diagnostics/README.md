# Opt-in runtime and session diagnostics

These utilities package the previously local counter, fixed-input score and
session-support code. They do not launch on import or authorize a hardware run.
Use a clean checkout, a currently assigned node and an explicit time budget.
Results and configuration files belong outside the repository. Do not commit
weights, addresses, keys, raw task outputs or private discussion notes.

## What is included

- `qualify_counters`: two short repetitions of idle, eight CPU workers, one GPU
  worker, and combined activity. Supply `--backend-python`, `--allocation`,
  `--isolation-note` and a new `--output` directory. The isolation note is an
  operator statement, not a detector. `audit_counters DIRECTORY` independently
  checks complete filenames, endpoint values, validity and derived energy; it
  rejects wraps for separate inspection. This is not electrical calibration or
  a guarantee that all desired energy domains are available.
- `prepare_case`: encode a caller-supplied JSON case with original tokenizer
  files. Required text fields: `case_id`, `model_revision`, `prompt_text`,
  `continuation_text`. An optional `primer` contains prompt/continuation text.
  Existing token IDs must match; continuations are limited to 32 tokens. No
  hidden task/reference data or generated case files are included here.
- `capture_fixed_forward`: separate native-demand, native-preparation and
  standard-reference captures. Forced prefixes and fresh target KV state are
  explicit. Hashes bind configuration, checkpoint, tokenizer, source and scores.
  Preparation only qualifies if owned nonzero transfers actually complete.
  Captures preserve scores even when this condition fails.
- `compare_fixed_forward`: reject incompatible identity/state, changed hashes,
  duplicate captures and unequal token prefixes before comparing scores. The
  existing absolute/relative tolerances remain 0.02/0.01. When a primer is used,
  both primer and target comparisons must pass. These are numerical diagnostics,
  not full-task correctness or energy acceptance.
- `run_qualification`: demand twice, repeatability comparison, preparation,
  preparation comparison, reference, reference comparison. Stops at the first
  failing stage and retains `stages.json`; missing later reports mean unexecuted
  stages. There are four captures, each with its own timeout. Use the bounded
  launcher for an additional overall budget.
- `run_bounded`: POSIX job lock, durable `status.json`, `run.log`, elapsed-time
  limit, UTC cutoff check and owned process cleanup: the child's process group
  first (`--grace-seconds`, default 20, before SIGKILL), then every descendant
  recorded before the stop, including workers that started their own session.
  `cleanup_complete` is true only when none of those processes survives;
  otherwise `surviving_pids` is recorded and recovery refuses the status. A
  process spawned after the pre-stop snapshot and outside the group can be
  missed. A completed status means the command exited zero, not that
  measurements are scientifically valid.
- `copy_results`: periodic SSH/rsync copies into a new local directory and final
  SHA-256 verification after a recognized terminal job status. Failed experiment
  status remains visible even when copying succeeds. Requires **rsync 3+** on the
  receiving computer, SSH key and previously verified known-host entry. The
  receiver must stay awake and connected. Remote output must be quiescent at
  final verification; do not include model caches or symlinks in its directory.
- `setup_a100_node.sh`: explicit Ubuntu 24.04/CUDA 12.6/A100 bootstrap. Arguments:
  existing repository, expected commit, new absolute work directory. Installs
  packages using available sudo, creates separate environments, downloads the
  pinned model and builds the pinned backend. Requires adequate disk space,
  network and an assigned node. Does not format disks, configure SSH, grant
  telemetry permissions or reserve hardware. A partial setup leaves its files
  for inspection; it does not silently resume or overwrite an existing directory.

## Usage

Run from the repository root using `python -m` and the environment appropriate
to the command; fixed-score work requires the backend Torch/Transformers stack.
Use `--help` for every module's exact input arguments. For example, on the node:

```bash
python -m studies.energy_diagnosis.diagnostics.run_bounded \
  --cwd "$PWD" --output "$RESULTS/job" --lock "$RESULTS/gpu.lock" \
  --seconds "$JOB_SECONDS" --cutoff-utc "$CUTOFF_UTC" -- \
  "$BACKEND_PYTHON" -m studies.energy_diagnosis.diagnostics.run_qualification \
  --config "$CONFIG" --case "$CASE" --output "$RESULTS/captures"
```

Set each variable explicitly for the current session. Keep the output directory
outside the checkout so source cleanliness remains meaningful. The launcher
requires at least 60 seconds beyond the requested job budget before its cutoff;
choose an earlier cutoff to allow final exports and off-node copying. Launch
under the session's approved detached service/shell if it must survive logout.
Reservation start alone does not boot an instance, configure it or launch work.

Commands must not daemonize out of their process group. The fixed-score capture
supervisor forwards cancellation by terminating its detached worker group. This
is not cgroup containment; abrupt machine failure or SIGKILL of the supervisor
can prevent cleanup/status publication. Never start a second measured job until
the prior job and its GPU work have terminated.

## Evidence and limitations

The source helpers were exercised in a bounded Linux hardware session; their
portable packaging and new cancellation/copy failure handling require the next
on-node smoke check. CPU fixtures test score-prefix alignment, fresh target KV,
effective-transfer criteria, provenance rejection, interruption, lock exclusion,
copy integrity and fail-fast sequencing. CI does not run GPU jobs or SSH into an
allocation. A zero-expert preparation capture must remain unqualified. Fix the
input coverage and rerun; do not weaken this check or widen tolerances to pass.

Use original tokenizer bytes when preparing new cases. Existing case rebinding
requires preserved source hashes and identical specified IDs; this does not
establish arbitrary tokenizer equivalence. Runtime measurements remain CPU
package and GPU board only where those domains are available and validated.

## Terminal snapshots and serial batch coordination

`archive_results` compresses only new/changed files and retains a full hash
manifest. Supply explicit remote repository/interpreter, result directory,
relative terminal status, host, SSH identity, known-hosts file and a new local
destination. A subsequent snapshot can use `--previous-receipt`. Keep every
bundle and receipt in its chain. `--restore-receipt RECEIPT --destination NEW_DIR`
verifies the complete chain and reconstructs the latest view. Integrity failures
are distinct from retryable SSH transport failures. No snapshot is accepted from
a running job or a tree that changes while being archived.

`batch_coordinator --spec PRIVATE_JSON --output LOCAL_DIRECTORY` runs on a POSIX
receiving host and resumes from its saved state with the **same** specification.
The private specification contains:

- `host`, `identity_file`, `known_hosts`;
- absolute `remote_directory`, `remote_repository`, `remote_python`;
- UTC `cutoff_utc`, positive `retry_seconds`, `first_poll_delay_seconds`,
  and `minimum_batch_seconds` (include startup, measurement, cleanup and backup);
- an ordered `batches` list, each with a unique single-component `id`, launch
  `argv`, and result-relative `status` and `log` paths.

Each launch command must itself use a bounded supervisor, enforce exclusive
measurement periods and publish its terminal status. The coordinator does not
supply hardware isolation. For sampled process guards, arrange that new SSH
sessions cannot start during measurement and restore access after each batch;
otherwise polling itself introduces unrelated work. Use a bounded recovery
mechanism for any temporary access restriction.

A remote intent marker prevents duplicate dispatch when SSH loses the launch
reply. An interrupted/ambiguous launch is retained for investigation, not
silently repeated. Transport failures are retried within the cutoff. Completed
results are verified off-node before another batch launches; failed remote jobs
are backed up and stop the sequence. Integrity errors stop rather than retrying
until something passes. A changed specification is rejected on resume. The
receiving computer must stay awake and connected; if it is unavailable the
current remote bounded batch can finish, but subsequent batches wait.
