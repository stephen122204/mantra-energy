# Bounded SQL ETL repair

The model reads and replaces pipeline.sql and executes it through the existing
bounded read-only SQLite tool. It must retain the maximum-sequence row per event,
filter latest status to paid, aggregate gross minus tax by region, and sort the
result. This is a SQL transformation repair, not unrestricted Python repository repair.

Version `etl-latest-record-v2` (task ids `etl-latest-v2-*`). v1 inputs used
`event_id = seq // 2` in both visible and hidden data, so parity shortcuts such
as `WHERE seq % 2 = 1` could pass visible and hidden checks. v2 inputs have 1-6 versions per
event, sparse event ids, versions interleaved across events, nonconsecutive seq
with random parity, region/status/amount changes between versions, and CSV row
order that differs from seq order.

`create_task(path, rows=8192, seed=7)` creates immutable generated CSV/database
inputs and an incorrect query. All sizes/seeds share one synthetic lineage.
`ETLRuntime` supplies the GoalExecutor begin/context/tool/verify interface.
The verifier runs the submitted SQL against the original immutable database and
five additional datasets not exposed by the model's tool interface (a hand-built
edge-case table, the v1 pair layout shifted to reverse seq parity, and three
irregular generated tables), comparing with independent Python calculations.
Tests cover equivalent correct formulations, parity/offset shortcuts, missing
deduplication, latest-paid-instead-of-latest, per-region deduplication, ordering
and hardcoded results. Each SQL execution has the existing 10-second bound; the
complete verifier can execute six queries. The integrating runner must budget
and record this cost. Queries without an event_id index that scan per row (for
example correlated NOT EXISTS) can exceed the bound on large inputs; that is an
execution-budget limitation. The current verifier catches SQLite interruption
as a failed check; separate timeout classification remains an integration issue.

This component is selected by task-pack kind `etl`. Existing fixture CLI tests
exercise numerical, business and ETL tasks, saved verifier identities, exports
and resume. v2 requires fresh assets and a new output directory. The single
goal deadline and live-model qualification are separate from this change; these
fixture checks do not authorize native runs. Alex identified the original ETL
sequence-parity shortcut.

Run `python -m pytest -q tests/test_etl_workload.py tests/test_task_pack.py`.
