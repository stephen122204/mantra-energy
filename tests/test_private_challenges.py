import json
from types import SimpleNamespace
import pytest
from studies.energy_diagnosis.moe import private_challenges, program_workload as pw, etl_workload as ew


@pytest.mark.parametrize('kind',['program','etl'])
def test_private_seeds_frozen_across_resume_but_absent_from_workspace(tmp_path, kind):
    module = pw if kind=='program' else ew
    kwargs = dict(rows=32,seed=7)
    if kind=='program': kwargs['case']='conditional-dedup'
    task=module.create_task(tmp_path/'assets',**kwargs)
    seeds=private_challenges.read(task.asset_path)
    again=module.create_task(task.asset_path,**kwargs)
    assert again.asset_sha256==task.asset_sha256 and private_challenges.read(task.asset_path)==seeds
    other=module.create_task(tmp_path/'other',**kwargs)
    assert private_challenges.read(other.asset_path)!=seeds
    runtime=(pw.ProgramRuntime if kind=='program' else ew.ETLRuntime)(tmp_path/'run')
    runtime.begin(task,SimpleNamespace(execution_id='one'))
    assert not (runtime.workspace/'private').exists()
    assert 'seeds' not in (runtime.workspace/'source.json').read_text()


@pytest.mark.parametrize('case',pw.CASES)
def test_lookup_of_all_previous_public_hidden_inputs_is_rejected(tmp_path,case):
    task=pw.create_task(tmp_path/'assets',case=case,rows=32,seed=7)
    runtime=pw.ProgramRuntime(tmp_path/'run')
    runtime.begin(task,SimpleNamespace(execution_id='one'))
    known=[json.loads((task.asset_path/'input.json').read_text())]
    known += [pw.generate(case,n,s) for n,s in [(32,7919),(73,15401),(251,32443)]]
    known += pw.edge_cases(case)
    source='def solve(data):\n'
    for data in known:
        source+=f'    if data == {data!r}:\n        return {pw.reference(case,data)!r}\n'
    source+='    return None\n'
    pw.validate_source(source)
    (runtime.workspace/'solution.py').write_text(source)
    assert pw.ProgramTool(runtime.workspace).execute('test')['passed']
    assert runtime.verify(task,{'done':True})['failure']=='mismatch'


def test_etl_private_generated_cases_are_not_the_published_fixed_cases(tmp_path):
    task=ew.create_task(tmp_path/'assets',rows=32,seed=7)
    current=list(ew.hidden_cases(private_challenges.read(task.asset_path)))
    prior=list(ew.hidden_cases())
    assert current[:2]==prior[:2]  # retain explicit structural traps
    assert all(a!=b for a,b in zip(current[2:],prior[2:]))
