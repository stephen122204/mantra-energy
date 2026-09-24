# Generated business-query component

`create_tasks(path, rows=8192, seed=7)` creates three PilotTasks sharing one
immutable dataset: matched paid revenue by segment; paid unmatched transactions;
and segments with strictly greater than 20 percent revenue decline.

Version `business-query-v2` (task ids `business-*-v2-*`). The v1 declines answer
could remain `["s0"]` across large-input configurations; this was not true
for every seed and size. v2 draws segment names, sparse customer
ids and unknown-customer ids from the seed, and assigns every task all six
decline categories (clear decline, stable, exactly 80 percent, one integer step
under 80 percent, non-positive 2024, and stable-only-if-refunds-are-filtered),
enforced with adjustment rows. Fixed trap rows add refunded/failed and 2023/2026
matched rows, repeat purchases, and NULL, unknown-id, negative and refunded
unmatched rows. Tests check that missing paid/year filters, `>=` years, distinct
customer counts, `NOT IN` with NULLs, NULL-only orphans, positive-only sums,
`<=` thresholds, a missing positivity check and selected constant answers are
rejected. Answer diversity is not uniqueness: different seeds can produce the
same decline set, and an answer-only task cannot reject a correct literal answer
merely because it was guessed.
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

BusinessRuntime implements the GoalExecutor workload interface and is selected
by task-pack kind `business`. Fixture CLI tests exercise verifier provenance,
record export and restart behavior. v2 requires fresh assets and a new output
directory; do not resume a v1 task pack with these definitions. Physical model
execution and measurements must be qualified separately on the new version.
