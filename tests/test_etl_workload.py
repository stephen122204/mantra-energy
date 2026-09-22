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
