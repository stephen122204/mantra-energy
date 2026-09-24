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
| `builtin` | fixture only; native execution currently rejected | Activation has not been qualified in the pinned backend; a configuration flag alone is insufficient |

`static` and `future` need data built from recorded development runs and
passed with `--policy-data static=PATH` / `--policy-data future=PATH`. The file
hash is part of the setting identity:

    python -m studies.energy_diagnosis.moe.expert_profile profile --campaign DEV --output profile.json
    python -m studies.energy_diagnosis.moe.expert_profile future  --campaign DEV --output trace.json

Build profiles from development goals only. The future trace assumes the
evaluated goal follows the reference goal's path. Compare recorded requests
and outputs separately; the launcher does not certify path equivalence. The
builder maps actual tool pauses to the following model call, including model
turns that recover from malformed responses without executing a tool. Missing
task/pause entries fail instead of silently acting as demand-only.

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
any completed transfer has no class or two. Empty/incomplete goals, duplicate
transfers, invalid byte counts and unknown residency are rejected.
`used_resident` records residency at first dispatch; it does **not** prove that
the same prepared copy survived, that a demand copy was avoided, or that latency
or energy decreased. Intervening eviction/reload requires a placement-event join.
Transfer timing relative to tool bodies is `audit_transfers.py`.
