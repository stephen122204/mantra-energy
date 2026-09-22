"""Bounded SQL pipeline repair; generated inputs and independent CSV verification."""
import csv
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash
from .query_workload import QueryTool

VERSION='etl-latest-record-v1'
BUGGY='SELECT region, COUNT(*) AS event_count, SUM(gross_cents + tax_cents) AS net_cents FROM raw GROUP BY region ORDER BY region'


def create_task(root, *, rows=8192, seed=7):
    if type(rows) is not int or not 32<=rows<=1_000_000 or type(seed) is not int or not 0<=seed<2**31:
        raise ValueError('invalid bounded rows or seed')
    root=Path(root);root.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as temp:
        stage=Path(temp)/'assets';stage.mkdir()
        with (stage/'raw.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.writer(f,lineterminator='\n')
            writer.writerow(['seq','event_id','region','gross_cents','tax_cents','status'])
            for i in range(rows):
                writer.writerow([i,i//2,f'r{(i//2+seed)%5}',(i*17+seed)%5000,(i*3+seed)%300,'paid' if (i+seed)%7 else 'cancelled'])
        db=sqlite3.connect(stage/'raw.sqlite')
        try:
            db.execute('CREATE TABLE raw(seq INTEGER PRIMARY KEY,event_id INTEGER,region TEXT,gross_cents INTEGER,tax_cents INTEGER,status TEXT)')
            with (stage/'raw.csv').open(newline='',encoding='utf-8') as f:
                db.executemany('INSERT INTO raw VALUES (?,?,?,?,?,?)',((int(r['seq']),int(r['event_id']),r['region'],int(r['gross_cents']),int(r['tax_cents']),r['status']) for r in csv.DictReader(f)))
            db.commit()
        finally:db.close()
        (stage/'pipeline.sql').write_text(BUGGY+'\n',encoding='utf-8')
        (stage/'source.json').write_text(json.dumps(dict(version=VERSION,rows=rows,seed=seed,source='synthetic versioned event records'),sort_keys=True)+'\n')
        fingerprint=_hash(stage)
        if root.exists():
            if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')) or _hash(root)!=fingerprint:raise ValueError('existing ETL assets differ')
        else:stage.rename(root)
    return PilotTask(f'etl-latest-v1-n{rows}-s{seed}','etl-sql-repair','synthetic-versioned-events-v1',root,{},fingerprint,(),
        'Repair pipeline.sql. raw contains versioned events: retain only the row with maximum seq for each event_id, then exclude events whose latest status is not paid. '
        'Group surviving events by region. Return columns region, event_count, net_cents, where net_cents sums gross_cents minus tax_cents. Keep negative/zero amounts. '
        'Order rows by region ascending. Use the etl tool to read the query/schema, write one read-only SELECT, and test its output. Return {done:true} when repaired. '
        'The repaired query must also work on additional inputs with this schema and the same rules. '
        'This is SQL query repair; no Python code or database mutation is permitted.')


def reference(task):
    latest={}
    with (task.asset_path/'raw.csv').open(newline='',encoding='utf-8') as f:
        for r in csv.DictReader(f):
            key=int(r['event_id'])
            if key not in latest or int(r['seq'])>int(latest[key]['seq']):latest[key]=r
    groups={}
    for r in latest.values():
        if r['status']!='paid':continue
        n,cents=groups.get(r['region'],(0,0))
        groups[r['region']]=n+1,cents+int(r['gross_cents'])-int(r['tax_cents'])
    return [[region,*groups[region]] for region in sorted(groups)]


class ETLTool:
    def __init__(self,root):self.root=Path(root)
    def execute(self,action,content=None,workers=1):
        if workers!=1 or action not in {'read','write','test'}:raise ValueError('invalid ETL action')
        path=self.root/'pipeline.sql'
        if action=='write':
            if not isinstance(content,str) or not content.strip() or len(content.encode())>32768:raise ValueError('provide bounded SQL content')
            # Authorizer is applied at execution; writing text never executes it.
            path.write_text(content,encoding='utf-8')
            return {'written':True}
        if content is not None:raise ValueError('content only allowed for write')
        query=QueryTool(str(self.root/'raw.sqlite'),tables=('raw',))
        if action=='read':return dict(source=path.read_text(encoding='utf-8'),schema=query.execute('schema'))
        return query.execute('query',path.read_text(encoding='utf-8'))


class ETLRuntime:
    def __init__(self,root):self.root=Path(root)
    def begin(self,task,lease):
        if _hash(task.asset_path)!=task.asset_sha256:raise ValueError('ETL inputs changed')
        self.workspace=self.root/'workspaces'/lease.execution_id
        shutil.copytree(task.asset_path,self.workspace)
    def context(self,task):
        return dict(family=task.family,tools={'etl':{'description':'Read query/schema, replace pipeline.sql, or execute the query. Dependent read/write/test calls must occur in order.','args':{'action':'read|write|test','content':'write only; complete SQL'}}},instruction='Return JSON {"tool_calls":[{"id":"unique","tool":"etl","args":{...}}]} or {"answer":{"done":true}}. Use actual tool results. No other tool arguments.')
    def tool(self,task,call):
        args=call.get('args',{})
        if call.get('tool')!='etl' or not isinstance(args,dict) or set(args)-{'action','content'}:raise ValueError('invalid ETL tool schema')
        return ETLTool(self.workspace)
    def verify(self,task,answer):
        if not isinstance(answer,dict) or set(answer)!={'done'} or answer['done'] is not True:return dict(passed=False,reason='invalid completion answer')
        if _hash(task.asset_path)!=task.asset_sha256:raise ValueError('ETL inputs changed')
        # Reuse immutable original DB, not a model-writable workspace database.
        sql=(self.workspace/'pipeline.sql').read_text(encoding='utf-8')
        def matches(candidate):
            try:
                result=QueryTool(str(candidate.asset_path/'raw.sqlite'),tables=('raw',)).execute('query',sql)
            except (ValueError,sqlite3.DatabaseError):return False
            rows=result['rows']
            return (result['columns']==['region','event_count','net_cents'] and not result['truncated']
                    and all(len(r)==3 and type(r[0]) is str and type(r[1]) is int and type(r[2]) is int for r in rows)
                    and rows==reference(candidate))
        if not matches(task):return dict(passed=False,reason='query failed independent input check')
        # Private verifier fixtures are never copied to the model workspace.
        with tempfile.TemporaryDirectory() as directory:
            for seed in (5,17):
                candidate=create_task(Path(directory)/f'case{seed}',rows=65+seed,seed=seed)
                if not matches(candidate):return dict(passed=False,reason='query failed additional input check')
        return dict(passed=True,reason='independent CSV checks on original and additional inputs')
