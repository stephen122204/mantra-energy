# Optional queryable TLC task

This extension depends on PR34's owned worker/tool/measurement/ledger path. It
does not change the default two-task smoke run. Use `--query-assets` to select the
prepared SQL task instead. Physical runtime acceptance remains pending.

The model can inspect table schemas and choose its own read-only SQL queries.
The final answer contains 24 exact hourly trip counts and a reconciled total.
The prompt specifies joins, filters, month boundaries, null handling, duplicate
record handling and timestamp interpretation. Preparation independently computes
the expected answer directly from the original Parquet using PyArrow; the model
tools expose the selected input database, not the reference manifest. Expected
values are never included in the model prompt. The tool is a bounded read-only
SQL interface, not a general OS sandbox.

## Prepare input once

Install `requirements-query.txt` (PyArrow 23.0.1 and DuckDB 1.5.0) in a separate
preparation environment. Download the two
files linked by the [NYC TLC source page](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page):

- [January 2025 yellow trips](https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2025-01.parquet).
- [Taxi zone lookup](https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv).

The preparation command verifies the exact source hashes pinned in
`query_workload.py` before reading records. It creates a new output directory,
projects five needed columns into both SQLite and DuckDB tables without filtering
records, imports the zone table, computes the independent reference, and records source
URLs/hashes, row count, database hash and preparation versions. Downloading and
preparation are separate from execution; neither is performed by CI or a model
tool. Do not commit downloaded data or generated databases. If the publisher
revises a source, investigate/version it rather than bypassing the hash check.

```sh
python -m studies.energy_diagnosis.moe.query_workload \
  --trips /absolute/path/yellow_tripdata_2025-01.parquet \
  --zones /absolute/path/taxi_zone_lookup.csv \
  --output /absolute/path/new-query-assets
```

The data describes records supplied to TLC, whose source page disclaims their
accuracy. Task correctness is relative to those supplied records and the stated
filters. This is one data lineage (`nyc-tlc-yellow-trips`), not a representative
multi-domain agent benchmark. A new month would not automatically be a new
independent lineage. No raw records are distributed in this repository.

## Run the existing path

Runtime defaults to DuckDB 1.5.0; `--query-engine sqlite` selects the alternate
standard-library implementation. Neither runtime needs PyArrow. First exercise
the simulated model/counter path with actual database tools:

```sh
python -m studies.energy_diagnosis.moe.run --mode fixture \
  --query-assets /absolute/path/new-query-assets \
  --output /absolute/path/new-fixture-run \
  --policies demand,fixed --max-runs 2 --deadline 60
```

Native use adds `--query-assets` to the assigned native command with explicit
configuration, allocation, isolation and budgets. Prepared synthetic test assets
are rejected in native mode. Actual inference, counter permissions, task-output
quality and runtime instrumentation still require on-node qualification. The
fixture's prescribed SQL decision tests integration only; native inference must
generate its own tool calls. Both controls receive identical tools and inputs.
The campaign manifest now records task ID, family, lineage, asset hash, workload
version and verifier hash explicitly. Use a new run directory for this revision;
an older manifest without this catalog is deliberately not resumed silently.

The read-only tool supports one worker and fresh connections. It limits SQL
length, execution time and output rows/bytes, records truncation and CPU/wall
time, and denies writes, attachments, PRAGMAs and undeclared functions. It exposes
the two input tables only. GoalExecutor hashes input assets before model startup;
there is no per-goal database copy. Source preparation is outside the recorded
goal; pre-execution hashing remains in the outer interval. SQLite connections
have an 8 MiB page-cache target; DuckDB uses one thread, a 512 MB engine memory
limit and no temporary-disk spill. OS page cache is not flushed. No artificial sleep
or repeated query is added to lengthen the tool operation. Tool accounting is
diagnostic, while existing owned-process body spans remain authoritative.

Both engine selections are fingerprinted and must use distinct run directories.
Tool accounting records the actual engine version. The DuckDB tool allows one
SELECT statement, disables external access and automatic extensions, and joins
its query-interrupt timer before returning. SQLite restricts readable tables and
functions through its authorizer. The engine memory limit is not a total-process
memory guarantee. Neither choice is a claim of optimal analytics performance.
Timing on a developer laptop is not GPU-node timing or
energy evidence. The task is an optional qualification input until native quality,
tool implementation and measurement acceptance are complete.

## Checks

`tests/test_moe_query_workload.py` covers correct/incorrect typed answers, boundary
dates/nulls/duplicates, database mutation rejection, disallowed SQL, truncation,
timeout, source integrity and two-policy complete fixture execution on both
engines. CI installs DuckDB for its small generated-input checks. An optional
PyArrow test checks the independent raw-data reference against hand-checked
records; it skips when that preparation dependency is absent. Portable CI runs
the remaining tests without downloading public data.
