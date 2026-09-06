# Latest published context: stephen

[Immutable turn record](turns/20260906-student-device-guides.md)

# Turn summary: Stephen — student device guides and local lead education

## Task and current understanding

Stephen asked to remove his personal human guide from GitHub because his education/orchestration planning belongs outside the shared student material. He also requested concrete device targets and examples so students can picture what they are building.

## Ideas and hypotheses

Describing where each process runs and showing a concrete inspectable artifact should help students reason about their component without exhaustive code reading. One shared Grace study platform with three cooperating components is the current plan.

## Decisions and rationale

Removed Stephen’s personal human guide and live inbound links from the handoff branch. Preserved a local copy outside the team repository and excluded it from student bundles. Shared technical coordination and the per-turn context protocol remain. Added a guard against recreating the personal guide in the shared tree. Existing Git history was not rewritten; the current-tree deletion is not a historical purge.

Student guides distinguish development computers from the measured Grace Linux compute allocation. Target one A100 40GB GPU, with proposed 16 CPU cores/64GB host RAM, subject to scheduler policy, actual requirements and isolation. Official Grace hardware documentation was checked. The model uses the GPU; tools and verifier use host CPUs; actual inference, computation and measurement occur in the same allocated environment. Access and CPU energy remain preflight questions.

## Changes and artifacts

Commit bece8af on lead/named-kickoff-prompts updates PR #14. Alex’s guide illustrates the model connection and energy boundary; Aldric’s illustrates a fixed task, answer key and controlled CPU execution; Nitheesh’s illustrates a resumable controller and complete attempt record. Updated initial prompts, indexes and shared overview. Refreshed student guide copies and attachment packages; Stephen’s human guide is absent from the distributable bundle. No email content or mailbox was changed this turn.

## Tests and evidence

Setup/link checker and diff whitespace checks pass. Remote tree checks confirm the personal human guide is absent from both lead/named-kickoff-prompts and research/energy-diagnosis. Portable prompt copies match source and ZIP inspection confirms the personal guide is excluded. GitHub handoff-and-plan passed at https://github.com/stephen122204/alems-energy-diagnosis/actions/runs/34053315442. Working tree clean after push. No hardware job or model inference ran.

## Open questions and disagreements

The previous guide remains accessible in earlier Git commits; current files and bundles no longer contain it. PR #14 remains unmerged. Actual device assignment, reservation, energy permissions and isolation have not been established by this documentation.

## Next actions and handoff

Stephen reviews PR #14 and shares the updated student guides/prompts. Students begin local fixture work and use their concrete component examples to check behavior. Coordinate the shared Grace preflight and integration rather than pursuing unrelated per-person platform ports. Keep personal lead education outside shared source and publish only team-facing coordination and evidence.
