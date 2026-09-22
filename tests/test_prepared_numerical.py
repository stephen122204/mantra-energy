"""Prepared input identity, normalization failures and launcher persistence."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
from studies.energy_diagnosis.moe.numerical_workload import load_task, RegressionTool, verify
from studies.energy_diagnosis.moe.task_pack import prepare
from studies.energy_diagnosis.workloads.pilot_tasks import _hash


def source(root, csv='group,x,y,valid\nmonth1,1,3,1\nmonth1,2,5,1\nmonth1,3,7,1\nmonth1,100,0,0\n'):
    root.mkdir()
    (root/'observations.csv').write_text(csv,encoding='utf-8')
    (root/'source.json').write_text(json.dumps({'source':'Owned normalization test fixture','x':'units','y':'units'}),encoding='utf-8')
    return dict(kind='numerical',assets=str(root.resolve()),task_id='prepared-case-v1',lineage='owned-test-fixture',asset_sha256=_hash(root))


def test_snapshot_reuse_and_corruption(tmp_path):
    spec=source(tmp_path/'source')
    pack=prepare(tmp_path/'pack',[spec]);task=pack.tasks[0]
    assert task.asset_path!=Path(spec['assets'])
    answer=RegressionTool(str(task.asset_path)).execute('fit')
    assert verify(task,answer)['passed']
    assert pack.catalog()==prepare(tmp_path/'pack',[spec]).catalog()
    (task.asset_path/'observations.csv').write_text('corrupt')
    with pytest.raises(ValueError,match='checksum'):prepare(tmp_path/'pack',[spec])


@pytest.mark.parametrize('csv',[
    'group,x,y,valid\n',
    'group,x,y,valid\ng,1,2,1\ng,1,3,1\n',
    'group,x,y,valid\ng,1,2,2\ng,2,3,1\n',
    'group,x,y,valid\ng,nan,2,1\ng,2,3,1\n',
    'group,x,y,valid\ng,1.5,2,1\ng,2,3,1\n',
    'group,x,y,valid\ng,1000000001,2,1\ng,2,3,1\n',
    'group,x,y,valid\ng,1,2,1,extra\ng,2,3,1\n',
    'group,x,y,valid\ng,1,2\ng,2,3,1\n',
    'x,group,y,valid\n1,g,2,1\n2,g,3,1\n',
])
def test_invalid_normalization_refused_before_pack_creation(tmp_path,csv):
    spec=source(tmp_path/'source',csv)
    with pytest.raises(ValueError):prepare(tmp_path/'pack',[spec])
    assert not (tmp_path/'pack').exists()


def test_changed_source_and_identity_refused(tmp_path):
    spec=source(tmp_path/'source')
    bad=dict(spec,task_id='../escape')
    with pytest.raises(ValueError,match='identity'):prepare(tmp_path/'pack',[bad])
    (tmp_path/'source/observations.csv').write_text('changed')
    with pytest.raises(ValueError,match='checksum'):prepare(tmp_path/'pack',[spec])
    assert not (tmp_path/'pack').exists()


def test_prepared_task_through_cli(tmp_path):
    spec=source(tmp_path/'source');specfile=tmp_path/'spec.json'
    specfile.write_text(json.dumps([spec]))
    output=tmp_path/'run'
    args=[sys.executable,'-m','studies.energy_diagnosis.moe.run','--mode','fixture','--task-pack',str(specfile),'--output',str(output),'--policies','demand','--max-runs','1','--deadline','30']
    for expected in (1,0):
        proc=subprocess.run(args,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=60)
        assert proc.returncode==0,proc.stdout+proc.stderr
        assert json.loads(proc.stdout)['executed']==expected
    record=json.loads(next((output/'goals').glob('*/record.json')).read_text())
    assert record['task_id']=='prepared-case-v1'
    assert record['simulated'] and record['verifier']['outcome']=='pass'
    catalog=json.loads((output/'moe-manifest.json').read_text())['task_catalog']
    assert catalog[0]['asset_sha256']==spec['asset_sha256']
    assert catalog[0]['lineage']=='owned-test-fixture'
