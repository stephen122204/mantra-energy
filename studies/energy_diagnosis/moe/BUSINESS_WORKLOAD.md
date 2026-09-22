# Generated business-query component

`create_tasks(path, rows=8192, seed=7)` creates three PilotTasks sharing one
immutable dataset: matched paid revenue by segment; paid unmatched transactions;
and segments with strictly greater than 20 percent revenue decline.
The bounded SQLite tool exposes only customers and transactions. The original
TLC defaults remain unchanged. Reference calculations read CSV inputs using
Python, independently of model SQL. Integer amounts, NULL customers, unmatched
IDs, refunded rows and strict year comparisons are explicit in prompts.

This is synthetic data, one lineage across questions/sizes/seeds. It is not a
published benchmark or a collection of independent source domains. Prepared
assets have content hashes and refuse changed-input reuse. No reference answer
is passed to the model. Tool reads/writes outside the declared SQL tables are
rejected by the existing authorizer.

Run:

    python -m pytest -q tests/test_business_workload.py tests/test_moe_query_workload.py

BusinessRuntime implements the GoalExecutor workload interface. Production
runner selection, exact verifier provenance, model decisions, complete ledger
integration and physical measurements remain pending. This PR is additive to
PR40; it does not replace or mutate that PR's assets and runner definitions.
