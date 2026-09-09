# Campaign execution ledger

`RunLedger` is the ED-04 execution layer. It is intentionally separate from the
planning-only generator under `docs/agent-context/starter/` and consumes the
shared contract-v0.1 `ExecutionRecord`.

The ledger uses SQLite transactions to claim one planned slot, persist stable
execution/attempt identities, retain terminal outcomes, and recover unfinished
work without erasing it. A retry is explicit and always creates a new linked
execution. JSONL, CSV, and validation-report exports are deterministic for a
given ledger.

The initial implementation is single-runner software. Concurrent calls are
serialized by SQLite and cannot claim the same plan slot, but ED-04 does not
authorize concurrent measured goals.

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
