# Operating a bounded native batch

One documented command per approved batch: launch unattended, inspect, stop
safely, recover, resume, export and copy off the node. Replace every
placeholder explicitly; the commands refuse missing or placeholder values where
they can. Keep addresses, keys, private configuration and raw results outside
Git. `$W` is the private work directory holding the study interpreter
(`$W/study-env/bin/python`), the backend interpreter, the clean checkout at the
execution commit (`$W/repo`) and the private native configuration.

## Launch (survives logout)

```sh
export PYTHONPATH=$W/repo CUDA_VISIBLE_DEVICES=0
RUN=$W/artifacts/BATCH_NAME; mkdir -p "$RUN"
cd $W/repo && test -z "$(git status --porcelain)" && git rev-parse HEAD > "$RUN/execution-commit.txt"
nohup $W/study-env/bin/python -m studies.energy_diagnosis.diagnostics.run_bounded \
  --cwd $W/repo --output "$RUN/job" --lock $W/gpu.lock \
  --seconds BUDGET_SECONDS --cutoff-utc RESERVATION_CUTOFF_MINUS_COPY_MARGIN -- \
  $W/study-env/bin/python -m studies.energy_diagnosis.moe.run --mode native \
  --config $W/PRIVATE_CONFIG.json --backend-python $W/backend-env/bin/python \
  --allocation-id ALLOCATION_ID --isolation "VERIFIED_ISOLATION_STATEMENT" \
  --output "$RUN/campaign" --task all --policies demand,fixed --byte-budget 536870912 \
  --repeats REPEATS --max-runs SLOTS --deadline 600 > "$RUN/launcher.log" 2>&1 &
```

The launcher holds the GPU lock; a second launch exits 75 with
`status: blocked_by_other_job`. `--seconds` must leave at least 60 s before the
cutoff, and the cutoff must leave time to export and copy. The first goal in a
fresh offload directory includes the one-time checkpoint conversion inside its
startup window; the example goal deadline (600 s) includes that startup.
An explicit `--deadline` may be increased up to 1800 s when initialization
requires it. Preserve the same goal limit across compared settings, record it
in the manifest, and size the supervisor budget and reservation cutoff for
the whole batch. This does not remove the time limit or authorize extra runs.

## Inspect

```sh
cat "$RUN/job/status.json"        # starting|running|completed|failed|timed_out|interrupted|blocked_by_other_job
tail "$RUN/job/run.log"           # campaign stdout/stderr (JSON result at the end)
ls "$RUN/campaign/goals"          # one directory per attempt (record.json, measurement.json, ...)
tail "$RUN/campaign/backend-logs/"*.log
```

Low GPU utilisation during startup is expected (checkpoint load); watch the
backend log advance instead.

## Stop safely

```sh
kill -TERM "$(python3 -c "import json;print(json.load(open('$RUN/job/status.json'))['supervisor_pid'])")"
```

The supervisor forwards the signal to the campaign's process group; the
campaign terminates its owned worker and tool processes, exports the ledger and
exits 130. The supervisor then terminates any recorded descendant and writes
`status: interrupted` with `cleanup_complete: true`, or `surviving_pids` when
something outlived cleanup. Check `ps -o pid,args -u "$USER" | grep -E
'moe.worker|multiprocessing'` before recovering.

## Recover an interrupted attempt

```sh
$W/study-env/bin/python -c "
from studies.energy_diagnosis.campaign import RunLedger
with RunLedger('$RUN/campaign/ledger.sqlite', artifact_root='$RUN/campaign') as l:
    for a in l.running_attempts(): print(a.attempt_id, a.session_id, a.clock_domain, a.started_ns)"
ENDED=$($W/study-env/bin/python -c "import time;print(time.monotonic_ns())")   # same boot only
$W/study-env/bin/python -m studies.energy_diagnosis.campaign.recover --campaign-dir "$RUN/campaign" \
  --session-id SESSION --clock-domain CLOCK_DOMAIN --ended-ns "$ENDED" \
  --reason "WHY" --supervisor-status "$RUN/job/status.json"                     # preview
# then the same command with: --apply --owned-work-terminated
```

After a reboot the monotonic clock is not comparable; leave the attempt for
manual reconciliation rather than inventing an endpoint.

## Resume

Rerun the launch command with the same `--output "$RUN/campaign"` and a new
launcher directory (`$RUN/job2`). Completed attempts are never repeated; an
interrupted slot stays `incomplete` under the default retry limit. A changed
revision, configuration or task definition is refused by the manifest check.

## Export, audit and copy off the node

```sh
$W/study-env/bin/python -m studies.energy_diagnosis.moe.audit_windows "$RUN/campaign"   # exit 0: replayed counters reconcile
ls "$RUN/campaign/exports"      # attempts.jsonl plans.jsonl dispositions.csv validation.json campaign-validation.json schedule.json
cp -r "$RUN/job" "$RUN/job-final"   # optional: the launcher status must live inside the copied tree
```

On the receiving computer (rsync 3 required; macOS ships openrsync, install
rsync separately and put it first on `PATH`):

```sh
python -m studies.energy_diagnosis.diagnostics.copy_results \
  --host USER@NODE --identity-file KEY --known-hosts VERIFIED_KNOWN_HOSTS \
  --remote-directory $W/artifacts/BATCH_NAME --remote-status job/status.json \
  --destination NEW_LOCAL_DIRECTORY --cutoff-utc RESERVATION_CUTOFF --interval 60
```

Exit 0 means every remote file was re-hashed on the node and matches the local
copy (`copied_and_verified`); 1 means a mismatch; 2 means the cutoff arrived
before final verification (the latest partial copy is retained).


## Balanced repeated comparisons

For a supplied two-policy repeated batch, `--comparison-order balanced-pairs`
requires an even `--repeats` value. Within each task, session, preparation and
input/model/verifier identity, the first of two successive repetitions gets a
seeded random policy order and the next gets its reverse. Every setting therefore
appears first equally often. Existing preparation blocks and task order stay in
place; this option does not randomize unrelated hardware/setup blocks.

The mode, seed and actual order are recorded in the immutable manifest and
schedule. Resume preserves them; changing the order mode requires a new output
directory. The default remains the existing independent within-block shuffle.
This controls ordering only: it does not establish an adequate repetition count,
consistent warm-up/cache state, thermal stability, exclusive hardware use or
measurement validity. Those checks remain required for the supplied batch.

## Guarded exclusive execution

On a separately reserved Linux node, save a private process snapshot with
`python -m studies.energy_diagnosis.diagnostics.process_guard --output BASELINE.json`.
Review its existing users and processes before accepting it. A snapshot of a busy
node is not authorization to keep the unrelated work. Stop or coordinate other
jobs first; do not automatically approve the baseline during every launch.

Pass `--process-baseline BASELINE.json` to `run_bounded`. It observes processes
about twice per second, retaining PID/start-time/user/name and CPU-time snapshots,
without collecting command lines or environments. Unapproved user-space processes,
a different boot or existing background usage above 0.25 CPU-seconds per elapsed
second abort the batch with exit 76 and `measurement_batch_valid: false`.
Owned descendants and launcher ancestors are distinguished from other work;
previously observed owned workers remain cleanup targets if reparented. Missing
process access fails closed. Kernel threads are excluded from process admission.

The threshold is an explicit detector limit, not evidence that smaller background
activity has no effect. Sampling can miss short processes and does not provide
access control or perfect isolation. Use a dedicated reservation, one operator,
the shared hardware lock and the saved observations together. Do not open new SSH
monitor sessions, install packages, build, download or copy backups during guarded
measurements. Schedule inspection and backups between bounded batches. On any
guard failure retain all artifacts, mark the affected batch invalid for energy
comparisons and investigate before resuming; do not silently retry it as clean.
