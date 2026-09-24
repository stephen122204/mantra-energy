"""Injected model/sensors, real tools and campaign persistence for every pack task.

Production CLI and per-task verifier hashing are checked separately in test_task_pack_cli.py.
"""
import json
from studies.energy_diagnosis.agent_protocol import ScriptedChatAdapter
import pytest
from studies.energy_diagnosis.moe import run as campaign
from studies.energy_diagnosis.moe.task_pack import prepare

SQL = {
    'segments': "SELECT segment,COUNT(*),SUM(cents) FROM transactions JOIN customers USING(customer_id) WHERE status='paid' AND year=2025 GROUP BY segment",
    'orphans': "SELECT COUNT(*),COALESCE(SUM(cents),0) FROM transactions t LEFT JOIN customers c ON t.customer_id=c.customer_id WHERE status='paid' AND year=2025 AND c.customer_id IS NULL",
    'declines': "SELECT segment FROM transactions JOIN customers USING(customer_id) WHERE status='paid' GROUP BY segment HAVING SUM(CASE WHEN year=2024 THEN cents ELSE 0 END)>0 AND 5*SUM(CASE WHEN year=2025 THEN cents ELSE 0 END)<4*SUM(CASE WHEN year=2024 THEN cents ELSE 0 END) ORDER BY segment",
}
REPAIR="SELECT r.region, COUNT(*) AS event_count, SUM(r.gross_cents-r.tax_cents) AS net_cents FROM raw r JOIN (SELECT event_id,MAX(seq) AS latest FROM raw GROUP BY event_id) v ON r.event_id=v.event_id AND r.seq=v.latest WHERE r.status='paid' GROUP BY r.region ORDER BY r.region"
SPECS=[dict(kind=k,rows=8192,seed=7) for k in ('business','numerical','etl')]


class ScriptedModel:
    def __init__(self,case):
        self.case=case
        self.model_config={'request_timeout_seconds':30,'max_tokens':512}
    def call(self,prompt,temperature):
        context=json.loads(prompt);history=context['tool_results'];family=context['family']
        assert 'expected' not in context
        def call(tool,**args):return {'tool_calls':[{'id':f'call{len(history)}','tool':tool,'args':args}]}
        if family=='etl-sql-repair':
            if not history:decision=call('etl',action='read')
            elif len(history)==1:decision=call('etl',action='write',content=REPAIR)
            elif len(history)==2:decision=call('etl',action='test')
            else:decision={'answer':{'done':True}}
        elif family=='grouped-regression':
            decision=call('regression',action='fit') if not history else {'answer':history[-1]['result']}
        else:
            kind=context['task_id'].split('-')[1]
            if not history:decision=call('sql',action='query',sql=SQL[kind])
            else:
                rows=history[-1]['result']['rows']
                if kind=='segments':answer={'by_segment':{s:{'count':n,'cents':c} for s,n,c in rows}}
                elif kind=='orphans':answer={'count':rows[0][0],'cents':rows[0][1]}
                else:answer={'segments':[r[0] for r in rows]}
                decision={'answer':answer}
        if 'answer' in decision and self.case=='wrong_answer':decision={'answer':{'wrong':True}}
        return {'status':'ok','content':json.dumps(decision),'tokens':{'prompt':10,'completion':10},'token_provenance':'estimated'}


@pytest.mark.parametrize('case',['success','wrong_answer','missing_telemetry'])
def test_all_pack_tasks_through_existing_executor_and_resume(tmp_path,monkeypatch,case):
    holder={}
    def tasks(root):
        holder['pack']=prepare(root,SPECS)
        return holder['pack'].tasks
    monkeypatch.setattr(campaign,'create_tasks',tasks)
    monkeypatch.setattr(campaign,'WorkloadRuntime',lambda root,fixture_case=None:holder['pack'].runtime(root))
    monkeypatch.setattr(campaign,'BackendAdapter',lambda backend,max_tokens:ScriptedChatAdapter(ScriptedModel(case)))
    output=tmp_path/'run'
    args=['--mode','fixture','--output',str(output),'--policies','demand','--max-runs','5','--deadline','30','--fixture-case',case]
    campaign.main(args)
    records=[json.loads(p.read_text()) for p in (output/'goals').glob('*/record.json')]
    assert len(records)==5
    assert {r['task_id'] for r in records}=={t.task_id for t in holder['pack'].tasks}
    for record in records:
        assert record['execution_status']=='completed'
        assert record['verifier']['outcome']==('fail' if case=='wrong_answer' else 'pass')
        assert record['simulated']
        if case=='missing_telemetry':assert any(m['energy_j'] is None for m in record['measurements'])
        else:assert all(m['status']=='valid' for m in record['measurements'])
    export=output/'exports/attempts.jsonl';before=export.read_bytes()
    assert len(before.splitlines())==5
    campaign.main(args)
    assert export.read_bytes()==before
    assert len(list((output/'goals').glob('*/record.json')))==5
