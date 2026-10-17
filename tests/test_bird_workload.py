"""BIRD text-to-SQL workload: execution-match verifier, read-only tool, seeded sampling, task identity."""
import collections
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from studies.energy_diagnosis.moe import bird_workload as bird
from studies.energy_diagnosis.moe.bird_workload import BirdRuntime, BirdSQLTool, create_tasks, sample, verify

GOLD = {
    0: ('shop', "SELECT name FROM customers WHERE city = 'Austin'", 'simple'),
    1: ('shop', 'SELECT COUNT(*) FROM orders', 'simple'),
    2: ('shop', 'SELECT c.name, SUM(o.amount) FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.id ORDER BY 2 DESC', 'moderate'),
    3: ('zoo', 'SELECT species FROM animals WHERE legs = 4 ORDER BY species', 'simple'),
    4: ('zoo', 'SELECT `nick name` FROM `pet names` WHERE animal_id = 99', 'simple'),
    5: ('zoo', 'SELECT MAX(legs) FROM animals', 'challenging'),
}


def _make_source(root, extra_simple=0):
    """A small BIRD-shaped release: dev.json and dev_databases/<db>/<db>.sqlite (zoo in WAL mode)."""
    root = Path(root)
    records = [dict(question_id=q, db_id=db, question=f'Question {q}?', evidence='' if q == 1 else f'hint {q}',
                    SQL=sql, difficulty=d) for q, (db, sql, d) in GOLD.items()]
    for i in range(extra_simple):
        q = len(records)
        records.append(dict(question_id=q, db_id=('shop', 'zoo', 'farm')[i % 3], question=f'Question {q}?', evidence='',
                            SQL='SELECT 1', difficulty='simple' if i % 4 else 'moderate'))
    (root / 'dev_databases').mkdir(parents=True)
    (root / 'dev.json').write_text(json.dumps(records))
    scripts = {
        'shop': ('CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, city TEXT);'
                 'CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), amount REAL);'
                 "INSERT INTO customers VALUES (1,'Ann','Austin'),(2,'Bo','Boston'),(3,'Cy','Austin');"
                 'INSERT INTO orders VALUES (1,1,10.0),(2,1,5.5),(3,2,7.0),(4,3,1.0);'),
        'zoo': ('PRAGMA journal_mode=WAL; CREATE TABLE animals(id INTEGER PRIMARY KEY AUTOINCREMENT, species TEXT, legs INTEGER, photo BLOB);'
                "INSERT INTO animals(species,legs,photo) VALUES ('cat',4,x'00ff'),('dog',4,NULL),('emu',2,NULL),('cat',4,NULL);"
                'CREATE TABLE "pet names"(animal_id INTEGER, "nick name" TEXT);'),
        'farm': 'CREATE TABLE fields(id INTEGER);',
    }
    for db, script in scripts.items():
        (root / 'dev_databases' / db).mkdir()
        con = sqlite3.connect(root / 'dev_databases' / db / f'{db}.sqlite')
        con.executescript(script)
        con.commit()
        if db == 'zoo':
            con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        con.close()
        for side in ('-wal', '-shm'):
            (root / 'dev_databases' / db / f'{db}.sqlite{side}').unlink(missing_ok=True)
    return root


def _pin(monkeypatch, source):
    monkeypatch.setattr(bird, 'DEV_JSON_SHA256', bird.file_sha256(source / 'dev.json'))
    monkeypatch.setattr(bird, 'DATABASE_SHA256', {db: bird.file_sha256(bird.database_path(source, db))
                                                  for db in ('shop', 'zoo', 'farm')})


@pytest.fixture
def source(tmp_path):
    return _make_source(tmp_path / 'dev')


def _task(tmp_path, source, db, qid, ids=None):
    tasks = create_tasks(tmp_path / f"assets-{db}-{'-'.join(map(str, ids or [qid]))}", db_id=db, question_ids=ids or [qid], source=source, pinned=False)
    return next(t for t in tasks if t.task_id == f'bird-{db}-q{qid}-v1')


def _runtime(task):
    runtime = BirdRuntime(None)
    runtime.begin(task, SimpleNamespace(execution_id='x'))
    return runtime


@pytest.mark.parametrize('qid', sorted(GOLD))
def test_gold_passes_and_wrong_queries_fail(tmp_path, source, qid):
    db = GOLD[qid][0]
    task = _task(tmp_path, source, db, qid)
    result = verify(task, {'sql': GOLD[qid][1]})
    assert result['passed'] and result['comparison']['set_match'] and 'failure' not in result
    check = bird.check_task(task)
    assert check['qualified'] and check['gold_passed']
    assert check['wrong_queries'] and not any(c['passed'] for c in check['wrong_queries'].values())
    assert check['wrong_queries'].keys() == ({'sentinel_row'} if qid == 4 else {'empty_result', 'extra_column'})


def test_execution_match_is_bird_set_comparison(tmp_path, source):
    task = _task(tmp_path, source, 'shop', 0)
    same = {
        "SELECT name FROM customers WHERE city='Austin' ORDER BY name DESC": dict(ordered_match=False, multiset_match=True),
        "SELECT name FROM customers WHERE city='Austin' UNION ALL SELECT 'Ann'": dict(multiset_match=False),
        "SELECT c.name FROM customers c JOIN orders o ON o.customer_id=c.id WHERE c.city='Austin'": dict(multiset_match=False),
    }
    for sql, diagnostics in same.items():
        result = verify(task, {'sql': sql})
        assert result['passed'], sql
        assert all(result['comparison'][k] == v for k, v in diagnostics.items()), sql
    for sql in ("SELECT name FROM customers",                                  # extra row
                "SELECT name, city FROM customers WHERE city='Austin'",        # extra column
                "SELECT name FROM customers WHERE city='Austin' LIMIT 1",      # missing row
                "SELECT UPPER(name) FROM customers WHERE city='Austin'"):      # different values
        result = verify(task, {'sql': sql})
        assert not result['passed'] and result['failure'] == 'mismatch', sql
    count = _task(tmp_path, source, 'shop', 1, ids=[0, 1])
    assert verify(count, {'sql': 'SELECT 4.0'})['passed']                   # sqlite3/Python value equality: 4 == 4.0
    assert not verify(count, {'sql': "SELECT '4'"})['passed']
    columns = _task(tmp_path, source, 'shop', 2, ids=[0, 1, 2])
    swapped = 'SELECT SUM(o.amount), c.name FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.id'
    assert not verify(columns, {'sql': swapped})['passed']                  # tuple positions matter


@pytest.mark.parametrize('answer,failure', [
    ({'sql': 'SELEC name FROM customers'}, 'runtime_error'),
    ({'sql': 'SELECT nope FROM customers'}, 'runtime_error'),
    ({'sql': 'DELETE FROM customers'}, 'runtime_error'),
    ({'sql': "SELECT 1; DELETE FROM customers"}, 'runtime_error'),
    ({'sql': ' '}, 'runtime_error'),
    ({'query': 'SELECT 1'}, 'format'),
    ('SELECT name FROM customers', 'format'),
    ({'sql': 'SELECT 1', 'extra': 1}, 'format'),
])
def test_invalid_submissions_fail_without_changing_inputs(tmp_path, source, answer, failure):
    task = _task(tmp_path, source, 'shop', 0)
    result = verify(task, answer)
    assert not result['passed'] and result['failure'] == failure
    assert result['completion']['format_ok'] == (failure != 'format')
    assert verify(task, {'sql': GOLD[0][1]})['passed']   # asset hash still matches; rows intact


def test_submission_and_tool_timeouts(tmp_path, source, monkeypatch):
    task = _task(tmp_path, source, 'shop', 0)
    forever = 'WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n) SELECT COUNT(*) FROM n'
    monkeypatch.setattr(bird, 'VERIFY_SECONDS', 0.3)
    result = verify(task, {'sql': forever})
    assert not result['passed'] and result['failure'] == 'hidden_timeout'
    with pytest.raises(ValueError, match='did not finish'):
        BirdSQLTool(task.asset_path / 'public' / 'shop.sqlite', max_seconds=0.3).execute('query', forever)


def test_gold_that_cannot_run_is_infrastructure_not_model_failure(tmp_path, source):
    task = _task(tmp_path, source, 'shop', 0)
    gold = task.asset_path / 'private' / 'gold' / '0.sql'
    gold.write_text('SELECT missing FROM customers')
    tampered = task.__class__(**{**task.__dict__, 'asset_sha256': bird._hash(task.asset_path)})
    with pytest.raises(RuntimeError, match='gold'):
        verify(tampered, {'sql': 'SELECT 1'})
    assert bird.check_task(tampered)['qualified'] is False
    with pytest.raises(ValueError, match='changed'):
        verify(task, {'sql': 'SELECT 1'})


@pytest.mark.parametrize('sql', [
    'DELETE FROM customers', "INSERT INTO customers VALUES (9,'x','y')", 'UPDATE orders SET amount = 0',
    'CREATE TABLE t(x)', 'DROP TABLE orders', "ATTACH DATABASE ':memory:' AS other", 'PRAGMA table_info(customers)',
    'SELECT * FROM sqlite_master', "SELECT load_extension('x')", 'SELECT 1; SELECT 2', 'BEGIN', 'VACUUM',
])
def test_tool_is_read_only_and_limited_to_declared_tables(tmp_path, source, sql):
    task = _task(tmp_path, source, 'shop', 0)
    runtime = _runtime(task)
    tool = runtime.tool(task, {'tool': 'sql', 'args': {'action': 'query', 'sql': sql}})
    with pytest.raises((sqlite3.DatabaseError, ValueError)):
        tool.execute('query', sql)
    assert bird._hash(task.asset_path) == task.asset_sha256


def test_tool_cannot_reach_other_files_or_the_gold(tmp_path, source):
    task = _task(tmp_path, source, 'zoo', 3, ids=[3, 4])
    runtime = _runtime(task)
    tool = runtime.tool(task, {'tool': 'sql', 'args': {'action': 'schema'}})
    assert tool.database == task.asset_path / 'public' / 'zoo.sqlite'
    other = tmp_path / 'other.sqlite'
    sqlite3.connect(other).executescript('CREATE TABLE secret(x); INSERT INTO secret VALUES (1);')
    for sql in (f"ATTACH DATABASE '{other}' AS o", 'SELECT * FROM o.secret', 'SELECT * FROM secret',
                'SELECT * FROM sqlite_sequence', 'SELECT COUNT(*) FROM sqlite_sequence', 'SELECT COUNT(*) FROM sqlite_master',
                "SELECT readfile('/etc/passwd')"):
        with pytest.raises((sqlite3.DatabaseError, ValueError)):
            tool.execute('query', sql)
    context = json.dumps(runtime.context(task)) + task.prompt
    assert GOLD[3][1] not in context and 'gold' not in context
    assert set(runtime.context(task)['tools']) == {'sql'}
    for bad in ({'tool': 'python', 'args': {'action': 'read'}}, {'tool': 'sql', 'args': {'sql': 'SELECT 1'}},
                {'tool': 'sql', 'args': {'action': 'schema', 'sql': 'SELECT 1'}}):
        with pytest.raises(ValueError):
            runtime.tool(task, bad)


def test_tool_schema_query_and_wal_database_leaves_no_side_files(tmp_path, source):
    task = _task(tmp_path, source, 'zoo', 3, ids=[3, 4])
    runtime = _runtime(task)
    contract = runtime.context(task)['tools']['sql']
    call = contract['example_call']
    schema = runtime.tool(task, call).execute(**call['args'])
    assert set(schema['tables']) == {'animals', 'pet names'}
    assert {c['name'] for c in schema['tables']['pet names']['columns']} == {'animal_id', 'nick name'}
    result = BirdSQLTool(runtime.database).execute('query', 'SELECT species, photo FROM animals ORDER BY id')
    assert result['rows'][0] == ['cat', "x'00ff'"] and result['truncated'] is False
    many = BirdSQLTool(runtime.database).execute(
        'query', 'WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < 500) SELECT i FROM n')
    assert many['truncated'] is True and len(many['rows']) == bird.TOOL_ROWS
    counted = BirdSQLTool(runtime.database).execute(
        'query', 'WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < 5) SELECT COUNT(*) FROM n')
    assert counted['rows'] == [[5]]
    assert BirdSQLTool(runtime.database).execute('query', 'SELECT COUNT(*) FROM animals')['rows'] == [[4]]
    assert verify(task, {'sql': GOLD[3][1]})['passed']
    assert sorted(p.name for p in (task.asset_path / 'public').iterdir()) == ['questions', 'zoo.sqlite']
    assert bird._hash(task.asset_path) == task.asset_sha256


def test_prompt_has_question_and_evidence_only(tmp_path, source):
    task = _task(tmp_path, source, 'shop', 0, ids=[0, 1])
    assert 'Question: Question 0?' in task.prompt and 'Evidence: hint 0' in task.prompt
    assert '"sql"' in task.prompt and 'submit_answer' in task.prompt
    no_evidence = _task(tmp_path, source, 'shop', 1, ids=[0, 1])
    assert 'Evidence: (none)' in no_evidence.prompt
    visible = json.loads((task.asset_path / 'public' / 'questions' / '0.json').read_text())
    assert set(visible) == {'question_id', 'db_id', 'question', 'evidence'}


def test_task_identity_is_stable_across_builds(tmp_path, source):
    first = create_tasks(tmp_path / 'a', db_id='shop', question_ids=[0, 1, 2], source=source, pinned=False)
    second = create_tasks(tmp_path / 'b', db_id='shop', question_ids=[0, 1, 2], source=source, pinned=False)
    assert [t.task_id for t in first] == ['bird-shop-q0-v1', 'bird-shop-q1-v1', 'bird-shop-q2-v1']
    assert [(t.task_id, t.asset_sha256, t.prompt, t.family, t.lineage) for t in first] == \
           [(t.task_id, t.asset_sha256, t.prompt, t.family, t.lineage) for t in second]
    assert len({t.asset_sha256 for t in first}) == 1 and first[0].family == 'bird-sql'
    assert create_tasks(tmp_path / 'a', db_id='shop', question_ids=[0, 1, 2], source=source, pinned=False) == first
    (tmp_path / 'a' / 'private' / 'gold' / '0.sql').write_text('SELECT 2')
    with pytest.raises(ValueError, match='differ'):
        create_tasks(tmp_path / 'a', db_id='shop', question_ids=[0, 1, 2], source=source, pinned=False)


@pytest.mark.parametrize('kwargs', [
    dict(db_id='shop', question_ids=[3]),        # question from another database
    dict(db_id='shop', question_ids=[1, 0]),     # not increasing
    dict(db_id='shop', question_ids=[]),
    dict(db_id='../shop', question_ids=[0]),
    dict(db_id='shop', question_ids=[0, 0]),
])
def test_invalid_task_requests_are_rejected(tmp_path, source, kwargs):
    with pytest.raises(ValueError):
        create_tasks(tmp_path / 'x', source=source, pinned=False, **kwargs)
    assert not (tmp_path / 'x').exists()


def test_pinned_release_refuses_other_sources(tmp_path, source, monkeypatch):
    with pytest.raises(ValueError, match='unknown BIRD database'):
        create_tasks(tmp_path / 'x', db_id='shop', question_ids=[0], source=source)
    monkeypatch.setattr(bird, 'DATABASE_SHA256', {'shop': '0' * 64})
    with pytest.raises(ValueError, match='dev.json differs'):
        create_tasks(tmp_path / 'x', db_id='shop', question_ids=[0], source=source)
    monkeypatch.setattr(bird, 'DEV_JSON_SHA256', bird.file_sha256(source / 'dev.json'))
    with pytest.raises(ValueError, match='shop database differs'):
        create_tasks(tmp_path / 'x', db_id='shop', question_ids=[0], source=source)
    assert not (tmp_path / 'x').exists()


def test_sampling_is_deterministic_simple_only_and_capped(tmp_path):
    questions = bird.load_questions(_make_source(tmp_path / 'dev', extra_simple=60), pinned=False)
    first = sample(questions, size=12, per_database=5)
    assert first == sample(questions, size=12, per_database=5)
    chosen = first['chosen']
    assert len(chosen) == 12 and len(set(chosen)) == 12
    assert all(questions[q]['difficulty'] == 'simple' for q in chosen)
    assert max(collections.Counter(questions[q]['db_id'] for q in chosen).values()) <= 5
    # The rule is: shuffle the sorted eligible ids with random.Random(seed) and walk them with the cap.
    import random
    order = sorted(q for q, r in questions.items() if r['difficulty'] == 'simple')
    random.Random(bird.SELECTION['seed']).shuffle(order)
    expected, counts = [], collections.Counter()
    for q in order:
        if counts[questions[q]['db_id']] < 5 and len(expected) < 12:
            expected.append(q)
            counts[questions[q]['db_id']] += 1
    assert chosen == expected
    assert sample(questions, size=12, per_database=5, seed=1) != first
    capped = sample(questions, size=40, per_database=2)['chosen']   # 3 databases x 2 < 40
    assert len(capped) == 6


def test_selection_report_and_task_pack_dispatch(tmp_path, source, monkeypatch):
    from studies.energy_diagnosis.moe.task_pack import prepare
    _pin(monkeypatch, source)
    monkeypatch.setattr(bird, 'SELECTION', dict(bird.SELECTION, size=4, per_database=2))
    monkeypatch.setattr(bird.sample, '__defaults__', (bird.SELECTION['seed'], 4, 2, 'simple'))
    report = bird.select(source, tmp_path / 'selection.json', work=tmp_path)
    assert json.loads((tmp_path / 'selection.json').read_text()) == json.loads(json.dumps(report))
    assert report['exclusions'] == [] and len(report['included']) == 4
    assert all(q['qualified'] and q['difficulty'] == 'simple' for q in report['questions'])
    specs = report['task_pack_specifications']
    assert all(s['kind'] == 'bird' for s in specs)
    pack = prepare(tmp_path / 'pack', specs)
    again = prepare(tmp_path / 'pack2', specs)
    assert pack.catalog() == again.catalog()
    catalog = pack.catalog()
    assert {r['family'] for r in catalog} == {'bird-sql'}
    assert all(r['workload_version'] == bird.VERSION and len(r['verifier_sha256']) == 64 for r in catalog)
    assert sorted(int(r['task_id'].rsplit('-q', 1)[1][:-3]) for r in catalog) == sorted(report['included'])
    runtime = pack.runtime(tmp_path / 'output')
    for i, task in enumerate(pack.tasks):
        runtime.begin(task, SimpleNamespace(execution_id=f'run{i}'))
        assert runtime.tool(task, {'tool': 'sql', 'args': {'action': 'schema'}}).execute('schema')['tables']
        _, qid = bird._question_id(task)
        assert runtime.verify(task, {'sql': GOLD.get(qid, (None, 'SELECT 1'))[1]})['passed']
        assert runtime.verification_callable(task)(task, {'sql': "SELECT 'wrong'"})['passed'] is False
    for bad in ([dict(specs[0], source='relative/path')], [dict(specs[0], question_ids=[])],
                [dict(specs[0], question_ids=list(reversed(specs[0]['question_ids'])) + [10**6])],
                [dict(specs[0], extra=1)], [specs[0], specs[0]]):
        with pytest.raises(ValueError):
            prepare(tmp_path / 'bad', bad)
        assert not (tmp_path / 'bad').exists()


REAL = Path(os.environ.get('BIRD_DEV_DIR', '/nonexistent-bird-dev'))


@pytest.mark.skipif(not (REAL / 'dev.json').is_file(), reason='BIRD dev release not available (set BIRD_DEV_DIR)')
def test_real_release_selection_rule_and_small_database_golds(tmp_path):
    questions = bird.load_questions(REAL)
    picked = sample(questions)
    assert picked == sample(questions) and picked['eligible'] == 925
    chosen = picked['chosen']
    assert len(chosen) == 40 and all(questions[q]['difficulty'] == 'simple' for q in chosen)
    by_db = collections.defaultdict(list)
    for q in chosen:
        by_db[questions[q]['db_id']].append(q)
    assert max(len(v) for v in by_db.values()) <= 5
    for db in ('superhero', 'student_club', 'toxicology'):
        if db in by_db:
            for task in create_tasks(tmp_path / db, db_id=db, question_ids=sorted(by_db[db]), source=REAL):
                assert bird.check_task(task)['qualified'], task.task_id
    assert hashlib.sha256((REAL / 'dev.json').read_bytes()).hexdigest() == bird.DEV_JSON_SHA256
