# Additive task-pack integration handoff

Dependencies: numerical component PR41 and business component PR42. This branch
combines both without modifying the pilot runner or PR40. `task_pack.prepare`
accepts an explicit list of `{kind, rows, seed}` specifications and returns
`TaskPack.tasks`, `TaskPack.catalog()` and `TaskPack.runtime(output)`.
Numerical and ETL each contribute one task per specification; business contributes three.
This is an implemented Python interface, not an existing command-line flag.

## Runner integration still required

- Add explicit selection for a pack, mutually exclusive with query-assets.
  Never silently replace existing tasks or run definitions.
- Use the returned tasks and runtime through GoalExecutor. The pack dispatcher
  supports begin/context/tool/verify. Keep the existing backend/lifecycle,
  measurement, scheduling, exports and cleanup paths.
- Populate each PlannedRun's verifier version/hash from that task's catalog row.
  The existing single workloads.py hash would be wrong for these components.
- Include the pack specification/component identities in the frozen manifest.
  Fail on configuration changes at resume; do not regenerate old definitions.
- Check task filtering, complete planned slot count, max-runs behavior, resume,
  all-attempt export and task-specific verifier identity through the real CLI.
- Extend simulated model decisions without supplying hidden references. A
  deterministic test policy may issue SQL/fit calls and read their actual outputs.
  It must not be presented as native model behavior.
- Native qualification still requires actual model decisions and hardware
  evidence on the final integrated revision. This handoff authorizes no run.

## Tests currently present

`python -m pytest -q tests/test_task_pack.py tests/test_business_workload.py tests/test_numerical_workload.py tests/test_numerical_pipeline.py tests/test_etl_workload.py tests/test_task_pack_pipeline.py`

44 local tests pass on the combined branch. Includes real numerical/SQL work,
reference comparisons, schema restrictions, invalid answers, input preservation,
pack dispatch, and injected-model/sensor numerical executor/ledger/resume cases.
The production CLI has not been modified. The bounded SQL ETL component is included; production integration remains pending.
Different sizes/seeds of generated inputs are still one lineage per generator.
No research protocol, raw data or private discussion is part of this handoff.

The all-pack pipeline test runs five tasks under each of success, wrong-answer
and missing-telemetry model/sensor fixtures (15 original attempts plus resume).
All records retain expected outcomes and exports remain identical after resume.
These tests inject pack selection. They intentionally do not certify the
production runner's per-task verifier hashes, which still require the integration
change above, nor native model decisions or transfer behavior.
