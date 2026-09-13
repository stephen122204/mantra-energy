import json
from pathlib import Path
import subprocess
import sys

import pytest
import torch
from transformers import Qwen3MoeConfig,Qwen3MoeForCausalLM

from studies.energy_diagnosis.diagnostics.capture_fixed_forward import fixed_forward,sequence_forward,validate_case,preparation_effect,digest
from studies.energy_diagnosis.diagnostics.compare_fixed_forward import comparison


@pytest.mark.parametrize('attention',['eager','sdpa'])
def test_cached_scores_match_whole_prefix_and_hook_position(attention):
    torch.set_num_threads(1);torch.manual_seed(44)
    config=Qwen3MoeConfig(vocab_size=64,hidden_size=32,intermediate_size=64,
           moe_intermediate_size=16,num_hidden_layers=2,num_attention_heads=4,
           num_key_value_heads=2,head_dim=8,num_experts=4,num_experts_per_tok=2,
           max_position_embeddings=128)
    config._attn_implementation=attention
    model=Qwen3MoeForCausalLM(config).eval()
    case=dict(prompt_ids=[1,2,3,4],continuation_ids=[6,8,9])
    seen=[];calls=[]
    h=model.register_forward_pre_hook(lambda m,a,k:seen.append(k['input_ids'].shape[1]),with_kwargs=True)
    result=fixed_forward(model,case,'cpu',lambda:calls.append(list(seen)))
    h.remove()
    assert seen==[4,1,1,1] and calls==[[4]]
    assert result['cache_lengths']==[4,5,6,7]
    all_ids=case['prompt_ids']+case['continuation_ids']
    with torch.no_grad():
        for i,n in enumerate(result['cache_lengths']):
            ids=torch.tensor([all_ids[:n]])
            full=model(input_ids=ids,attention_mask=torch.ones_like(ids),use_cache=False).logits[:,-1]
            torch.testing.assert_close(result['logits'][:,i],full,atol=1e-6,rtol=1e-5)


@pytest.mark.parametrize('case',[
    dict(prompt_ids=[],continuation_ids=[1]),dict(prompt_ids=[True],continuation_ids=[1]),
    dict(prompt_ids=[1],continuation_ids=[64]),dict(prompt_ids=[1],continuation_ids=[2]*33),
    dict(prompt_ids=[1]*100,continuation_ids=[2]*32),
])
def test_invalid_cases(case):
    with pytest.raises(ValueError):validate_case(case,64,128)


@pytest.mark.parametrize('attention',['eager','sdpa'])
def test_primer_boundary_precedes_target_with_fresh_kv(attention):
    torch.set_num_threads(1);torch.manual_seed(45)
    config=Qwen3MoeConfig(vocab_size=64,hidden_size=32,intermediate_size=64,
           moe_intermediate_size=16,num_hidden_layers=2,num_attention_heads=4,
           num_key_value_heads=2,head_dim=8,num_experts=4,num_experts_per_tok=2,
           max_position_embeddings=128)
    config._attn_implementation=attention
    model=Qwen3MoeForCausalLM(config).eval()
    case=dict(prompt_ids=[1,2,3,4],continuation_ids=[6,8],
              primer=dict(prompt_ids=[1,9,7],continuation_ids=[4,5]))
    events=[]
    handle=model.register_forward_pre_hook(lambda m,a,k:events.append((k['input_ids'].shape[1],k['past_key_values'] is None)),with_kwargs=True)
    result,primer=sequence_forward(model,case,'cpu',lambda:events.append('boundary'),lambda:events.append('reset'))
    handle.remove()
    assert events==[(3,True),(1,False),(1,False),'boundary','reset',(4,True),(1,False),(1,False)]
    assert primer['cache_lengths']==[3,4,5] and result['cache_lengths']==[4,5,6]
    fresh=fixed_forward(model,case,'cpu')
    torch.testing.assert_close(result['logits'],fresh['logits'],atol=1e-6,rtol=1e-5)


def test_intervention_requires_actual_owned_completed_bytes():
    selected=[dict(node=4)];ack=dict(accepted_bytes=99)
    good=dict(generation=9001,outcome='completed',transferred_bytes=99,node=4)
    assert preparation_effect([good],ack,selected)
    for override in [dict(generation=1),dict(outcome='cancelled'),dict(transferred_bytes=0),dict(node=5),dict(kind='placement')]:
        assert not preparation_effect([good|override],ack,selected)
    assert not preparation_effect([good],dict(accepted_bytes=0),selected)
    assert not preparation_effect([good],ack,[])
    assert not preparation_effect([],ack,selected)


def packet(root,run_id,case_sha='case',changed=False):
    root.mkdir()
    x=torch.tensor([[[1.,2.,3.],[3.,2.,1.]]])
    if changed:x[0,1,0]=0.
    torch.save(dict(logits=x,prompt_ids=[1,2],continuation_ids=[3],cache_lengths=[2,3]),root/'scores.pt')
    m=dict(case_sha256=case_sha,config_sha256='config',model_revision='r',checkpoint_manifest_sha256='m',seed=1,
           attention='eager',torch_version='t',cuda='c',gpu='g',source_commit='s',script_sha256='script',
           transformers_version='hf',accelerate_version='ac',
           intervention=dict(initial_snapshot=[dict(layer=0,expert=0,nbytes=4,device='cpu')],
                             boundary_snapshot=[dict(layer=0,expert=0,nbytes=4,device='cpu')]),
           native_boot=dict(expert_cache_limit_bytes=4,expert_count=1,applied_config={}),
           source_dirty=False,model_training=False,mode='native-demand',scores_sha256=digest(root/'scores.pt'))
    (root/'capture.json').write_text(json.dumps(m))
    (root/'supervisor.json').write_text(json.dumps(dict(capture_qualified=True,owned_worker_exited=True,
        returncode=0,run_id=run_id,capture_sha256=digest(root/'capture.json'))))


def test_comparison_and_rejection(tmp_path):
    packet(tmp_path/'a','a');packet(tmp_path/'b','b');packet(tmp_path/'changed','c',changed=True)
    assert comparison(tmp_path/'a',tmp_path/'b')['reference_relative_tolerance_pass']
    assert not comparison(tmp_path/'a',tmp_path/'changed')['reference_relative_tolerance_pass']
    with pytest.raises(ValueError,match='same capture'):comparison(tmp_path/'a',tmp_path/'a')
    packet(tmp_path/'mismatch','d',case_sha='different')
    with pytest.raises(ValueError,match='unmatched case'):comparison(tmp_path/'a',tmp_path/'mismatch')
    (tmp_path/'b'/'scores.pt').write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='score hash'):comparison(tmp_path/'a',tmp_path/'b')


@pytest.mark.parametrize('snapshot',['initial_snapshot','boundary_snapshot'])
def test_native_state_mismatch_rejected(tmp_path,snapshot):
    packet(tmp_path/'a','a');packet(tmp_path/'b','b')
    path=tmp_path/'b'/'capture.json'
    m=json.loads(path.read_text());m['intervention'][snapshot][0]['device']='cuda:0'
    path.write_text(json.dumps(m))
    supervisor=tmp_path/'b'/'supervisor.json'
    s=json.loads(supervisor.read_text());s['capture_sha256']=digest(path)
    supervisor.write_text(json.dumps(s))
    with pytest.raises(ValueError,match='expert placement'):comparison(tmp_path/'a',tmp_path/'b')


def test_primer_difference_cannot_hide_behind_equal_target(tmp_path):
    for name in ['a','b']:
        directory=tmp_path/name
        packet(directory,name)
        x=torch.load(directory/'scores.pt',weights_only=True)
        if name=='b':x['logits'][0,0,0]+=5
        torch.save(x,directory/'primer-scores.pt')
        metadata=directory/'capture.json'
        m=json.loads(metadata.read_text());m['primer_scores_sha256']=digest(directory/'primer-scores.pt')
        metadata.write_text(json.dumps(m))
        supervisor=directory/'supervisor.json'
        s=json.loads(supervisor.read_text());s['capture_sha256']=digest(metadata)
        supervisor.write_text(json.dumps(s))
    result=comparison(tmp_path/'a',tmp_path/'b')
    assert result['reference_relative_tolerance_pass']
    assert not result['both_stages_reference_relative_tolerance_pass']


def test_supervisor_preserves_failed_worker(tmp_path):
    script=Path(__file__).resolve().parents[1]/'studies/energy_diagnosis/diagnostics/capture_fixed_forward.py'
    out=tmp_path/'failure'
    r=subprocess.run([sys.executable,str(script),'--config',str(tmp_path/'missing'),
                      '--case',str(tmp_path/'missing-case'),'--mode','reference','--output',str(out)],timeout=30)
    assert r.returncode==2
    status=json.loads((out/'supervisor.json').read_text())
    assert status['owned_worker_exited'] and not status['capture_qualified']
    assert 'FileNotFoundError' in (out/'worker.log').read_text()
