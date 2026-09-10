# Campaign execution ledger

`RunLedger` is the ED-04 execution layer. It is intentionally separate from the
planning-only generator under `docs/agent-context/starter/` and consumes the
shared contract-v0.1 `ExecutionRecord`.

The ledger uses SQLite transactions to claim one planned slot, persist stable
execution/attempt identities, retain terminal outcomes, and recover unfinished
work without erasing it. A retry is explicit and always creates a new linked
execution. JSONL, CSV, and validation-report exports are deterministic for a
given ledger.

The initial implementation is single-runner software. Claiming is serialized
by SQLite and returns `None` while any attempt is running, even if another
plan slot is pending. The runner must distinguish busy from exhausted using
the disposition counts and terminate owned work before finalizing a lease.
This protects one ledger; separate databases do not isolate shared hardware.

`recover_interrupted(session_id=..., clock_domain=..., ended_ns=..., reason=...)`
only recovers running attempts in the named session. Supply a known termination
endpoint from the original host/boot clock after owned work has stopped.
A timestamp from a restarted machine must not be substituted. With no known
endpoint, retain the running record and artifacts for reconciliation; explicit
unknown-endpoint/checkpoint recovery is a remaining NI2 integration requirement.
The ledger does not kill model/tool processes or discover surviving processes.

`export()` returns `plans`, `attempts`, `dispositions`, and `validation` paths.
`plans.jsonl` retains full definitions for unattempted slots and pending retry
requests; `attempts.jsonl` retains every realized attempt. The CSV is a latest
disposition summary, not a total-cost table: analysis must include earlier
failed attempts and separately measured preparation/backoff/session costs.
Keep the database and artifact root; JSON exports reference, but do not copy,
raw artifacts. Export only while the single writer is quiescent; each output
file is atomically replaced, not the entire four-file bundle.

Valid goal-energy measurements must cover the entire goal window. Partial
readings retain covered joules, coverage, and reason; they are never promoted
to valid full-goal totals. Model timestamps must use the goal clock and fit
inside its interval. These checks do not prove physical domain coverage or
actual worker behavior; NI2/NI3 must connect and validate the real producers.

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
