# Expert-preparation arms and usefulness accounting

`--policies` selects arms (comma-separated). All arms share the model, cache
size, prompt bytes and byte budget unless stated.

| Arm | When it prepares | What it selects |
|---|---|---|
| `demand` | never | nothing; experts load on demand |
| `fixed` | each tool pause | non-resident experts used earlier in the goal, most routed tokens first, up to `--byte-budget` |
| `history` | each tool pause | as `fixed`, at most 8 experts |
| `bounded` | each tool pause | as `fixed`, budget capped at `--bytes-per-second` × `--expected-pause-seconds`; demand-only without both |
| `random` | each tool pause | the `fixed` candidate pool and budget in seeded random order (`--random-seed`) |
| `static` | once, after model initialization and before the first model call | a development profile's ranked experts, up to the byte budget; nothing at pauses |
| `future` | each tool pause | **diagnostic, not deployable**: experts the next model call used in a reference run of the same task |
| `builtin` | during generation (backend) | MoE-Infinity's own activation-aware prefetcher (`prefetch=True` for this arm's backend only); nothing at pauses |

`static` and `future` need data built from recorded development runs and
passed with `--policy-data static=PATH` / `--policy-data future=PATH`. The file
hash is part of the setting identity:

    python -m studies.energy_diagnosis.moe.expert_profile profile --campaign DEV --output profile.json
    python -m studies.energy_diagnosis.moe.expert_profile future  --campaign DEV --output trace.json

Build profiles from development goals only. The future trace assumes the
evaluated goal follows the reference goal's path; paired requests are checked
to be identical, but a diverging path makes the trace stale.

## Usefulness

`python -m studies.energy_diagnosis.moe.audit_usefulness --campaign RUN`
classifies every completed preparation exactly once:

- `used_resident`: requested later and resident at its first dispatch;
- `evicted_before_use`: requested later but not resident at its first dispatch;
- `replaced_unused`: prepared again before any use;
- `unused_at_goal_end`.

It reports bytes per class, the phase (prefill or decode) of first use, bytes
by preparation source (`ahead` or pause), incomplete transfers by native
outcome, and dispatches to non-resident experts per phase. The audit fails if
any completed transfer has no class or two. With the backend prefetcher off,
`used_resident` means the prepared copy survived until used; under `builtin`
the inference does not hold, and that arm prepares nothing itself.
Transfer timing relative to tool bodies is `audit_transfers.py`.
