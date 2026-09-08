# Latest published context: stephen

[Immutable turn record](turns/20260907-ed01-contracts-and-utf8-merged.md)

# ED-01 shared contracts merged (#21); publisher UTF-8 fix merged (#20)

## Task and current understanding

Clear the remaining items on Stephen's side of the dependency chain before the students' agents start their next milestones: the concrete shared interface (ED-01, gate G0) and the shared Windows tooling follow-up. Both are merged; the open PR list is empty.

## Ideas and hypotheses

With the record types in one module, three components developed in parallel should meet at the local integration gate (G2) with field-level rather than structural mismatches. The contract deliberately encodes the semantics that were previously only prose: null-not-zero energy, separate execution/verifier/measurement status, span dependency order, simulated flag.

## Decisions and rationale

- ED-01 v0.1 is dataclasses plus JSON, no dependencies, so every component can consume it without new packages. Callable and module names for the runner, executor and collector stay with their milestones; only the records are shared.
- Changes to records go through a PR against `studies/energy_diagnosis/contracts.py`: additive fields in minor versions, renames bump `CONTRACT_VERSION`. Do not keep local copies of the types.
- The publisher now reads and writes notes as UTF-8 because every guide contains characters outside the Windows default code page.

## Changes and artifacts

- `eb49e72` (#21): `studies/energy_diagnosis/contracts.py`; examples in `studies/energy_diagnosis/fixtures/contract_examples/` (task spec, four settings, verified run, completed-but-wrong run, timeout with missing energy); `tests/test_study_contracts.py`; CI step; pointers in `docs/agent-context/04-interfaces-and-data.md` and the study README.
- `b58984a` (#20): publisher UTF-8 I/O; regression test under a forced ASCII locale; the Windows path simulation test is skipped on native Windows.

## Tests and evidence

- CI on the merged heads: setup check, 6 publisher tests, 12 workload tests, 10 contract tests.
- Contract bridge test maps the merged ED-03 verifier output into `VerifierResult` and embeds it in an `ExecutionRecord`.
- UTF-8 regression test fails against the previous publisher (UnicodeEncodeError) and passes now. No native Windows run.

## Open questions and disagreements

- Alex, Aldric and Nitheesh: confirm your next milestone consumes these types, and open a small PR if a field is missing. That is the G0 producer/consumer check.
- Native Windows confirmation of the workload, publisher and contract tests is still owed by the Windows user.
- ED-12 (individual Grace accounts, allocation, scheduled session) and the node-side RAPL check remain the hardware prerequisites for ED-05 and ED-07.

## Next actions and handoff

- Students: fetch integration, complete the startup checklist, publish the full-milestone acknowledgment, continue.
- Stephen: ED-12 access, the comparison specification for ED-10, local integration command (G2) once the first executor and ledger PRs land.
