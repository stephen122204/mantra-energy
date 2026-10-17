"""Independent boundary checks, adversarial solutions and real process execution."""
import json
from types import SimpleNamespace
import pytest
from studies.energy_diagnosis.moe import program_workload as pw
from studies.energy_diagnosis.moe.task_pack_fixture import PROGRAMS
from studies.energy_diagnosis.moe.task_pack import prepare


def runtime(tmp_path, case, rows=32, seed=7):
    task=pw.create_task(tmp_path/'assets',case=case,rows=rows,seed=seed)
    rt=pw.ProgramRuntime(tmp_path/'run');rt.begin(task,SimpleNamespace(execution_id='one'))
    return task,rt


def test_hand_calculated_references():
    assert pw.reference(pw.CASES[0],pw.edge_cases(pw.CASES[0])[-1]) == [900,-2,8,4]
    assert pw.reference(pw.CASES[1],pw.edge_cases(pw.CASES[1])[-1]) == {'a':[0,1],'b':[2,0],'z':[0,0]}
    assert pw.reference(pw.CASES[0],[]) == []
    assert pw.reference(pw.CASES[1],{'records':[],'bins':[0,1]}) == {}


@pytest.mark.parametrize('case',pw.CASES)
@pytest.mark.parametrize('rows,seed',[(32,1),(8192,7),(100000,99)])
def test_correct_implementation_passes_real_worker_and_hidden_checks(tmp_path,case,rows,seed):
    task,rt=runtime(tmp_path,case,rows,seed)
    tool=pw.ProgramTool(rt.workspace)
    assert tool.execute('write',content=PROGRAMS[case]) == {'written':True}
    assert tool.execute('test')['passed']
    assert rt.verify(task,{'done':True})['passed']
    assert not any('hidden' in p.name for p in rt.workspace.iterdir())
    context=rt.context(task)
    assert len(context['tools']['program']['parameters']['oneOf'])==3
    assert 'expected' not in json.dumps(context)


WRONG = [
 ('conditional-dedup', "def solve(data):\n    return [r['id'] for r in data if r['keep']]"),
 ('conditional-dedup', "def solve(data):\n    return [r['id'] for r in data]"),
 ('conditional-dedup', "def solve(data):\n    return list({r['url']:r['id'] for r in data}.values())"),
 ('conditional-dedup', PROGRAMS['conditional-dedup'].replace('return out','return list(reversed(out))')),
 ('conditional-dedup', PROGRAMS['conditional-dedup'].replace(" or r['keep']",'')),
 ('user-histogram', PROGRAMS['user-histogram'].replace("bins[j]<r['views']<=bins[j+1]","bins[j]<=r['views']<bins[j+1]")),
 ('user-histogram', PROGRAMS['user-histogram'].replace('return out',"return {k:v for k,v in out.items() if sum(v)>0}")),
 ('user-histogram', PROGRAMS['user-histogram'].replace('counts[j]+=1','counts[j]=1')),
]
@pytest.mark.parametrize('case,source',WRONG)
def test_wrong_algorithms_rejected(tmp_path,case,source):
    task,rt=runtime(tmp_path,case)
    (rt.workspace/'solution.py').write_text(source)
    result=rt.verify(task,{'done':True})
    assert result=={'passed':False,'reason':'incorrect_result','failure':'mismatch'}


@pytest.mark.parametrize('case',pw.CASES)
def test_visible_answer_hardcoding_does_not_pass_hidden_checks(tmp_path,case):
    task,rt=runtime(tmp_path,case)
    answer=pw.reference(case,json.loads((task.asset_path/'input.json').read_text()))
    pw.ProgramTool(rt.workspace).execute('write',content=f'def solve(data):\n    return {answer!r}\n')
    assert pw.ProgramTool(rt.workspace).execute('test')['passed']
    assert not rt.verify(task,{'done':True})['passed']


@pytest.mark.parametrize('source',[
 'import os\ndef solve(data): return []',
 'def solve(data):\n    return open("secret").read()',
 'def solve(data):\n    return data.__class__',
 'def solve(data: int): return []',
 'def solve(data):\n    import os\n    return []',
 '@list\ndef solve(data): return []',
 'def solve(data):\n    def other(): return []\n    return other()',
 'def solve(data):\n    return eval("1")',
])
def test_unsupported_programs_rejected(source):
    assert pw.execute(source,[])['status']=='invalid_program'


def test_timeout_mutation_types_and_missing_file(tmp_path):
    assert pw.execute('def solve(data):\n    while True: pass',[],seconds=.2)['status']=='budget_exceeded'
    assert pw.execute('def solve(data):\n    data.append(1)\n    return data',[])['status']=='runtime_error'
    assert not pw.matches(pw.CASES[0],[True],[1])
    assert not pw.matches(pw.CASES[1],{'a':[True]},{'a':[1]})
    task,rt=runtime(tmp_path,pw.CASES[0])
    (rt.workspace/'solution.py').unlink()
    assert rt.verify(task,{'done':True})['reason']=='missing_or_invalid_program'
    for seconds in (True,0,11,float('nan')):
        with pytest.raises(ValueError):pw.execute(PROGRAMS[pw.CASES[0]],[],seconds=seconds)


def test_pack_resume_identity_and_original_asset_integrity(tmp_path):
    specs=[dict(kind='program',case=c,rows=32,seed=7) for c in pw.CASES]
    pack=prepare(tmp_path/'pack',specs)
    assert pack.catalog()==prepare(tmp_path/'pack',specs).catalog()
    assert len(pack.tasks)==2
    rt=pack.runtime(tmp_path/'run');task=pack.tasks[0]
    rt.begin(task,SimpleNamespace(execution_id='one'))
    assert rt.context(task)['family']=='python-transformation'
    task.asset_path.joinpath('input.json').write_text('[]')
    with pytest.raises(ValueError,match='inputs changed'):rt.verify(task,{'done':True})
    with pytest.raises(ValueError,match='assets differ'):prepare(tmp_path/'pack',specs)


def test_program_spec_validation(tmp_path):
    base=dict(kind='program',case=pw.CASES[0],rows=32,seed=7)
    for override in ({'case':'missing'},{'rows':True},{'rows':100001},{'seed':-1},{'extra':True}):
        with pytest.raises(ValueError):prepare(tmp_path/'pack',[base|override])


def test_inventory_specifications_cover_distinct_behaviors():
    from studies.energy_diagnosis.moe.prepare_task_screen import specifications
    specs=specifications('/source','/python')
    assert len(specs)==14 # business expands to three, so sixteen tasks
    assert sum(s['kind']=='repo' for s in specs)==9
    assert {s['case'] for s in specs if s['kind']=='program'}==set(pw.CASES)
    assert len(specifications('/source','/python',repo_cases=['bfs-layers-visited']))==6
    with pytest.raises(ValueError):specifications('/source','/python',repo_cases=[])
