"""Scripted task decisions for simulated runs only; consumes actual tool outputs."""
import json

SQL = {
    'segments': "SELECT segment,COUNT(*),SUM(cents) FROM transactions JOIN customers USING(customer_id) WHERE status='paid' AND year=2025 GROUP BY segment",
    'orphans': "SELECT COUNT(*),COALESCE(SUM(cents),0) FROM transactions t LEFT JOIN customers c ON t.customer_id=c.customer_id WHERE status='paid' AND year=2025 AND c.customer_id IS NULL",
    'declines': "SELECT segment FROM transactions JOIN customers USING(customer_id) WHERE status='paid' GROUP BY segment HAVING SUM(CASE WHEN year=2024 THEN cents ELSE 0 END)>0 AND 5*SUM(CASE WHEN year=2025 THEN cents ELSE 0 END)<4*SUM(CASE WHEN year=2024 THEN cents ELSE 0 END) ORDER BY segment",
}
REPAIR="SELECT r.region, COUNT(*) AS event_count, SUM(r.gross_cents-r.tax_cents) AS net_cents FROM raw r JOIN (SELECT event_id,MAX(seq) AS latest FROM raw GROUP BY event_id) v ON r.event_id=v.event_id AND r.seq=v.latest WHERE r.status='paid' GROUP BY r.region ORDER BY r.region"



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
        elif family=='python-transformation':
            if not history:decision=call('program',action='read')
            elif len(history)==1:decision=call('program',action='write',content=PROGRAMS[history[-1]['result']['case']])
            elif len(history)==2:decision=call('program',action='test')
            else:decision={'answer':{'done':True}}
        elif family=='grouped-regression':
            decision=call('regression',action='fit') if not history else {'answer':history[-1]['result']}
        else:
            kind=context['task_id'].split('-')[1]
            if not history:decision=call('sql',action='schema')
            elif len(history)==1:decision=call('sql',action='query',sql=SQL[kind])
            else:
                rows=history[-1]['result']['rows']
                if kind=='segments':answer={'by_segment':{s:{'count':n,'cents':c} for s,n,c in rows}}
                elif kind=='orphans':answer={'count':rows[0][0],'cents':rows[0][1]}
                else:answer={'segments':[r[0] for r in rows]}
                decision={'answer':answer}
        if 'answer' in decision and self.case=='wrong_answer':decision={'answer':{'wrong':True}}
        return {'status':'ok','content':json.dumps(decision),'tokens':{'prompt':10,'completion':10},'token_provenance':'estimated'}


# Known solutions for simulated pipeline qualification only. Never given to a live model.
PROGRAMS = {
    'conditional-dedup': "def solve(data):\n    seen=set()\n    out=[]\n    for r in data:\n        if r['url'] not in seen or r['keep']:\n            out.append(r['id'])\n        seen.add(r['url'])\n    return out\n",
    'user-histogram': "def solve(data):\n    bins=data['bins']\n    out={}\n    for r in data['records']:\n        counts=out.setdefault(r['user'],[0]*(len(bins)-1))\n        for j in range(len(bins)-1):\n            if bins[j]<r['views']<=bins[j+1]:\n                counts[j]+=1\n    return out\n",
}
