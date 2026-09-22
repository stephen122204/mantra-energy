# Bounded SQL ETL repair

The model reads and replaces pipeline.sql and executes it through the existing
bounded read-only SQLite tool. It must retain the maximum-sequence row per event,
filter latest status to paid, aggregate gross minus tax by region, and sort the
result. Inputs contain repeated event identities and changing statuses/amounts.
This is a SQL transformation repair, not unrestricted Python repository repair.

`create_task(path, rows=8192, seed=7)` creates immutable generated CSV/database
inputs and an incorrect query. All sizes/seeds share one synthetic lineage.
`ETLRuntime` supplies the GoalExecutor begin/context/tool/verify interface.
The verifier runs the submitted SQL against the original immutable database and
two additional small datasets not exposed by the model's tool interface, comparing
with independent Python/CSV calculations. A hardcoded original result is rejected.
Each SQL execution has the existing 10-second bound; the complete verifier can
execute three queries. The integrating runner must budget and record this cost.

This component is selected by task_pack kind `etl`. The pack now supports
numerical, business and ETL specifications. It does not enable a production CLI
flag or authorize native runs. Model decisions, goal timeouts across verification,
measurement records, resume and exports still need actual integration checks.

Run `python -m pytest -q tests/test_etl_workload.py tests/test_task_pack.py`.
