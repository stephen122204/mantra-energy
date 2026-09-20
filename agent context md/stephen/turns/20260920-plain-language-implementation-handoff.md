# Current implementation handoff and named responsibilities

## Task and current understanding

Updated the human guides and agent entry points in fresh clone from integration 838ac3a0042eb6ce1307d0cc37be8f3166155ee2. Documentation PR #37 at a1d8914211e7a429081070a05c9c34a9518e68ad provides current plain-language responsibilities and detailed implementation acceptance. No executable code or hardware changed.

## Ideas and hypotheses

Older maintained guides point to first issues and Grace-only setup. A current, explicitly prioritized handoff prevents agents from restarting completed components or mistaking historical run counts for launch instructions. This is a documentation correction, not a new runtime result.

## Decisions and rationale

Alex owns measurement validity; Aldric owns equivalent useful work and independent answer checks; Nitheesh owns complete records, unattended execution and verified exports. Stephen owns model-runtime changes, standard-model agreement and shared starting-state/configuration decisions. Develop independently with fixtures; use one coordinated queue for measured hardware runs. Keep ordinary failed attempts distinct from defects that invalidate measurements or records.

## Changes and artifacts

PR: https://github.com/stephen122204/alems-energy-diagnosis/pull/37
Branch: stephen/plain-language-team-handoff

Read these CURRENT documents now, including while the documentation PR is pending:
- https://github.com/stephen122204/alems-energy-diagnosis/blob/stephen/plain-language-team-handoff/agent%20context%20md/CURRENT_HANDOFF.md
- https://github.com/stephen122204/alems-energy-diagnosis/blob/stephen/plain-language-team-handoff/agent%20context%20md/BATCH_ACCEPTANCE.md
- Your named HUMAN_START_HERE.md on that branch.

Fetch the branch and read with git show if preserving an older working checkout. Do not merge or reset working code merely to read instructions. The new handoff is linked from root/startup/full-assignment and named prompt files in PR37. Historical milestone checklists remain coverage records; reuse completed work and identify missing evidence. Private research discussion, presentation content, connection details and raw results were not published.

## Tests and evidence

`python3 scripts/check_energy_diagnosis_setup.py`: PASS, portable links/provenance/planning-readiness checks only.
`git diff --check`: PASS.
Documentation-only change; no model execution, counter qualification, download, session launch or expensive rerun. No claim of new hardware acceptance. PR34/35/36 remained open at inspection; their stacked additions are not all integrated.

## Open questions and disagreements

Current instance login, execution revision, paths, configuration and budget must be supplied/verified for hardware work. Standard-model numerical agreement and actual preparation in the dedicated fixed-input check remain open in the supplied handoff. Stephen owns those runtime decisions. Existing code and fixture tests can progress independently. Historical hardware evidence is version-specific and stored privately.

## Next actions and handoff

Each student agent reads the documents above and reports the full owned milestone status, exact tested code, evidence, remaining dependencies and next action, then continues ready implementation. Complete the small task/check/measurement/record/export path using existing components. Do not recreate earlier work or launch an old planning matrix. Stephen reviews PR37 and retains merge authority. The feature branch is pushed; the maintained files await merge, while this narrow technical handoff makes the instructions discoverable on integration immediately.
