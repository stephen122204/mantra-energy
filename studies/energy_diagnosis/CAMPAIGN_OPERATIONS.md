# Campaign operations (operator runbook)

This runbook executes a frozen campaign plan. Operators do not change the plan, the checkout,
environments, host settings or any file under the result root. Every decision about tasks, arms,
repetitions, order and validity is already in the plan; your job is to launch, check in the
maintenance windows, and keep verified backups.

## Rules that protect the measurement

1. **Never log in to the node outside a maintenance window.** Any new login during a measured
   batch is detected by the process guard; the batch is kept but marked invalid and the campaign
   stops for review. List the windows from your laptop (no login needed):
   `python -m studies.energy_diagnosis.diagnostics.campaign_plan --plan PLAN.json --windows 8`
2. Do not start other work on the node (builds, notebooks, downloads) at any time during a campaign.
3. Do not edit, pull or rebuild anything in the campaign checkout or environments.
4. Never delete or rename a batch directory, a dispatch intent or a snapshot. Failed batches are data.
5. A task that the model fails (wrong answer, budgets, context, deadline) is a normal result. It does
   not stop the campaign and must not be rerun.

## Before launch (one login, before the first batch)

```
cd REMOTE_REPOSITORY            # the frozen checkout named in the plan
PYTHONPATH=$PWD REMOTE_PYTHON -m studies.energy_diagnosis.diagnostics.campaign_check preflight --plan PLAN.json
```
Expected: `"passed": true`. Any `false` check: stop and report it; do not work around it.

Generate the node specification (deterministic; the same plan always gives the same batches):
```
PYTHONPATH=$PWD REMOTE_PYTHON -m studies.energy_diagnosis.diagnostics.campaign_plan --plan PLAN.json --output NODE_SPEC.json
```
Expected: one JSON line with `batches`, `plan_sha256` and `estimated_hours_excluding_windows`.

Launch (fully detached; the command returns at once and survives logout):
```
setsid -f env PYTHONPATH=$PWD REMOTE_PYTHON -m studies.energy_diagnosis.diagnostics.node_batches \
  --spec NODE_SPEC.json --output NODE_OUTPUT > NODE_OUTPUT.launch.log 2>&1 < /dev/null
exit
```
Log out immediately. The scheduler waits for the next allowed slot by itself. Do not use
`cd DIR && nohup ... &`: the backgrounded `&&` list keeps the login session open.

## During the campaign (inside maintenance windows only)

Status (read-only):
```
PYTHONPATH=$PWD REMOTE_PYTHON -m studies.energy_diagnosis.diagnostics.campaign_check status --plan PLAN.json
```
- `node_state.status`: `maintenance_window` or `between_batches` = healthy; `measuring` should not
  appear inside a window; `completed` = done; `stopped` = see Recovery.
- `protocol_invalid`: must be empty. Anything listed stops the campaign (see Recovery).

Backups from your laptop (the receiver only connects inside windows and verifies every snapshot):
```
python -m studies.energy_diagnosis.diagnostics.receive_node_batches --spec NODE_SPEC.json --output LOCAL_BACKUP_DIR
```
Leave it running; a sleeping laptop simply resumes in a later window. Every received batch has
`LOCAL_BACKUP_DIR/<batch>/receipt.json` with `"status": "verified"`.

## After completion

1. In a window, confirm `node_state.status == "completed"` and `protocol_invalid == []`.
2. Let the receiver fetch the remaining snapshots (it exits by itself when the node reports
   completed or stopped).
3. Verify an independent restore:
```
python -m studies.energy_diagnosis.diagnostics.archive_results --restore-receipt LOCAL_BACKUP_DIR/<last batch>/receipt.json --destination RESTORE_DIR
```
Expected: exit 0, and `RESTORE_DIR/<batch>/job/status.json` exists for every batch.
4. Copy `LOCAL_BACKUP_DIR` to the second storage location named in the plan and record its checksum.

## Recovery

| Symptom (`campaign_check status`) | Meaning | Action |
|---|---|---|
| `stopped`, error `invalid batch retained` and a batch with job `interference_detected` | someone/something started a process during measurement | Do not rerun it. Report the batch id and time. A reviewer decides whether to resume with a new plan revision. |
| `stopped`, a batch with `protocol_valid: false` | measurement check failed (missing energy domain, audit) | Report; do not resume. |
| `stopped`, error `node cutoff reached` or `insufficient next-batch time budget` | the plan's cutoff is near | Normal end; fetch backups. |
| `stopped`, error `low disk` | storage floor reached | Report; never delete results to make room. |
| `stopped`, error `ambiguous prior dispatch` | the node or scheduler died while launching a batch | Report; a reviewer inspects `dispatch/<id>.json` and that batch directory. |
| scheduler not running, state `between_batches` or `maintenance_window` (e.g. after a reboot) | scheduler died between batches | In a window: run preflight, then relaunch the same command with the same NODE_SPEC and NODE_OUTPUT. Finished batches re-verify and are never repeated. |
| scheduler not running, state `measuring` | node or scheduler died during a batch | Relaunching stops with `existing batch not terminal`: that batch is not adopted or repeated. Report the batch id; a reviewer decides. |

Relaunching with the same specification never repeats a batch: completed batches are skipped after
their snapshots re-verify, and an interrupted or uncertain batch stops the scheduler instead.
