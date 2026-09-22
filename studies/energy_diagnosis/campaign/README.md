# Campaign execution ledger

`RunLedger` is the ED-04 execution layer. It is intentionally separate from the
planning-only generator under `docs/agent-context/starter/` and consumes the
shared contract-v0.1 `ExecutionRecord`.

The ledger uses SQLite transactions to claim one planned slot, persist stable
execution/attempt identities, retain terminal outcomes, and recover unfinished
work without erasing it. A retry is explicit and always creates a new linked
execution. JSONL, CSV, and validation-report exports are deterministic for a
given ledger.

The implementation is single-runner software. Claiming is serialized
by SQLite and returns `None` while any attempt is running, even if another
plan slot is pending. The runner must distinguish busy from exhausted using
the disposition counts and terminate owned work before finalizing a lease.
This protects one ledger; separate databases do not isolate shared hardware.

`CampaignSchedule.build(...)` performs reproducible seeded shuffling inside
declared preparation blocks; runs never cross block boundaries. Construct a
`BoundedCampaignRunner` with that schedule and provide a one-goal executor
callback to `run_next(...)`. The callback receives the claim, declared block,
requested resources, and a durable checkpoint writer. It returns an
`ExecutionOutcome` containing the existing contract-v0.1 record, artifact
references, and observed settings/resources/fidelity metadata. A callback
exception or an outcome that reports surviving owned work is not finalized,
so the global one-goal gate remains closed.

`recover_interrupted(session_id=..., clock_domain=..., ended_ns=..., reason=...)`
only recovers running attempts in the named session. Supply a known termination
endpoint from the original host/boot clock after owned work has stopped.
A timestamp from a restarted machine must not be substituted. With no known
endpoint, `record_unknown_interruption(...)` writes an explicit durable
checkpoint and leaves the attempt running for reconciliation. It does not
invent an endpoint or permit another goal. The ledger does not kill model/tool
processes or discover surviving processes.

For supervised campaigns, use the operator command instead of calling the API
manually. It previews by default and refuses to apply unless the bounded
supervisor has a terminal cleanup record and the operator attests that an
independent process check found no owned work remaining:

```bash
python -m studies.energy_diagnosis.campaign.recover \
  --campaign-dir "$RUNROOT/campaign" \
  --session-id "$SESSION_ID" \
  --clock-domain "$CLOCK_DOMAIN" \
  --ended-ns "$ORIGINAL_CLOCK_ENDPOINT_NS" \
  --reason "supervisor interrupted; owned work confirmed stopped" \
  --supervisor-status "$RUNROOT/supervisor/status.json"
```

Inspect the preview, repeat the same command with
`--apply --owned-work-terminated`, then resume through the ordinary launch
command. Never use a post-reboot monotonic timestamp or attest termination
without checking processes; leave the attempt unresolved when either fact is
unknown.

`export()` returns `plans`, `attempts`, `dispositions`, and `validation` paths.
`plans.jsonl` retains full definitions for unattempted slots and pending retry
requests; `attempts.jsonl` retains every realized attempt. The CSV is a latest
disposition summary, not a total-cost table: analysis must include earlier
failed attempts and separately measured preparation/backoff/session costs.
Keep the database and artifact root; JSON exports reference, but do not copy,
raw artifacts. Export only while the single writer is quiescent; each output
file is atomically replaced, not the entire four-file bundle.

The bounded runner adds `schedule.json` and `campaign-validation.json`.
Validation compares declared and observed settings/preparation, rejects
reported overlapping measurement domains or surviving work, and gives every
attempt an explicit analysis-eligibility decision. Failed, partial, divergent,
and unavailable observations remain in the raw export with exclusion reasons;
they are not silently dropped or converted to zero.

Valid goal-energy measurements must cover the entire goal window. Partial
readings retain covered joules, coverage, and reason; they are never promoted
to valid full-goal totals. Model timestamps must use the goal clock and fit
inside its interval. These checks do not prove physical domain coverage or
actual worker behavior; real executor and collector integrations must populate
the observed metadata and remain subject to Stephen's pilot/session gates.

## Fixture demonstration

Generate a five-slot simulated ledger containing a success, model failure,
verifier failure, interrupted/retried attempt, and unavailable measurement:

```bash
python -m studies.energy_diagnosis.campaign.demo \
  --source-commit YOUR_EXACT_40_CHARACTER_COMMIT \
  --out /tmp/ed04-ledger-demo
```

The output is fixture evidence only. It does not invoke a model, tools, Grace,
or any hardware collector. Simulated sessions and clock domains must be labeled
with `fixture`; unavailable energy remains JSON `null` with a reason.
