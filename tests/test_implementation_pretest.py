"""Saved-stage acceptance refuses stale settings, hidden measurement gaps and blocked task paths."""
import copy
import json
import pytest
from studies.energy_diagnosis.moe import pretest

LIMITS = dict(context=16384, max_turns=12, max_tool_calls=24, max_total_output_tokens=8192,
              max_output_tokens_per_turn=2048, goal_seconds=180)


@pytest.fixture
def stage(tmp_path, monkeypatch):
    monkeypatch.setattr(pretest, 'audit', lambda *a, **k: {'smoke_passed':True, 'protocol_valid':True})
    root=tmp_path/'stage';campaign=root/'campaign';goal=campaign/'goals'/'g';goal.mkdir(parents=True)
    manifest=dict(source_revision='abc', agent=dict(protocol='chat-tools-v2', **{k:v for k,v in LIMITS.items() if k.startswith('max_')}),
        config=dict(engine='llamacpp',gguf_path='/models/q4.gguf',max_context=16384),limits=dict(goal_seconds=180),
        task_pack=dict(specifications=[dict(kind='impl',prompt='v2')]),task_catalog=[dict(task_id='impl-toy-v2')])
    (campaign/'moe-manifest.json').write_text(json.dumps(manifest))
    (goal/'verification.json').write_text(json.dumps(dict(status='returned',result=dict(passed=True))))
    (goal/'agent-trace.json').write_text(json.dumps(dict(outcome='passed',turns=[dict(kind='tool_calls'),dict(kind='answer')])) )
    energy=dict(measurements=[dict(domain_id=d,status='valid',energy_j=1.0) for d in pretest.DOMAINS])
    (goal/'initialized-model-window.json').write_text(json.dumps({k:energy for k in ('before_task_window','task_window','verifier_window')}))
    workspace=campaign/'workspaces'/'g';workspace.mkdir(parents=True);(workspace/'solution.py').write_text('def f(x): return x\n')
    return root


def checked(stage):
    return pretest.check_stage(stage,dict(arm='q4',gguf_path='/models/q4.gguf',task_id='impl-toy-v2'),revision='abc',limits=LIMITS)


def test_complete_stage(stage):
    result=checked(stage)
    assert result['passed'] and result['solution_sha256'] and result['energy_j']['task_window']==3


@pytest.mark.parametrize('mutation', ['missing_energy','duplicate_domain','wrong_protocol','old_task','wrong_context','loop','no_artifact'])
def test_false_ready_is_rejected(stage,mutation):
    goal=stage/'campaign/goals/g';manifest=stage/'campaign/moe-manifest.json'
    if mutation in ('missing_energy','duplicate_domain'):
        path=goal/'initialized-model-window.json';data=json.loads(path.read_text())
        if mutation=='missing_energy':del data['verifier_window']
        else:data['task_window']['measurements'][0]['domain_id']='GPU_BOARD_0'
        path.write_text(json.dumps(data))
    elif mutation in ('wrong_protocol','old_task','wrong_context'):
        data=json.loads(manifest.read_text())
        if mutation=='wrong_protocol':data['agent']['protocol']='chat-tools-v1'
        elif mutation=='old_task':data['task_pack']['specifications'][0]['kind']='repo'
        else:data['config']['max_context']=4096
        manifest.write_text(json.dumps(data))
    elif mutation=='loop':
        (goal/'agent-trace.json').write_text(json.dumps(dict(outcome='passed',turns=[dict(kind='no_action'),dict(kind='answer')])))
    else:(stage/'campaign/workspaces/g/solution.py').unlink()
    assert checked(stage)['passed'] is False


def test_both_arms_must_match_task_slots():
    contract=dict(stages=[dict(path='a',arm='q4',task_id='x',gguf_path='/q4'),dict(path='b',arm='q8',task_id='y',gguf_path='/q8')])
    with pytest.raises(ValueError,match='same task'):
        pretest.check(contract)


def test_prompt_change_must_be_explicit_in_contract(stage):
    path = stage / 'campaign/moe-manifest.json'
    manifest = json.loads(path.read_text())
    manifest['task_pack']['specifications'][0]['prompt'] = 'v3'
    path.write_text(json.dumps(manifest))
    assert not checked(stage)['passed']
    expected = dict(arm='q4', gguf_path='/models/q4.gguf', task_id='impl-toy-v2', prompt='v3')
    assert pretest.check_stage(stage, expected, revision='abc', limits=LIMITS)['passed']


@pytest.mark.parametrize('kind', ['etl','program','business','numerical','repo'])
def test_explicit_full_pack_contract_supports_other_families(stage,kind):
    path=stage/'campaign/moe-manifest.json';m=json.loads(path.read_text())
    m['task_pack']={'specifications':[{'kind':kind}], 'components':{kind:'component-hash'},
                    'support_components':{'helper':'helper-hash'}}
    m['task_catalog']=[{'task_id':'task-v4','family':pretest.FAMILIES[kind],
                        'asset_sha256':'asset-hash','verifier_sha256':'verifier-hash'}]
    path.write_text(json.dumps(m))
    workspace=stage/'campaign/workspaces/g'
    if kind=='etl':(workspace/'pipeline.sql').write_text('SELECT 1')
    if kind=='repo':
        (workspace/'networkx').mkdir();(workspace/'networkx/f.py').write_text('def f(): return 1')
        verification=stage/'campaign/goals/g/verification.json'
        v=json.loads(verification.read_text());v['result']['changed_files']=['networkx/f.py']
        verification.write_text(json.dumps(v))
    expected=dict(arm='q4',gguf_path='/models/q4.gguf',task_id='task-v4',kind=kind,
                  task_pack=copy.deepcopy(m['task_pack']),task_catalog_entry=copy.deepcopy(m['task_catalog'][0]))
    assert pretest.check_stage(stage,expected,revision='abc',limits=LIMITS)['passed']
    m['task_pack']['support_components']['helper']='changed'
    path.write_text(json.dumps(m))
    assert not pretest.check_stage(stage,expected,revision='abc',limits=LIMITS)['passed']


def test_model_failure_does_not_invalidate_intact_records(stage,monkeypatch):
    monkeypatch.setattr(pretest,'audit',lambda *a,**kw:dict(smoke_passed=False,protocol_valid=True))
    (stage/'campaign/goals/g/agent-trace.json').write_text(json.dumps(
        dict(outcome='turn_limit',turns=[dict(kind='no_action')])))
    (stage/'campaign/goals/g/verification.json').write_text(json.dumps(
        dict(status='returned',result=dict(passed=False,failure='mismatch'))))
    result=checked(stage)
    assert result['record_valid'] and not result['passed']


@pytest.mark.parametrize("field", ["task_pack", "task_catalog_entry", "kind", "prompt"])
def test_pair_rejects_different_inputs_or_verification_before_reading_stages(field, monkeypatch):
    stages = [dict(path=arm, arm=arm, task_id="same-task", gguf_path="/"+arm, kind="impl",
                   prompt="v2", task_pack={"components": {"task": "frozen"}},
                   task_catalog_entry={"asset_sha256": "frozen", "verifier_sha256": "verifier"})
              for arm in ("q4", "q8")]
    stages[1][field] = "different"
    def unexpected(*args, **kwargs):
        pytest.fail("mismatched pair must be rejected before stage inspection")
    monkeypatch.setattr(pretest, "check_stage", unexpected)
    with pytest.raises(ValueError, match="paired stages must share"):
        pretest.check(dict(stages=stages))


def test_pair_allows_identical_inputs_and_preserves_valid_model_failure(monkeypatch):
    stages = [dict(path=arm, arm=arm, task_id="same-task", gguf_path="/"+arm, kind="etl",
                   task_pack={"components": {"task": "frozen"}},
                   task_catalog_entry={"asset_sha256": "frozen"}) for arm in ("q4", "q8")]
    monkeypatch.setattr(pretest, "check_stage", lambda path, *a, **kw:
                        dict(passed=path=="q8", record_valid=True))
    result = pretest.check(dict(stages=stages, revision="abc", limits=LIMITS))
    assert result["records_valid"] and not result["task_pretest_passed"]


@pytest.mark.parametrize("key", ["max_turns", "max_tool_calls", "max_total_output_tokens", "max_output_tokens_per_turn", "goal_seconds"])
def test_changed_budget_invalidates_record(stage, key):
    path = stage / "campaign/moe-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["limits" if key == "goal_seconds" else "agent"][key] += 1
    path.write_text(json.dumps(manifest))
    result = checked(stage)
    assert not result["passed"] and not result["record_valid"]
