from types import SimpleNamespace
import pytest
from studies.energy_diagnosis.moe.etl_workload import create_task,ETLRuntime,ETLTool

CORRECT="SELECT r.region, COUNT(*) AS event_count, SUM(r.gross_cents-r.tax_cents) AS net_cents FROM raw r JOIN (SELECT event_id,MAX(seq) AS latest FROM raw GROUP BY event_id) v ON r.event_id=v.event_id AND r.seq=v.latest WHERE r.status='paid' GROUP BY r.region ORDER BY r.region"

def setup(tmp_path,rows=128,seed=7):
    task=create_task(tmp_path/'assets',rows=rows,seed=seed)
    runtime=ETLRuntime(tmp_path/'runs');runtime.begin(task,SimpleNamespace(execution_id='one'))
    return task,runtime,ETLTool(runtime.workspace)

@pytest.mark.parametrize('rows,seed',[(32,0),(8192,7),(65536,29)])
def test_repair_with_real_query_and_csv_reference(tmp_path,rows,seed):
    task,runtime,tool=setup(tmp_path,rows,seed)
    assert task.task_id.startswith('etl-latest-v2-')
    assert task.lineage == 'synthetic-versioned-events-v2'
    assert not runtime.verify(task,{'done':True})['passed']
    tool.execute('write',CORRECT)
    assert not tool.execute('test')['truncated']
    assert runtime.verify(task,{'done':True})['passed']
    assert create_task(task.asset_path,rows=rows,seed=seed)==task

@pytest.mark.parametrize('sql',[CORRECT.replace("r.status='paid'","1=1"),CORRECT.replace('MAX(seq)','MIN(seq)'),CORRECT.replace('r.gross_cents-r.tax_cents','r.gross_cents+r.tax_cents'),CORRECT.replace('ORDER BY r.region','ORDER BY r.region DESC'),'DELETE FROM raw',"SELECT name FROM sqlite_master"])
def test_incorrect_or_forbidden_query_rejected(tmp_path,sql):
    task,runtime,tool=setup(tmp_path)
    tool.execute('write',sql)
    assert not runtime.verify(task,{'done':True})['passed']

def test_forged_done_and_input_mutation_rejected(tmp_path):
    task,runtime,tool=setup(tmp_path)
    tool.execute('write',CORRECT)
    assert not runtime.verify(task,{'done':1})['passed']
    assert not runtime.verify(task,{'done':True,'extra':'yes'})['passed']
    source=task.asset_path/'raw.csv';source.write_bytes(source.read_bytes()+b'corrupt')
    with pytest.raises(ValueError):runtime.verify(task,{'done':True})

def test_hardcoded_original_answer_fails_additional_inputs(tmp_path):
    from studies.energy_diagnosis.moe.etl_workload import reference
    task,runtime,tool=setup(tmp_path)
    sql=' UNION ALL '.join("SELECT '%s' AS region, %d AS event_count, %d AS net_cents" % tuple(row) for row in reference(task))
    tool.execute('write',sql)
    assert not runtime.verify(task,{'done':True})['passed']

# v2: v1 inputs used event_id=seq//2, allowing parity shortcuts on vulnerable inputs.
EQUIVALENT=[
    CORRECT,
    "SELECT region, COUNT(*) AS event_count, SUM(gross_cents-tax_cents) AS net_cents FROM raw WHERE status='paid' AND seq IN (SELECT MAX(seq) FROM raw GROUP BY event_id) GROUP BY region ORDER BY region",
    "SELECT region, COUNT(*) AS event_count, SUM(net) AS net_cents FROM (SELECT region, status, gross_cents-tax_cents AS net, MAX(seq) FROM raw GROUP BY event_id) WHERE status='paid' GROUP BY region ORDER BY region",
    "SELECT region, COUNT(*) AS event_count, SUM(gross_cents-tax_cents) AS net_cents FROM raw r WHERE status='paid' AND NOT EXISTS (SELECT 1 FROM raw x WHERE x.event_id=r.event_id AND x.seq>r.seq) GROUP BY region ORDER BY region",
]
SHORTCUTS=[
    "SELECT region, COUNT(*) AS event_count, SUM(gross_cents-tax_cents) AS net_cents FROM raw WHERE seq%2=1 AND status='paid' GROUP BY region ORDER BY region",
    "SELECT region, COUNT(*) AS event_count, SUM(gross_cents-tax_cents) AS net_cents FROM raw WHERE seq%2=0 AND status='paid' GROUP BY region ORDER BY region",
    "SELECT region, COUNT(*) AS event_count, SUM(gross_cents-tax_cents) AS net_cents FROM raw WHERE seq=2*event_id+1 AND status='paid' GROUP BY region ORDER BY region",
    "SELECT region, COUNT(*) AS event_count, SUM(gross_cents-tax_cents) AS net_cents FROM raw WHERE status='paid' GROUP BY region ORDER BY region",
    "SELECT region, COUNT(DISTINCT event_id) AS event_count, SUM(gross_cents-tax_cents) AS net_cents FROM raw WHERE status='paid' GROUP BY region ORDER BY region",
    # latest paid version instead of latest version
    CORRECT.replace("FROM raw GROUP BY event_id","FROM raw WHERE status='paid' GROUP BY event_id"),
    # latest version per (event, region) misses region changes
    CORRECT.replace("GROUP BY event_id","GROUP BY event_id,region"),
]

@pytest.mark.parametrize('seed',[0,7,19])
@pytest.mark.parametrize('sql',EQUIVALENT)
def test_equivalent_correct_queries_pass(tmp_path,sql,seed):
    task,runtime,tool=setup(tmp_path,rows=512,seed=seed)
    tool.execute('write',sql)
    assert runtime.verify(task,{'done':True})['passed']

@pytest.mark.parametrize('seed',[0,7,19])
@pytest.mark.parametrize('sql',SHORTCUTS)
def test_structural_shortcuts_rejected(tmp_path,sql,seed):
    task,runtime,tool=setup(tmp_path,rows=512,seed=seed)
    tool.execute('write',sql)
    assert not runtime.verify(task,{'done':True})['passed']

def test_irregular_inputs_and_private_hidden_cases(tmp_path):
    from studies.energy_diagnosis.moe.etl_workload import hidden_cases,reference_records
    task,runtime,tool=setup(tmp_path,rows=2048,seed=7)
    import csv
    rows=list(csv.DictReader((task.asset_path/'raw.csv').open()))
    versions={}
    for r in rows:versions.setdefault(r['event_id'],[]).append(int(r['seq']))
    assert {len(v) for v in versions.values()}>={1,2,3}
    assert any(int(r['event_id'])!=int(r['seq'])//2 for r in rows)
    assert [int(r['seq']) for r in rows]!=sorted(int(r['seq']) for r in rows)
    assert {p.name for p in runtime.workspace.iterdir()}=={'raw.csv','raw.sqlite','pipeline.sql','source.json'}
    cases=list(hidden_cases())
    assert len(cases)==5 and all(reference_records(c) for c in cases)


def test_hand_built_hidden_reference_and_sql_agree(tmp_path):
    from studies.energy_diagnosis.moe.etl_workload import hidden_cases, reference_records, _materialize
    from studies.energy_diagnosis.moe.query_workload import QueryTool
    records = next(hidden_cases())
    expected = [['central', 1, 7], ['north', 2, 390], ['south', 1, 0], ['west', 1, -20]]
    assert reference_records(records) == expected
    _materialize(tmp_path, list(reversed(records)))
    tool = QueryTool(str(tmp_path/'raw.sqlite'), tables=('raw',))
    for query in EQUIVALENT:
        assert tool.execute('query', query)['rows'] == expected
    for query in SHORTCUTS:
        assert tool.execute('query', query)['rows'] != expected
