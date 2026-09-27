"""Saved-stage acceptance refuses stale settings, hidden measurement gaps and blocked task paths."""
import copy
import json
import pytest
from studies.energy_diagnosis.moe import pretest

LIMITS = dict(context=16384, max_turns=12, max_tool_calls=24, max_total_output_tokens=8192,
              max_output_tokens_per_turn=2048, goal_seconds=180)


@pytest.fixture
def stage(tmp_path, monkeypatch):
    monkeypatch.setattr(pretest, 'audit', lambda *a, **k: {'smoke_passed':True})
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
