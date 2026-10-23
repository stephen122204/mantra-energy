# Initialized-model counter checkpoint implementation

## Task and current understanding
PR34 now adds real counter checkpoints around initialized-model task execution while retaining complete outer goal accounting. Branch stephen/moe-runtime-validation, implementation e0155e0. PR remains draft and unmerged. This handoff covers implementation only.

## Ideas and hypotheses
Counter acquisition must be serialized with periodic sampling. A teardown callback may join a sampling thread, so teardown must not hold the measurement lock. A neighboring JSON file without a ledger registration is not measurement evidence.

## Decisions and rationale
Use explicit immutable checkpoints, all intervening counter readings, per-domain validity, and the existing raw acquisition brackets. Split task-work drain from model release. Keep fresh-process cache semantics and the outer deadline explicit; do not claim persistent serving. Preserve the default non-MoE executor lifecycle. Bump execution protocol to planned-body-initialized-window-v1 and require a fresh output directory.

## Changes and artifacts
MeasurementSession and NodeMeasurement expose checkpoint and measure_between. Lifecycle exposes idempotent settle_work and rejects further generation/admission after settling. The MoE executor measures task setup, planning, inference, tools and verification before model release, registering initialized-model-window.json. Summary output reports initialized, before and after energy only from ledger-registered, hash-verified artifacts. Missing values remain unavailable; failed attempts remain in totals; unconfirmed final ownership invalidates coverage. README documents exact scope.

## Tests and evidence
190 runtime tests plus five subtests and 20 MoE pipeline tests pass locally. Setup checker and diff checks pass. Tests exercise costly load/release, task/verifier containment, energy partition, counter wraps, missing readings, concurrent samples, teardown locking, failure cleanup, zero-success accounting, and unregistered artifact rejection. GitHub checks at the new head are pending when this note is prepared. Earlier head 1325cb9 passed all eight jobs. Native runtime 847b384 was qualified with two completed data executions and independently replayed counters; e0155e0 has not run on hardware. Do not transfer old hardware evidence to the new checkpoint protocol.

## Open questions and disagreements
Native checkpoint synchronization, acquisition timing, failure cleanup and counter replay still need a bounded hardware qualification. Full model fidelity and task-contract qualification remain open. No persistent model/cache reuse is implemented. CPU package plus GPU board counters are not whole-node measurements.

## Next actions and handoff
Check current PR34 CI. On the next assigned hardware session inventory the actual node, verify sensor permissions and isolation, deploy the exact tested revision and run the bounded qualification with a fresh output directory. Independently replay outer and initialized portions, verify model/tool/verifier containment and final worker termination. Preserve failed records. Do not launch or extend a hardware allocation without the assigned session and budget. Stephen retains merge authority.
