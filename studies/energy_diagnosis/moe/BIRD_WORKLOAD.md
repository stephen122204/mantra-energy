# BIRD text-to-SQL component

Task-pack kind `bird`, family `bird-sql`, version `bird-sql-v1`. Questions come
from the official BIRD dev release (`dev.zip`, folder `dev_20240627`,
CC BY-SA 4.0). `dev.json` and the 11 database files are pinned by sha256 in
`bird_workload.py`; other bytes are refused. The dataset is never committed.

Specification (one per database; ids strictly increasing):

    {"kind": "bird", "db_id": "formula_1", "question_ids": [888, 948],
     "source": "/abs/path/dev_20240627"}

`create_tasks` builds one immutable asset per database, shared by its
questions like the business dataset: `public/<db_id>.sqlite` (unchanged
bytes), `public/questions/<id>.json` (question and evidence) and `private/`
(gold SQL, metadata). Task id `bird-<db_id>-q<id>-v1`; the prompt contains
the question, BIRD's evidence text and the submission format.

Tool `sql` uses the shared SQL action contract (`schema` | `query`). It
opens the asset database with `mode=ro&immutable=1` (no WAL/journal side
files; `card_games` is a WAL database) under an authorizer that allows only
SELECT, reads of the database's user tables, CTEs and SQL functions
(`load_extension` excluded). Writes, DDL, ATTACH, PRAGMA, transactions and
`sqlite_master`/`sqlite_sequence` are rejected. Limits: 128 rows (labelled
truncated), 65536 output bytes, 30 s, 32768 SQL bytes. No per-attempt
database copy is made; the asset hash is checked at begin and verification.

Answer: `submit_answer` with `{"sql": "<one SELECT statement>"}`.

Verifier: the submission and the gold SQL run separately on the asset
database with the same read-only settings, each bounded at 30 s. Pass iff
`set(submitted_rows) == set(gold_rows)` over Python sqlite3 row tuples, the
comparison in BIRD's official `llm/src/evaluation.py`: row order and
duplicates are ignored, column positions matter, and `1 == 1.0`. Multiset
and ordered equality are recorded as diagnostics only. Differences from the
official script: separate 30 s bounds instead of one around both queries,
the read-only authorizer, and a 1,000,000-row result bound. Failure labels:
`format` (wrong answer shape), `runtime_error` (SQL error or rejected
operation), `hidden_timeout` (submission over 30 s), `mismatch`. A gold query
that fails at verification raises an infrastructure error.

Selection (`python -m studies.energy_diagnosis.moe.bird_workload --source
DEV --output selection.json`): eligible ids are the sorted `question_id`s
with difficulty `simple`; a copy is shuffled with `random.Random(20260929)`;
ids are taken in shuffled order, skipping any whose database already has 5,
until 40. Each selected task is built and checked: the gold must pass its
verifier and deliberately wrong queries must fail (nonempty gold: empty
result, and gold plus a constant column; empty gold: one sentinel row).
Failed questions are listed as exclusions and not replaced. The report also
lists the task-pack specifications for the included ids.

    python -m pytest -q tests/test_bird_workload.py

Tests use a small generated BIRD-shaped release; one test also checks the
real release when present (`BIRD_DEV_DIR`).
