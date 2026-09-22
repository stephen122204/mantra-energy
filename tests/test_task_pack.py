from types import SimpleNamespace
import pytest
from studies.energy_diagnosis.moe.task_pack import prepare

SPECS=[dict(kind='numerical',rows=128,seed=7),dict(kind='business',rows=128,seed=7)]

def test_pack_catalog_and_dispatch(tmp_path):
    pack=prepare(tmp_path/'pack',SPECS)
    assert len(pack.tasks)==4
    assert len({t.task_id for t in pack.tasks})==4
    assert len({t.lineage for t in pack.tasks})==2
    assert all(len(row['verifier_sha256'])==64 for row in pack.catalog())
    runtime=pack.runtime(tmp_path/'output')
    for i,task in enumerate(pack.tasks):
        runtime.begin(task,SimpleNamespace(execution_id=f'run{i}'))
        context=runtime.context(task)
        name='regression' if task.family=='grouped-regression' else 'sql'
        args={'action':'fit' if name=='regression' else 'schema'}
        result=runtime.tool(task,dict(tool=name,args=args)).execute(**args)
        if name=='regression':assert runtime.verify(task,result)['passed']
        else:assert set(result['tables'])=={'customers','transactions'}
    assert prepare(tmp_path/'pack',SPECS).catalog()==pack.catalog()
    with pytest.raises(ValueError):prepare(tmp_path/'pack',[dict(kind='numerical',rows=256,seed=7)])

@pytest.mark.parametrize('specs',[[],SPECS+SPECS,[dict(kind='unknown',rows=32,seed=1)],[dict(kind='numerical',rows=True,seed=1)]])
def test_invalid_packs_do_not_create_assets(tmp_path,specs):
    root=tmp_path/'assets'
    with pytest.raises(ValueError):prepare(root,specs)
    assert not root.exists()
