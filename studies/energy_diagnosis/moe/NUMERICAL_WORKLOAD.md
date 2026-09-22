# Grouped numerical workload component

This additive component does not modify the runner or PR40. `create_task(path,
rows=8192, seed=7)` produces immutable synthetic grouped observations. Different
sizes/seeds share one lineage; they are not independent benchmark domains.

`RegressionRuntime` implements begin/context/tool/verify for GoalExecutor.
The tool performs local fitting over the input rather than returning all rows
to the model. Four group summaries bound output size. The verifier separately
reads original inputs and computes exact rational sufficient statistics.
The explicit numerical tolerance is 1e-6 absolute. Invalid types, nonfinite
values, wrong groups/counts and corrupted assets fail validation.

Run component tests:

    python -m pytest -q tests/test_numerical_workload.py tests/test_numerical_pipeline.py

Evidence: local component and adapter checks only. Runner task-pack selection,
actual model decisions, scheduling, ledger/measurement integration and hardware
runtime qualification remain unimplemented/unverified for this component.
Fable's pilot changes should integrate this adapter through the existing
workload runtime interface; no alternate campaign engine is intended.
The supplied row counts are test inputs, not an approved measured run matrix.

Additional integration evidence: three injected-model/sensor runs exercise actual
numerical computation, independent verification, measurement records, ledger
exports and resume through the existing runner. Success, wrong answer and
missing telemetry are retained correctly. Tests inject task/adapter selection;
production CLI selection and correct verifier-source hashing still need wiring.
These tests do not establish native model behavior or transfer overlap.
