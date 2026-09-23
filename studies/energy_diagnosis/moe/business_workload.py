"""Synthetic business-query variants using bounded SQLite and CSV references."""
import csv
import json
from pathlib import Path
import sqlite3
import tempfile
from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash
from .query_workload import QueryTool
from .tool_contracts import SQL_ACTIONS, sql_contract, validate_action

VERSION = 'business-query-v1'
PROMPTS = {
    'segments': 'Join transactions to customers. Include only paid transactions in year 2025 with a matching customer. Return {by_segment:{segment:{count:integer,cents:integer}}}. Keep zero and negative paid amounts. Count each transaction row separately.',
    'orphans': 'Find paid transactions in year 2025 with no matching customer, including NULL customer IDs. Return {count:integer,cents:integer}. Count rows separately and retain zero/negative amounts.',
    'declines': 'For each segment, sum matched paid transaction cents separately for 2024 and 2025. Return {segments:[sorted segment names]} for segments whose 2024 sum is positive and whose 2025 sum is strictly less than 80% of the 2024 sum. Missing year sums are zero. Use exact integer comparison.',
}


def create_tasks(root, *, rows=8192, seed=7):
    if type(rows) is not int or not 32 <= rows <= 1_000_000 or type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('invalid bounded rows or seed')
    root=Path(root);root.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as temp:
        stage=Path(temp)/'assets';stage.mkdir()
        customers=[(i,f's{i%5}') for i in range(1,101)]
        with (stage/'customers.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f,lineterminator='\n');w.writerow(['customer_id','segment']);w.writerows(customers)
        with (stage/'transactions.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f,lineterminator='\n');w.writerow(['id','customer_id','year','cents','status'])
            for i in range(rows):
                customer=None if i%31==0 else 1+(i+seed)%107
                year=2024+i%2
                cents=((i*13+seed)%2001)-100
                if year==2025 and customer and customer%5==0: cents//=4
                w.writerow([i,customer,year,cents,'paid' if i%7 else 'refunded'])
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
    return tuple(PilotTask(f'business-{kind}-v1-n{rows}-s{seed}','business-query','synthetic-business-v1',root,{},fingerprint,(),prompt) for kind,prompt in PROMPTS.items())


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
        import shutil
        if _hash(task.asset_path)!=task.asset_sha256:raise ValueError('business inputs changed')
        self.workspace=self.root/'workspaces'/lease.execution_id
        shutil.copytree(task.asset_path,self.workspace)
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
