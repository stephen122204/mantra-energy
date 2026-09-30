"""BIRD dev text-to-SQL questions over read-only SQLite databases (task-pack kind 'bird').

Source: the official BIRD dev release (dev.zip, folder dev_20240627). create_tasks copies one database and the
selected questions of that database into an immutable asset directory, like the business workload's shared
dataset:

    public/<db_id>.sqlite            unchanged database bytes (sha256 pinned below)
    public/questions/<id>.json       question_id, db_id, question, evidence (the text the agent is given)
    private/gold/<id>.sql            BIRD gold SQL, read only by the verifier
    private/meta.json                release and database hashes, question metadata, verifier settings

The model never receives files. Its only tool is ``sql`` (schema | query), which opens the asset database with
``mode=ro&immutable=1`` and an authorizer that permits SELECT, reads of the database's own user tables, SQL
functions (load_extension excluded) and recursive CTEs, and denies everything else (writes, DDL, ATTACH, PRAGMA,
transactions, sqlite_master/sqlite_sequence). No per-attempt database copy is made; the asset hash is checked at
begin and at verification.

The agent submits ``{"sql": "<one SELECT statement>"}`` through submit_answer. The verifier executes the
submission and the gold SQL separately on the asset database with the same connection settings, each bounded by
VERIFY_SECONDS of wall time, and passes the task when ``set(submission_rows) == set(gold_rows)``: the comparison
in BIRD's official EX evaluation (llm/src/evaluation.py, which compares ``set(cursor.fetchall())``). Row order and
duplicate rows are ignored; columns are compared positionally inside each row tuple; Python sqlite3 value
equality applies (so 1 == 1.0). Multiset and ordered equality are recorded as diagnostics only. Differences from
the official script: separate 30 s bounds for submission and gold instead of one 30 s bound around both;
read-only connection with the authorizer above; results above MAX_RESULT_ROWS rows fail (memory bound).
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import random
import re
import shutil
import sqlite3
import tempfile
import time

from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash
from .tool_contracts import SQL_ACTIONS, action_contract, validate_action

VERSION = 'bird-sql-v1'
FAMILY = 'bird-sql'
RELEASE = 'dev_20240627'
SOURCE_URL = 'https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip'
DEV_JSON_SHA256 = '630272f2b1c44d8cef2c3b246f623355cf0bbc1e832c81061df895530dfc2f06'
DATABASE_SHA256 = {
    'california_schools': '986817d793479801ed55133e55aa27e335422c0cd3866b54a3d6317b7c5f09c1',
    'card_games': 'c98bdb57fe7474da798b407785544b9af0daaad5d61fd21e2a73309493bc1227',
    'codebase_community': '92101be6d2a9f6adceea59d38f6d1c556087f9eea1432432a21268cb1348036d',
    'debit_card_specializing': 'b3d149ad05746dbbe5116e229e17e18f09c39db43cf117d9ef3441753608b691',
    'european_football_2': 'e4d361dbeec6591a4b315877c0c481da05c8ff5a3d389b34d6e17b6f15bee4e0',
    'financial': 'd15d89cdb068a202b6f2b99342af44dffc1d52545b39ceaf62efdc0ba570101e',
    'formula_1': '17185981cd747f6cdc374cb02a6096db3130e6ec2ddc582fe1686a28fb4c4c8a',
    'student_club': 'eb89bcfe97eefa386a27904ec5aa15159811a7eac894ec659a36e48fa9f76b77',
    'superhero': '75e94a2c3236ee3bb2c01fb97a1c4b4c1c269bcefd4eab1d04be323d2d0825b1',
    'thrombosis_prediction': 'e7e16d74b4731b4b8d33fdbe8c29cd5622620788ce8d1f335631f65fc7cf1db9',
    'toxicology': 'f5fa7f21af1ad878ff8fef1b0582b8cb2d7ed63dbac65ff16d2ba05667650c5b',
}
# Fixed selection rule (seeded; recorded in each selection report).
SELECTION = dict(seed=20260929, size=40, per_database=5, difficulty='simple')
TOOL_SECONDS = 30.0
VERIFY_SECONDS = 30.0
MAX_RESULT_ROWS = 1_000_000
TOOL_ROWS = 128
TOOL_BYTES = 65536
MAX_SQL_BYTES = 32768
WRONG_SENTINEL = 'bird-wrong-answer-sentinel'
_DB_ID = re.compile(r'[a-z][a-z0-9_]{0,63}')


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_questions(source, *, pinned=True):
    """Return {question_id: record} from <source>/dev.json (the extracted dev_20240627 folder)."""
    path = Path(source) / 'dev.json'
    if pinned and file_sha256(path) != DEV_JSON_SHA256:
        raise ValueError('dev.json differs from the pinned BIRD dev release')
    records = json.loads(path.read_text(encoding='utf-8'))
    questions = {r['question_id']: r for r in records}
    if len(questions) != len(records) or any(type(q) is not int for q in questions):
        raise ValueError('BIRD question ids must be unique integers')
    return questions


def database_path(source, db_id):
    return Path(source) / 'dev_databases' / db_id / f'{db_id}.sqlite'


def connect(database):
    """Read-only, immutable connection: no journal/WAL side files are created next to the asset."""
    db = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro&immutable=1', uri=True, check_same_thread=False)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA cache_size=-65536')
    db.execute('PRAGMA temp_store=MEMORY')
    return db


def user_tables(db):
    return tuple(r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name"))


def authorizer(tables, internal=()):
    """tables: readable user tables; internal: other schema names (sqlite_master, sqlite_sequence, ...)."""
    allowed, hidden = set(tables), {'sqlite_master', 'sqlite_schema', 'sqlite_temp_master', *internal} - set(tables)

    def authorize(op, a, b, database, trigger):
        if op in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if op == sqlite3.SQLITE_READ and a in allowed and database == 'main':
            return sqlite3.SQLITE_OK
        # Whole-table/count-only reads of tables and of CTEs are reported with an empty column and no database name.
        if op == sqlite3.SQLITE_READ and database is None and b == '' and a not in hidden:
            return sqlite3.SQLITE_OK
        if op == sqlite3.SQLITE_FUNCTION and (b or '').lower() != 'load_extension':
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    return authorize


def _check_sql(sql):
    if not isinstance(sql, str) or not sql.strip() or len(sql.encode()) > MAX_SQL_BYTES:
        raise ValueError(f'SQL must be nonempty text up to {MAX_SQL_BYTES} bytes')


def execute(database, sql, *, seconds=VERIFY_SECONDS, max_rows=MAX_RESULT_ROWS, truncate=False):
    """Run one SELECT under the read-only authorizer. Returns dict(status=ok|timeout|error|too_large, ...).

    With truncate, the first max_rows rows are returned with truncated=True instead of status too_large."""
    started = time.monotonic()
    try:
        _check_sql(sql)
    except ValueError as exc:
        return dict(status='error', error=str(exc), seconds=0.0)
    db = connect(database)
    expired = []

    def progress():
        if time.monotonic() - started > seconds:
            expired.append(True)
            return 1
        return 0
    try:
        db.set_authorizer(authorizer(user_tables(db), (r[0] for r in db.execute('SELECT name FROM sqlite_master'))))
        db.set_progress_handler(progress, 1000)
        rows = []
        cursor = db.execute(sql)
        while True:
            chunk = cursor.fetchmany(10000)
            if not chunk:
                break
            rows.extend(chunk)
            if len(rows) > max_rows:
                if truncate:
                    break
                return dict(status='too_large', error=f'more than {max_rows} result rows', seconds=time.monotonic()-started)
        return dict(status='ok', rows=rows[:max_rows], truncated=len(rows) > max_rows,
                    columns=[c[0] for c in cursor.description or ()], seconds=time.monotonic()-started)
    except (sqlite3.Error, ValueError, OverflowError, MemoryError) as exc:
        if expired:
            return dict(status='timeout', error=f'did not finish within {seconds:g} seconds', seconds=time.monotonic()-started)
        return dict(status='error', error=f'{type(exc).__name__}: {exc}'[:500], seconds=time.monotonic()-started)
    finally:
        db.close()


def compare(submitted, gold):
    """BIRD EX verdict (set equality) plus multiset and ordered equality as diagnostics."""
    return dict(set_match=set(submitted) == set(gold),
                multiset_match=collections.Counter(submitted) == collections.Counter(gold),
                ordered_match=list(submitted) == list(gold))


def prompt_text(record):
    evidence = (record.get('evidence') or '').strip() or '(none)'
    return (f"Answer the question below about the SQLite database {record['db_id']} by writing one SQLite SELECT query.\n\n"
            f"Question: {record['question'].strip()}\n"
            f"Evidence: {evidence}\n\n"
            'Use the sql tool: action="schema" lists the tables and columns; action="query" runs a read-only SELECT and '
            'returns its first rows. Grading executes your submitted query on the database and compares the returned '
            'rows with those of a reference query; select only the values the question asks for. When your query is '
            'final, call the submit_answer tool with answer {"sql": "<your final SELECT query>"}; do not write the '
            'answer as text.')


def create_tasks(root, *, db_id, question_ids, source, pinned=True):
    """One immutable asset per database (shared by its selected questions, like business)."""
    if not isinstance(db_id, str) or not _DB_ID.fullmatch(db_id) or (pinned and db_id not in DATABASE_SHA256):
        raise ValueError('unknown BIRD database')
    if (not isinstance(question_ids, list) or not 1 <= len(question_ids) <= 64
            or any(type(q) is not int or q < 0 for q in question_ids) or question_ids != sorted(set(question_ids))):
        raise ValueError('question_ids must be a nonempty strictly increasing list of integers')
    source = Path(source)
    questions = load_questions(source, pinned=pinned)
    records = []
    for qid in question_ids:
        record = questions.get(qid)
        if record is None or record['db_id'] != db_id:
            raise ValueError(f'question {qid} is not a {db_id} question')
        records.append(record)
    database = database_path(source, db_id)
    database_sha256 = file_sha256(database)
    if pinned and database_sha256 != DATABASE_SHA256[db_id]:
        raise ValueError(f'{db_id} database differs from the pinned BIRD dev release')
    root = Path(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as temp:
        stage = Path(temp) / 'assets'
        (stage / 'public' / 'questions').mkdir(parents=True)
        (stage / 'private' / 'gold').mkdir(parents=True)
        shutil.copyfile(database, stage / 'public' / f'{db_id}.sqlite')
        if file_sha256(stage / 'public' / f'{db_id}.sqlite') != database_sha256:
            raise ValueError('database changed while copying')
        for r in records:
            visible = dict(question_id=r['question_id'], db_id=r['db_id'], question=r['question'], evidence=r['evidence'])
            (stage / 'public' / 'questions' / f"{r['question_id']}.json").write_text(
                json.dumps(visible, indent=1, sort_keys=True) + '\n', encoding='utf-8')
            (stage / 'private' / 'gold' / f"{r['question_id']}.sql").write_text(r['SQL'], encoding='utf-8')
        meta = dict(version=VERSION, release=RELEASE, source_url=SOURCE_URL, db_id=db_id,
                    dev_json_sha256=file_sha256(source / 'dev.json'), database_sha256=database_sha256,
                    questions={str(r['question_id']): dict(difficulty=r['difficulty']) for r in records},
                    verifier=dict(comparison='set equality of result-row tuples (BIRD EX)',
                                  verify_seconds=VERIFY_SECONDS, max_result_rows=MAX_RESULT_ROWS),
                    license='CC BY-SA 4.0 (BIRD)')
        (stage / 'private' / 'meta.json').write_text(json.dumps(meta, indent=1, sort_keys=True) + '\n', encoding='utf-8')
        fingerprint = _hash(stage)
        if root.exists():
            if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')) or _hash(root) != fingerprint:
                raise ValueError('existing BIRD assets differ')
        else:
            stage.rename(root)
    return tuple(PilotTask(task_id(r), FAMILY, f'bird-{RELEASE}-{db_id}', root, {}, fingerprint, (), prompt_text(r))
                 for r in records)


def task_id(record):
    return f"bird-{record['db_id']}-q{record['question_id']}-v1"


def _question_id(task):
    match = re.fullmatch(r'bird-([a-z0-9_]+)-q(\d+)-v1', task.task_id)
    if not match:
        raise ValueError('not a BIRD task')
    return match.group(1), int(match.group(2))


def _database(task):
    db_id, _ = _question_id(task)
    return task.asset_path / 'public' / f'{db_id}.sqlite'


def gold_sql(task):
    _, qid = _question_id(task)
    return (task.asset_path / 'private' / 'gold' / f'{qid}.sql').read_text(encoding='utf-8')


def verify(task, answer):
    if _hash(task.asset_path) != task.asset_sha256:
        raise ValueError('BIRD inputs changed')
    format_ok = isinstance(answer, dict) and set(answer) == {'sql'} and isinstance(answer.get('sql'), str)
    completion = dict(format_ok=format_ok, submitted_type=type(answer).__name__)
    if not format_ok:
        return dict(passed=False, reason='answer must be {"sql": "<one SELECT statement>"}', failure='format',
                    completion=completion)
    sql = answer['sql']
    submitted_sha256 = hashlib.sha256(sql.encode()).hexdigest()
    database = _database(task)
    gold = execute(database, gold_sql(task), seconds=VERIFY_SECONDS, max_rows=MAX_RESULT_ROWS)
    if gold['status'] != 'ok':
        # A reference that cannot run is an infrastructure fault, never a model failure.
        raise RuntimeError(f"BIRD gold SQL {gold['status']}: {gold.get('error')}")
    submitted = execute(database, sql, seconds=VERIFY_SECONDS, max_rows=MAX_RESULT_ROWS)
    common = dict(completion=completion, submitted_sql=sql if len(sql.encode()) <= MAX_SQL_BYTES else None,
                  submitted_sql_sha256=submitted_sha256, gold_rows=len(gold['rows']),
                  gold_seconds=round(gold['seconds'], 4), submitted_seconds=round(submitted['seconds'], 4))
    if submitted['status'] == 'timeout':
        return dict(passed=False, reason=f'submitted SQL did not finish within {VERIFY_SECONDS:g} seconds',
                    failure='hidden_timeout', **common)
    if submitted['status'] != 'ok':
        return dict(passed=False, reason=f"submitted SQL {submitted['status']}: {submitted.get('error')}",
                    failure='runtime_error', **common)
    comparison = compare(submitted['rows'], gold['rows'])
    result = dict(passed=comparison['set_match'], comparison=comparison, submitted_rows=len(submitted['rows']), **common)
    if comparison['set_match']:
        result['reason'] = 'execution match: result-row sets equal (BIRD EX)'
    else:
        result.update(reason='execution mismatch: result-row sets differ (BIRD EX)', failure='mismatch')
    return result


def _visible(value):
    if isinstance(value, bytes):
        return "x'" + value[:64].hex() + ("...'" if len(value) > 64 else "'")
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    return value


class BirdSQLTool:
    def __init__(self, database, max_seconds=None):
        self.database = Path(database)
        self.max_seconds = TOOL_SECONDS if max_seconds is None else max_seconds

    def execute(self, action, sql=None, workers=1):
        if workers != 1:
            raise ValueError('this SQLite tool supports one worker')
        if action not in SQL_ACTIONS or (action == 'schema' and sql is not None):
            raise ValueError('use schema or query(sql)')
        started, cpu = time.monotonic_ns(), time.process_time_ns()
        if action == 'schema':
            db = connect(self.database)
            try:
                tables = {}
                for name in user_tables(db):
                    quoted = '"' + name.replace('"', '""') + '"'
                    columns = [dict(name=r[1], type=r[2], primary_key=bool(r[5]))
                               for r in db.execute(f'PRAGMA table_info({quoted})')]
                    keys = [dict(column=r[3], references=f'{r[2]}.{r[4]}' if r[4] else r[2])
                            for r in db.execute(f'PRAGMA foreign_key_list({quoted})')]
                    tables[name] = dict(columns=columns, foreign_keys=keys) if keys else dict(columns=columns)
                payload = dict(tables=tables)
            finally:
                db.close()
        else:
            _check_sql(sql)
            result = execute(self.database, sql, seconds=self.max_seconds, max_rows=TOOL_ROWS, truncate=True)
            if result['status'] == 'timeout':
                raise ValueError(f'query did not finish within {self.max_seconds:g} seconds')
            if result['status'] != 'ok':
                raise sqlite3.DatabaseError(result['error'])
            payload = dict(columns=result['columns'], rows=[[_visible(v) for v in r] for r in result['rows']],
                           truncated=result['truncated'])
        if len(json.dumps(payload, allow_nan=False, default=str).encode()) > TOOL_BYTES:
            raise ValueError(f'result exceeds {TOOL_BYTES} bytes; aggregate or select fewer columns')
        payload['tool_accounting'] = dict(elapsed_ns=time.monotonic_ns()-started, cpu_ns=time.process_time_ns()-cpu,
                                          sqlite=sqlite3.sqlite_version, workers=1)
        return payload


def sql_contract():
    return dict(
        description='Read-only SQLite database. The action argument is mandatory on every call. '
        'action="schema" (no sql argument) returns every table with its columns (name, type, primary_key) and foreign keys. '
        'Use those exact names; quote names containing spaces or punctuation with double quotes or backticks. '
        'action="query" requires sql containing one SELECT statement; it returns columns, rows and truncated. '
        f'At most {TOOL_ROWS} rows and {TOOL_BYTES} output bytes are returned; the query time limit is {TOOL_SECONDS:g} seconds '
        f'and the SQL text limit is {MAX_SQL_BYTES} bytes. SQLite functions, window functions and CTEs are available. '
        'No database writes, attachments, PRAGMA, sqlite_master, external files or extensions.',
        args={'action': 'required: schema or query', 'sql': 'required only for query; omit for schema'},
        parameters=action_contract(SQL_ACTIONS),
        example_call={'id': 'schema_1', 'tool': 'sql', 'args': {'action': 'schema'}},
    )


class BirdRuntime:
    def __init__(self, root=None):
        self.root = root

    def begin(self, task, lease):
        # No per-attempt database copy: the tool opens the hash-checked asset read-only and immutable. The
        # private gold SQL is read only by verify().
        if _hash(task.asset_path) != task.asset_sha256:
            raise ValueError('BIRD inputs changed')
        self.database = _database(task)

    def context(self, task):
        return dict(family=task.family, tools={'sql': sql_contract()},
            instruction='Return only JSON {"tool_calls":[{"id":"unique","tool":"sql","args":{...}}]} or {"answer":{"sql":"..."}}. '
            'Continue from the observations already present in tool_results; do not restart the task on each response. '
            'If no successful schema result is present, inspect the schema with action="schema". '
            'Then query with action="query" and sql, using the observed table and column names. '
            'When a query returns the requested values, submit that query as the answer. '
            'Use a new call id for each call. Use actual tool results; do not invent observations or guess column names.')

    def tool(self, task, call):
        if call.get('tool') != 'sql':
            raise ValueError('invalid SQL tool request')
        validate_action(call.get('args'), SQL_ACTIONS)
        return BirdSQLTool(self.database)

    def verify(self, task, answer):
        return verify(task, answer)


# ---------------------------------------------------------------- fixed selection

def sample(questions, *, seed=SELECTION['seed'], size=SELECTION['size'], per_database=SELECTION['per_database'],
           difficulty=SELECTION['difficulty']):
    """Shuffle the sorted eligible ids with random.Random(seed); take ids in that order, skipping any whose
    database already has per_database picks, until size are taken."""
    eligible = sorted(q for q, r in questions.items() if r['difficulty'] == difficulty)
    order = list(eligible)
    random.Random(seed).shuffle(order)
    chosen, counts = [], collections.Counter()
    for qid in order:
        db_id = questions[qid]['db_id']
        if counts[db_id] < per_database:
            chosen.append(qid)
            counts[db_id] += 1
            if len(chosen) == size:
                break
    return dict(eligible=len(eligible), order_prefix=order[:len(chosen) + 64], chosen=chosen)


def wrong_queries(gold, gold_rows):
    """Deliberately wrong queries whose result-row set must differ from the gold set."""
    inner = gold.strip().rstrip(';').strip()
    if gold_rows:
        return {'empty_result': f'SELECT * FROM ({inner}) WHERE 0',
                'extra_column': f"SELECT *, '{WRONG_SENTINEL}' FROM ({inner})"}
    return {'sentinel_row': f"SELECT '{WRONG_SENTINEL}'"}


def check_task(task, runtime=None):
    """Gold must pass its own verifier and every wrong query must fail."""
    runtime = runtime or BirdRuntime()
    runtime.begin(task, None)
    gold = gold_sql(task)
    try:
        result = runtime.verify(task, {'sql': gold})
    except RuntimeError as exc:
        return dict(gold_passed=False, gold_error=str(exc), wrong_queries={}, qualified=False)
    checks = {}
    for name, sql in wrong_queries(gold, result['gold_rows']).items():
        outcome = runtime.verify(task, {'sql': sql})
        checks[name] = dict(sql=sql, passed=outcome['passed'], failure=outcome.get('failure'))
    return dict(gold_passed=result['passed'], gold_rows=result['gold_rows'], gold_seconds=result['gold_seconds'],
                gold_comparison=result.get('comparison'), wrong_queries=checks,
                qualified=result['passed'] and bool(checks) and not any(c['passed'] for c in checks.values()))


def select(source, output, *, work=None, pinned=True):
    """Apply the fixed selection rule, build the tasks, run the gold and wrong-query checks, write selection.json."""
    source = Path(source).resolve()
    questions = load_questions(source, pinned=pinned)
    picked = sample(questions)
    by_db = collections.defaultdict(list)
    for qid in picked['chosen']:
        by_db[questions[qid]['db_id']].append(qid)
    rows, exclusions = [], []
    with tempfile.TemporaryDirectory(dir=work) as temp:
        for db_id in sorted(by_db):
            for task in create_tasks(Path(temp) / f'bird-{db_id}', db_id=db_id, question_ids=sorted(by_db[db_id]),
                                     source=source, pinned=pinned):
                _, qid = _question_id(task)
                check = check_task(task)
                rows.append(dict(question_id=qid, db_id=db_id, difficulty=questions[qid]['difficulty'],
                                 task_id=task.task_id, asset_sha256=task.asset_sha256, **check))
                if not check['qualified']:
                    exclusions.append(dict(question_id=qid, db_id=db_id,
                                           reason=check.get('gold_error') or 'gold failed its verifier or a wrong query passed'))
    order = {q: i for i, q in enumerate(picked['chosen'])}
    rows.sort(key=lambda r: order[r['question_id']])
    included = [r['question_id'] for r in rows if r['qualified']]
    report = dict(
        version=VERSION, release=RELEASE, source_url=SOURCE_URL, dev_json_sha256=file_sha256(source / 'dev.json'),
        rule=dict(SELECTION, method='eligible = sorted question_id with difficulty == "simple"; '
                  'random.Random(seed).shuffle(copy of eligible); walk the shuffled list, keeping an id unless its '
                  'db_id already has per_database kept ids; stop at size. Excluded ids are not replaced.'),
        eligible=picked['eligible'], sampled=picked['chosen'],
        verifier=dict(comparison='set(submitted_rows) == set(gold_rows) (BIRD EX, llm/src/evaluation.py)',
                      verify_seconds=VERIFY_SECONDS, max_result_rows=MAX_RESULT_ROWS,
                      wrong_queries='nonempty gold: empty result and gold plus a constant extra column; empty gold: one sentinel row',
                      sqlite=sqlite3.sqlite_version, workload_sha256=file_sha256(__file__)),
        questions=rows, exclusions=exclusions, included=included,
        task_pack_specifications=specifications({db: [q for q in ids if q in included] for db, ids in by_db.items()}, source))
    output = Path(output)
    output.write_text(json.dumps(report, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    return report


def specifications(question_ids_by_db, source):
    """Task-pack specifications (one per database) for the given question ids."""
    return [dict(kind='bird', db_id=db, question_ids=sorted(ids), source=str(Path(source).resolve()))
            for db, ids in sorted(question_ids_by_db.items()) if ids]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fixed BIRD dev selection with gold and wrong-query checks; no model run')
    parser.add_argument('--source', required=True, help='extracted BIRD dev folder (dev_20240627)')
    parser.add_argument('--output', required=True, help='selection.json path')
    parser.add_argument('--work', help='scratch directory for temporary task assets')
    args = parser.parse_args(argv)
    report = select(args.source, args.output, work=args.work)
    print(json.dumps(dict(sampled=len(report['sampled']), included=len(report['included']),
                          exclusions=report['exclusions']), indent=1))


if __name__ == '__main__':
    main()
