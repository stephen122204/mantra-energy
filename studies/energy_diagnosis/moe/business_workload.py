"""Synthetic business-query variants using bounded SQLite and CSV references.

v2 replaces the v1 layout, which could yield the same declines answer across
seeds, with seeded segment names, sparse customer ids, and per-segment decline
categories enforced by adjustment rows (threshold and filter traps).
"""
import csv
import json
from pathlib import Path
import random
import sqlite3
import tempfile
from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash, copy_workspace
from .query_workload import QueryTool
from .tool_contracts import SQL_ACTIONS, sql_contract, validate_action

VERSION = 'business-query-v2'
SEGMENTS = ('consumer','education','enterprise','government','healthcare','nonprofit','retail','startup')
# decline: clearly below 80%; stable: at/above; boundary: exactly 80% (excluded);
# below_boundary: one integer step under 80% (included); nonpositive: 2024 sum
# <= 0 (excluded although 2025 is lower); refund_trap: stable on paid rows but a
# decline if refunded rows are not filtered out.
CATEGORIES = ('decline','stable','boundary','below_boundary','nonpositive','refund_trap')
DECLINING = {'decline','below_boundary'}
PROMPTS = {
    'segments': 'Join transactions to customers. Include only paid transactions in year 2025 with a matching customer. Return {by_segment:{segment:{count:integer,cents:integer}}}. Keep zero and negative paid amounts. Count each transaction row separately.',
    'orphans': 'Find paid transactions in year 2025 with no matching customer, including NULL customer IDs. Return {count:integer,cents:integer}. Count rows separately and retain zero/negative amounts.',
    'declines': 'For each segment, sum matched paid transaction cents separately for 2024 and 2025. Return {segments:[sorted segment names]} for segments whose 2024 sum is positive and whose 2025 sum is strictly less than 80% of the 2024 sum. Missing year sums are zero. Use exact integer comparison.',
}


def generate(rows,rng):
    """Return (customers, transactions, categories); transactions has exactly rows rows."""
    segments=sorted(rng.sample(SEGMENTS,rng.randint(len(CATEGORIES),len(SEGMENTS))))
    # Every category (and so every trap) occurs in every task; which segment
    # gets which category, and so the declines answer, varies by seed.
    kinds=list(CATEGORIES)+[rng.choice(CATEGORIES) for _ in segments[len(CATEGORIES):]];rng.shuffle(kinds)
    category=dict(zip(segments,kinds))
    ids=rng.sample(range(1,20*len(segments)*8),rng.randint(6,12)*len(segments))
    customers=[(c,segments[i%len(segments)]) for i,c in enumerate(ids)]
    known=set(ids);orphans=[c for c in range(1,20*len(segments)*8+40) if c not in known][:40]
    members={s:[c for c,t in customers if t==s] for s in segments}
    customer=rng.choice(ids)
    # Fixed trap rows: non-paid and out-of-range-year matched rows, repeat
    # purchases by one customer, and unmatched rows (NULL and unknown ids,
    # negative amount, refunded).
    extra=[[rng.choice(ids),2025,rng.randint(500,900),'refunded'],[rng.choice(ids),2025,rng.randint(500,900),'failed'],
           [rng.choice(ids),2026,rng.randint(500,900),'paid'],[rng.choice(ids),2023,rng.randint(500,900),'paid'],
           [customer,2025,rng.randint(1,900),'paid'],[customer,2025,rng.randint(1,900),'paid'],
           [None,2025,rng.randint(1,900),'paid'],[rng.choice(orphans),2025,rng.randint(1,900),'paid'],
           [rng.choice(orphans),2025,-rng.randint(1,900),'paid'],[rng.choice(orphans),2025,rng.randint(500,900),'refunded'],
           [None,2024,rng.randint(1,900),'paid']]
    adjustments=len(extra)+2*len(segments)+kinds.count('refund_trap')
    if rows<adjustments:raise ValueError('rows too small for business traps')
    base=[]
    for _ in range(rows-adjustments):
        u=rng.random()
        who=None if u<0.03 else rng.choice(orphans) if u<0.06 else rng.choice(customers)[0]
        year=rng.choice((2024,2025,2024,2025,2023,2026)) if rng.random()<0.1 else rng.choice((2024,2025))
        cents=0 if rng.random()<0.03 else rng.randint(-200,3000)
        base.append([who,year,cents,rng.choices(('paid','refunded','failed'),(8,1,1))[0]])
    segment_of=dict(customers)
    def sums(status_filter):
        total={}
        for who,year,cents,status in base+extra:
            if who in segment_of and (status=='paid' or not status_filter):
                total[segment_of[who],year]=total.get((segment_of[who],year),0)+cents
        return total
    paid=sums(True)
    for s in segments:
        pick=lambda:rng.choice(members[s])
        s24=paid.get((s,2024),0);kind=category[s]
        target24=-rng.randint(1,5000) if kind=='nonpositive' else max(s24,5000)+rng.randint(0,4)
        if kind=='boundary':target24-=target24%5
        extra.append([pick(),2024,target24-s24,'paid'])
        target25={'decline':target24//2,'stable':target24+rng.randint(0,500),'boundary':4*target24//5,
                  'below_boundary':(4*target24-1)//5,'nonpositive':target24-rng.randint(1,5000),
                  'refund_trap':target24}[kind]
        extra.append([pick(),2025,target25-paid.get((s,2025),0),'paid'])
    # Refunded 2024 rows added after paid targets are fixed: stable on paid
    # rows, a decline if refunded rows are counted.
    for s in segments:
        if category[s]=='refund_trap':
            total=sums(False)
            extra.append([rng.choice(members[s]),2024,total.get((s,2025),0)*5//4+1000-total.get((s,2024),0),'refunded'])
    rows_out=base+extra;rng.shuffle(rows_out)
    transactions=[(i+1,*r) for i,r in enumerate(rows_out)]
    assert len(transactions)==rows
    return customers,transactions,category


def create_tasks(root, *, rows=8192, seed=7):
    if type(rows) is not int or not 32 <= rows <= 1_000_000 or type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('invalid bounded rows or seed')
    root=Path(root);root.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as temp:
        stage=Path(temp)/'assets';stage.mkdir()
        customers,transactions,_=generate(rows,random.Random(f'{VERSION}:{seed}'))
        with (stage/'customers.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f,lineterminator='\n');w.writerow(['customer_id','segment']);w.writerows(customers)
        with (stage/'transactions.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f,lineterminator='\n');w.writerow(['id','customer_id','year','cents','status'])
            w.writerows(transactions)
        db=sqlite3.connect(stage/'business.sqlite')
        try:
            db.executescript('CREATE TABLE customers(customer_id INTEGER PRIMARY KEY,segment TEXT); CREATE TABLE transactions(id INTEGER PRIMARY KEY,customer_id INTEGER,year INTEGER,cents INTEGER,status TEXT);')
            db.executemany('INSERT INTO customers VALUES (?,?)',customers)
            with (stage/'transactions.csv').open(newline='',encoding='utf-8') as f:
                db.executemany('INSERT INTO transactions VALUES (?,?,?,?,?)',
                    ((int(r['id']),int(r['customer_id']) if r['customer_id'] else None,int(r['year']),int(r['cents']),r['status']) for r in csv.DictReader(f)))
            db.commit()
        finally:db.close()
        (stage/'source.json').write_text(json.dumps(dict(version=VERSION,rows=rows,seed=seed,source='synthetic deterministic business records'),sort_keys=True)+'\n')
        fingerprint=_hash(stage)
        if root.exists():
            if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')) or _hash(root)!=fingerprint:
                raise ValueError('existing business assets differ')
        else:stage.rename(root)
    return tuple(PilotTask(f'business-{kind}-v2-n{rows}-s{seed}','business-query','synthetic-business-v2',root,{},fingerprint,(),prompt) for kind,prompt in PROMPTS.items())


def reference(task):
    with (task.asset_path/'customers.csv').open(newline='',encoding='utf-8') as f:
        customers={r['customer_id']:r['segment'] for r in csv.DictReader(f)}
    groups={};years={};count=cents=0
    with (task.asset_path/'transactions.csv').open(newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['status']!='paid':continue
            segment=customers.get(r['customer_id']);amount=int(r['cents']);year=int(r['year'])
            if segment is not None:
                years[segment,year]=years.get((segment,year),0)+amount
                if year==2025:
                    bucket=groups.setdefault(segment,dict(count=0,cents=0))
                    bucket['count']+=1;bucket['cents']+=amount
            elif year==2025:count+=1;cents+=amount
    if task.task_id.startswith('business-segments-'):return dict(by_segment=groups)
    if task.task_id.startswith('business-orphans-'):return dict(count=count,cents=cents)
    return dict(segments=sorted(s for s in set(customers.values()) if years.get((s,2024),0)>0 and 5*years.get((s,2025),0)<4*years[s,2024]))


def verify(task,answer):
    if _hash(task.asset_path)!=task.asset_sha256:raise ValueError('business inputs changed')
    expected=reference(task)
    def same(a,b):
        if type(a) is not type(b):return False
        if isinstance(b,dict):return set(a)==set(b) and all(same(a[k],b[k]) for k in b)
        if isinstance(b,list):return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
        return a==b
    return dict(passed=same(answer,expected),reason='independent raw CSV business reference')


class BusinessRuntime:
    def __init__(self,root):self.root=Path(root)
    def begin(self,task,lease):
        if _hash(task.asset_path)!=task.asset_sha256:raise ValueError('business inputs changed')
        self.workspace=self.root/'workspaces'/lease.execution_id
        copy_workspace(task.asset_path,self.workspace)
    def context(self,task):
        return dict(family=task.family,tools={'sql':sql_contract('SQLite')},
            instruction='Return only JSON {"tool_calls":[{"id":"unique","tool":"sql","args":{...}}]} or {"answer":{...}}. '
            'Continue from the observations already present in tool_results; do not restart the task on each response. '
            'If no successful schema result is present, inspect the schema with action="schema". '
            'If table and column names are already present, use them to make a query call with action="query" and sql, rather than requesting the same schema again. '
            'When query results support the requested answer, return it in the goal answer schema. '
            'Use a new call id for each call. Use actual tool results; do not omit action, invent observations or guess column names.')
    def tool(self,task,call):
        if call.get('tool')!='sql':raise ValueError('invalid SQL tool request')
        validate_action(call.get('args'),SQL_ACTIONS)
        return QueryTool(str(self.workspace/'business.sqlite'),tables=('customers','transactions'))
    def verify(self,task,answer):return verify(task,answer)
