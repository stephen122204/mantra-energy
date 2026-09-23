# Latest published context: stephen

[Immutable turn record](turns/20260923-native-gil-wait.md)

## Task and current understanding
Stephen owns native runtime acceptance. Repeated generation still stalled after the notification repair, so that build is not accepted. Captured native stacks now show the main Python thread waiting for expert completion while the execution worker waits to acquire the GIL during tensor destruction.

## Ideas and hypotheses
The wait_expert binding retained the GIL throughout WaitHiddenStates. A worker that needs Python reference-count cleanup cannot progress while the caller holds that lock and awaits its completion. This is a captured lock dependency, not a conclusion from a successful retry.

## Decisions and rationale
Release the GIL for the native wait through pybind's call_guard; the wrapper reacquires it before converting the returned tensor. Retain the separate notification synchronization repair. Preserve failed builds and records, and requalify a new installation. No task, arithmetic, timeout or numerical-tolerance changes.

## Changes and artifacts
Draft PR55 updated at e3c434fc0ab4ba0305fc358390ae72dfc8e13de4. Added native binding guard and tests/test_moe_native_gil_wait.py. The test uses PyTorch's bundled pybind headers and a C++ compiler; it explicitly skips when those prerequisites are absent, so native qualification runs it in the backend environment.

## Tests and evidence
The regression compiles a worker requiring the GIL while its Python caller waits: the guarded binding completes, and removing the guard produces the expected subprocess timeout. This test passed locally. Six portable synchronization/lifecycle checks passed. Separate native build, numerical comparisons and repeated-generation checks are running and are not yet accepted. Earlier failed qualification was backed up and independently restored.

## Open questions and disagreements
Native qualification and repetition remain necessary despite the targeted regression. CI alone is insufficient. Do not interpret preserved diagnostic energy as experiment data or treat a successful retry as resolution.

## Next actions and handoff
Follow the existing bounded qualification job, then audit its terminal output and fingerprints. Merge only after review and qualification. New accepted builds require new execution definitions and pilot acceptance; do not restart old stopped launchers.
