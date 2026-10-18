"""A missing usage field is not zero unless isolated counter evidence establishes it."""
from types import SimpleNamespace

import pytest

from studies.paper2.cohort import guards
from studies.paper2.cohort.fake_server import FakeVllm


@pytest.mark.parametrize('fault,expected', [(None,True),('warm',True),('missing',False),
    ('no_lookup',False),('disagree',False),('reset_ignored',False),('decrease',False)])
def test_counter_evidence_rules(monkeypatch,fault,expected):
    state=dict(q=100,h=20,warm=fault=='warm',requests=0)
    monkeypatch.setattr(guards,'COUNTER_TIMEOUT_S',0,raising=False)
    monkeypatch.setattr(guards,'wait_drained',lambda *a,**kw:dict(drained=True))
    def metrics(_):
        if fault=='missing': return 'vllm:prefix_cache_queries_total 100\n'
        return f"vllm:prefix_cache_queries_total {state['q']}\nvllm:prefix_cache_hits_total {state['h']}\n"
    def post(url,path,body=None,**kw):
        if path=='/reset_prefix_cache':
            if fault!='reset_ignored': state['warm']=False
            return 200,None
        hits=64 if state['warm'] else 0
        state['q'] += -1 if fault=='decrease' else (0 if fault=='no_lookup' else 64)
        state['h'] += hits;state['warm']=True;state['requests']+=1
        usage={'prompt_tokens':64}
        # Real 0.10.2 omits the field for zero hits.
        if hits: usage['prompt_tokens_details']={'cached_tokens':hits+(16 if fault=='disagree' else 0)}
        return 200,dict(usage=usage)
    monkeypatch.setattr(guards,'fetch_metrics',metrics)
    monkeypatch.setattr(guards,'_post',post)
    result=guards.verified_cache_reset('fixture','model',list(range(64)))
    assert result['ok'] is expected
    assert result['probes']  # retain evidence even on failure
    if expected:
        assert result['probes']['warm']['delta_h']==64
        assert result['probes']['cold']['delta_h']==0
        assert result['probes']['cold']['cached_tokens'] is None
        assert result['probes']['cold']['delta_q']==64
        for p in result['probes'].values():
            assert p['before'] and p['after'] and p['probe_tokens']==64


def test_fake_server_matches_zero_usage_omission_and_counter_semantics():
    with FakeVllm(SimpleNamespace()) as server:
        server.answer_ids=lambda:[7]
        _,first=guards._post(server.base_url,'/v1/completions',dict(prompt=list(range(64)),max_tokens=1))
        assert 'prompt_tokens_details' not in first['usage']
        result=guards.verified_cache_reset(server.base_url,'fixture',list(range(64)))
        assert result['ok']
        assert result['probes']['warm']['delta_h']==64
        assert result['probes']['cold']['delta_h']==0
        assert result['probes']['cold']['delta_q']==64


@pytest.mark.parametrize('metrics', ['vllm:prefix_cache_queries_total NaN\nvllm:prefix_cache_hits_total 0\n',
                                   'vllm:prefix_cache_queries_total 10\nvllm:prefix_cache_hits_total -1\n'])
def test_invalid_counters_fail(monkeypatch,metrics):
    monkeypatch.setattr(guards,'wait_drained',lambda *a,**kw:dict(drained=True))
    monkeypatch.setattr(guards,'fetch_metrics',lambda _:metrics)
    result=guards.verified_cache_reset('fixture','m',list(range(64)))
    assert not result['ok']


def test_nonidle_server_cannot_supply_isolated_counter_evidence(monkeypatch):
    monkeypatch.setattr(guards,'wait_drained',lambda *a,**kw:dict(drained=False))
    result=guards.verified_cache_reset('fixture','m',list(range(64)))
    assert not result['ok']


def test_replay_does_not_report_missing_cache_usage_as_zero(tmp_path):
    from studies.paper2.cohort.replay import ReplaySession, ReplayTurn, run_replay
    session=ReplaySession('s','t',[ReplayTurn(list(range(64)),[8],0)])
    with FakeVllm(SimpleNamespace()) as server:
        result=run_replay('replay',[session],server.base_url,'fixture',tmp_path,admission_limit=1)
    assert result['failed']==0 and result['mismatched_turns']==0
    assert result['cached_tokens'] is None


@pytest.mark.parametrize('which',[1,2])
def test_both_reset_requests_must_succeed(monkeypatch,which):
    with FakeVllm(SimpleNamespace()) as server:
        server.answer_ids=lambda:[7]
        post=guards._post; count=[0]
        def fail_reset(url,path,*args,**kwargs):
            if path=='/reset_prefix_cache':
                count[0]+=1
                if count[0]==which: return 503,None
            return post(url,path,*args,**kwargs)
        monkeypatch.setattr(guards,'_post',fail_reset)
        result=guards.verified_cache_reset(server.base_url,'fixture',list(range(64)))
        assert not result['ok']
