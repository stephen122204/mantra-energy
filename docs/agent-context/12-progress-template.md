# Progress handoff template

Copy this template to an issue comment or a dated team progress file. Fill with facts; delete inapplicable sections.

## Identity

- Person / issue:
- Repository / branch / full source commit:
- Baseline and relevant upstream differences:
- Session date and environment:

## Completed behavior

What now works, for which concrete input, and how it differs from before. Link the small PR and relevant artifacts.

## Evidence

| Claim | Evidence level | Command or procedure | Result / artifact |
|---|---|---|---|
| Fill | Proposed / code-reviewed / fixture-tested / hardware-tested / campaign-validated | Exact reproducible action | Actual output and limitations |

List tests that failed or were not run, with reasons. State whether an actual model ran and whether actual energy readings were collected. A provider fixture is not a live experiment.

## Hardware run, if any

- Job/allocation/session and device identities:
- Requested versus actual resources; sharing/isolation:
- Model/runtime and task/verifier hashes:
- Energy domains/units and coverage:
- Run IDs, success/failure counts and missing measurements:
- Actual reservation/elapsed time and artifact storage:

## Integration

Files/interfaces changed, downstream impact, compatibility concerns, migration needs and which collaborator must update. No change to shared schema should be hidden in a status report.

## Remaining work

One next bounded action, concrete blocker if any, and useful independent work that can continue. Separate required user input from optional preferences.

## Scientific limits

What these results do not yet establish: energy-saving effect, correctness beyond fixtures, hardware validity, held-out generalization, novelty or publication readiness as applicable.

