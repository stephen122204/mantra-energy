# Existing planning materials, copied for portability

These files come from the September 4 diagnostic-launch package. They are copied unchanged except for this README. They contain no measured results or real task assets.

- [campaign.json](campaign.json): proposed candidate matrix, counts and missing declarations.
- [make_run_plan.py](make_run_plan.py): standard-library planning utility, not a workload executor.
- [data-contract.md](data-contract.md): complete record and scientific integrity contract.

From this directory, `python3 make_run_plan.py --out generated` produces a planning CSV and report. `python3 make_run_plan.py --require-ready --out generated` intentionally exits with code 2 while declarations remain missing. Filling declarations is not hardware validation. The current planning matrix has 1,432 rows; task IDs are placeholders.

The newer access report and model/runtime recommendations are in the parent pack. We intentionally did not set actual hardware/runtime fields to requested or merely reported values. Student 3 must validate actual assets, capabilities and identities when implementing the real runner. No generated outputs need to be supplied to a student agent before its first issue.

