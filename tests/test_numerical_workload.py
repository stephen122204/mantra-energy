import copy
import json
import pytest
from studies.energy_diagnosis.moe.numerical_workload import create_task, RegressionTool, verify

@pytest.mark.parametrize('rows,seed', [(32,0),(8192,7),(65536,19)])
def test_actual_computation_agrees_with_independent_reference(tmp_path,rows,seed):
    task=create_task(tmp_path/'inputs',rows=rows,seed=seed)
    answer=RegressionTool(str(task.asset_path)).execute('fit')
    assert verify(task,answer)['passed']
    assert sum(g['count'] for g in answer['by_group'].values()) == rows - (rows+18)//19
    assert len(json.dumps(answer))<2000
    assert task.expected == {}

@pytest.mark.parametrize('defect',['missing','extra','count','bool','nan','wrong','swapped'])
def test_rejects_incorrect_answers(tmp_path,defect):
    task=create_task(tmp_path/'inputs',rows=128)
    answer=RegressionTool(str(task.asset_path)).execute('fit')
    groups=answer['by_group']
    if defect=='missing': del groups['g0']
    elif defect=='extra': groups['g4']=copy.deepcopy(groups['g0'])
    elif defect=='count': groups['g0']['count']+=1
    elif defect=='bool': groups['g0']['slope']=True
    elif defect=='nan': groups['g0']['rmse']=float('nan')
    elif defect=='wrong': groups['g0']['intercept']+=.01
    else: groups['g0'],groups['g1']=groups['g1'],groups['g0']
    assert not verify(task,answer)['passed']

def test_reuse_preserves_inputs_and_changed_inputs_refused(tmp_path):
    task=create_task(tmp_path/'inputs',rows=128)
    path=task.asset_path/'observations.csv'
    before=path.read_bytes(),path.stat().st_mtime_ns
    assert create_task(task.asset_path,rows=128).asset_sha256==task.asset_sha256
    assert before==(path.read_bytes(),path.stat().st_mtime_ns)
    path.write_bytes(before[0]+b'corrupt')
    with pytest.raises(ValueError):create_task(task.asset_path,rows=128)
    with pytest.raises(ValueError):verify(task,{})


def test_numerical_tolerance_is_explicit(tmp_path):
    task=create_task(tmp_path/'inputs',rows=128)
    answer=RegressionTool(str(task.asset_path)).execute('fit')
    answer['by_group']['g0']['slope']+=0.5e-6
    assert verify(task,answer)['passed']
    answer['by_group']['g0']['slope']+=2e-6
    assert not verify(task,answer)['passed']


def test_runtime_tools_use_isolated_workspace_and_strict_schema(tmp_path):
    from types import SimpleNamespace
    from studies.energy_diagnosis.moe.numerical_workload import RegressionRuntime
    task=create_task(tmp_path/'inputs',rows=128)
    runtime=RegressionRuntime(tmp_path/'runs')
    runtime.begin(task,SimpleNamespace(execution_id='one'))
    call={'tool':'regression','args':{'action':'fit'}}
    answer=runtime.tool(task,call).execute(**call['args'])
    assert runtime.verify(task,answer)['passed']
    assert runtime.workspace != task.asset_path
    assert 'expected' not in json.dumps(runtime.context(task))
    with pytest.raises(ValueError):runtime.begin(task,SimpleNamespace(execution_id='one'))
    with pytest.raises(ValueError):runtime.tool(task,{'tool':'regression','args':{'action':'fit','path':'secret'}})
