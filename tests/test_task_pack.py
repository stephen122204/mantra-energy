from types import SimpleNamespace
import pytest
from studies.energy_diagnosis.moe.task_pack import prepare

SPECS=[dict(kind='numerical',rows=128,seed=7),dict(kind='business',rows=128,seed=7),dict(kind='etl',rows=128,seed=7)]

def test_pack_catalog_and_dispatch(tmp_path):
    pack=prepare(tmp_path/'pack',SPECS)
    assert len(pack.tasks)==5
    assert len({t.task_id for t in pack.tasks})==5
    assert len({t.lineage for t in pack.tasks})==3
    assert all(len(row['verifier_sha256'])==64 for row in pack.catalog())
    runtime=pack.runtime(tmp_path/'output')
    for i,task in enumerate(pack.tasks):
        runtime.begin(task,SimpleNamespace(execution_id=f'run{i}'))
        context=runtime.context(task)
        name={'grouped-regression':'regression','business-query':'sql','etl-sql-repair':'etl'}[task.family]
        args={'action':{'regression':'fit','sql':'schema','etl':'read'}[name]}
        result=runtime.tool(task,dict(tool=name,args=args)).execute(**args)
        if name=='regression':assert runtime.verify(task,result)['passed']
        elif name=='sql':assert set(result['tables'])=={'customers','transactions'}
        else:assert set(result['schema']['tables'])=={'raw'}
    assert prepare(tmp_path/'pack',SPECS).catalog()==pack.catalog()
    with pytest.raises(ValueError):prepare(tmp_path/'pack',[dict(kind='numerical',rows=256,seed=7)])

@pytest.mark.parametrize('specs',[[],SPECS+SPECS,[dict(kind='unknown',rows=32,seed=1)],[dict(kind='numerical',rows=True,seed=1)]])
def test_invalid_packs_do_not_create_assets(tmp_path,specs):
    root=tmp_path/'assets'
    with pytest.raises(ValueError):prepare(root,specs)
    assert not root.exists()


def test_support_change_prevents_resuming_frozen_pack(tmp_path, monkeypatch):
    from studies.energy_diagnosis.moe import task_pack
    root=tmp_path/'pack'
    prepare(root,SPECS)
    monkeypatch.setattr(task_pack,'support_components',lambda kinds:{'changed':'a'*64})
    with pytest.raises(ValueError,match='task pack changed'):
        prepare(root,SPECS)


def test_inventory_distinguishes_input_variants_and_never_claims_ready(tmp_path):
    from studies.energy_diagnosis.moe.prepare_task_screen import inventory
    specs=SPECS+[dict(kind='etl',rows=256,seed=8)]
    report=inventory(prepare(tmp_path/'pack',specs))
    assert report['task_cases']==6 and report['task_types']==5
    assert report['counts']['etl-sql-repair']==2
    assert all(t['qualification'].startswith('pending') for t in report['tasks'])


def test_prepared_snapshot_preserves_private_challenges_between_arms(tmp_path):
    specs=[dict(kind='etl',rows=128,seed=7),dict(kind='program',case='conditional-dedup',rows=128,seed=7)]
    source=tmp_path/'frozen';frozen=prepare(source,specs)
    arms=[prepare(tmp_path/arm,specs,prepared_assets=source) for arm in ('q4','q8')]
    assert arms[0].catalog()==arms[1].catalog()==frozen.catalog()
    assert prepare(tmp_path/'q4',specs,prepared_assets=source).catalog()==frozen.catalog()
    assert arms[0].tasks[0].asset_path != frozen.tasks[0].asset_path
    private=next((tmp_path/'q4').glob('*/private/challenges.json'))
    private.write_text('{}')
    with pytest.raises(ValueError,match='differ from frozen'):
        prepare(tmp_path/'q4',specs,prepared_assets=source)


def test_prepared_snapshot_rejects_stale_code_and_symlinks(tmp_path):
    import json
    source=tmp_path/'frozen';prepare(source,SPECS)
    manifest=source/'task-pack.json';original=manifest.read_text()
    data=json.loads(original);data['support_components']={'stale':'old'}
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='verifier code'):
        prepare(tmp_path/'run',SPECS,prepared_assets=source)
    assert not (tmp_path/'run').exists()
    manifest.write_text(original)
    (source/'leak').symlink_to(tmp_path/'secret')
    with pytest.raises(ValueError,match='symlinks'):
        prepare(tmp_path/'run',SPECS,prepared_assets=source)


def test_prepared_snapshot_accepts_read_only_frozen_directories(tmp_path):
    import stat
    source=tmp_path/'frozen-readonly'; frozen=prepare(source,SPECS)
    paths=[source,*source.rglob('*')]
    modes={p:stat.S_IMODE(p.stat().st_mode) for p in paths}
    try:
        for p in paths:p.chmod(modes[p] & ~0o222)
        run=tmp_path/'readonly-run'
        copied=prepare(run,SPECS,prepared_assets=source)
        assert copied.catalog()==frozen.catalog()
        assert all(not stat.S_IMODE(p.stat().st_mode) & 0o222 for p in paths)
        assert stat.S_IMODE(run.stat().st_mode)==stat.S_IMODE(source.stat().st_mode) | 0o200
        assert all(not stat.S_IMODE(p.stat().st_mode) & 0o222 for p in run.rglob('*'))
    finally:
        for p,mode in modes.items():p.chmod(mode)
        if (tmp_path/'readonly-run').exists():
            for p in [tmp_path/'readonly-run',*(tmp_path/'readonly-run').rglob('*')]:
                p.chmod(p.stat().st_mode | 0o200)
