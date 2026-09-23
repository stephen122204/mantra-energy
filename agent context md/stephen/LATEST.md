# Latest published context: stephen

[Immutable turn record](turns/20260923-eviction-reservation.md)

## Task and current understanding
Repair a native CPU/CUDA device mismatch without bypassing validity checks or changing model arithmetic. Existing failed outputs remain preserved.
## Ideas and hypotheses
Unmanaged cache eviction selected an idle victim without reserving it. A demand can claim the same node before eviction executes. This source defect is reproduced by a deterministic interleaving test; correlation with a particular observed runtime failure still needs hardware evidence.
## Decisions and rationale
Add an explicit eviction reservation competing with demand on the same atomic state. Retain reservations across cache-wait predicates and until host movement/cache bookkeeping finishes. Demand waits for eviction and checks acquisition after prefetch.
## Changes and artifacts
Draft PR58; source69c8577. Separate native build and runtime environment queued; old installations remain intact. No math, tolerance, task or outcome-selection changes.
## Tests and evidence
Ten focused tests and two subtests passed, including a negative control reproducing select-then-evict and existing lifecycle/GIL checks. Actual native build, fixed-prefix numerical checks and repeated task checks are pending, not passed.
## Open questions and disagreements
The reservation repair is not yet certified as the cause/fix for all device mismatch reports. Investigate any remaining failure rather than forcing CPU/GPU copies or relaxing checks.
## Next actions and handoff
Complete separate build; require unchanged numerical agreement and repeated valid task execution before merge/recovery. Preserve all old failures and version recovery; use node-owned scheduling, never restart the retired client dispatcher.
