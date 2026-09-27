"""Bounded SQL pipeline repair; generated inputs and independent CSV verification.

v2 replaces the v1 two-row-per-event layout (event_id=seq//2), which let
sequence-parity shortcuts pass visible and hidden checks on vulnerable inputs,
with irregular versioned events.
"""
import csv
import json
from pathlib import Path
import random
import shutil
import sqlite3
import tempfile
from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash
from .query_workload import QueryTool
from .tool_contracts import ETL_ACTIONS, action_contract, validate_action

VERSION='etl-latest-record-v2'
BUGGY='SELECT region, COUNT(*) AS event_count, SUM(gross_cents + tax_cents) AS net_cents FROM raw GROUP BY region ORDER BY region'
COLUMNS=['seq','event_id','region','gross_cents','tax_cents','status']
REGIONS=('central','coastal','east','mountain','north','south','west')
STATUSES=('paid','paid','paid','cancelled','refunded','pending')


def generate(rows,rng):
    """1..6 versions per event, sparse event ids, versions interleaved across
    events, nonconsecutive seq with random parity, and region/status/amount
    changes between versions. Returns (seq,event_id,region,gross,tax,status)."""
    counts=[];left=rows
    while left:
        k=min(left,rng.choice((1,1,1,2,2,3,3,4,5,6)));counts.append(k);left-=k
    ids=rng.sample(range(4*len(counts)+64),len(counts))
    order=[e for e,k in zip(ids,counts) for _ in range(k)];rng.shuffle(order)
    regions=REGIONS[:rng.randint(3,len(REGIONS))]
    region={e:rng.choice(regions) for e in ids}
    records=[];seq=rng.randint(0,7)
    for e in order:
        seq+=rng.randint(1,4)
        if rng.random()<0.25:region[e]=rng.choice(regions)
        gross=0 if rng.random()<0.05 else rng.randint(1,5000)
        records.append((seq,e,region[e],gross,rng.randint(0,600),rng.choice(STATUSES)))
    return records


def _materialize(stage,records,rng=None):
    rows=list(records)
    if rng is not None:rng.shuffle(rows)  # file order differs from seq order
    with (stage/'raw.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerow(COLUMNS);writer.writerows(rows)
    db=sqlite3.connect(stage/'raw.sqlite')
    try:
        db.execute('CREATE TABLE raw(seq INTEGER PRIMARY KEY,event_id INTEGER,region TEXT,gross_cents INTEGER,tax_cents INTEGER,status TEXT)')
        with (stage/'raw.csv').open(newline='',encoding='utf-8') as f:
            db.executemany('INSERT INTO raw VALUES (?,?,?,?,?,?)',((int(r['seq']),int(r['event_id']),r['region'],int(r['gross_cents']),int(r['tax_cents']),r['status']) for r in csv.DictReader(f)))
        db.commit()
    finally:db.close()


def create_task(root, *, rows=8192, seed=7, variant=None):
    if type(rows) is not int or not 32<=rows<=1_000_000 or type(seed) is not int or not 0<=seed<2**31:
        raise ValueError('invalid bounded rows or seed')
    variant=validate_variant(variant)
    root=Path(root);root.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as temp:
        stage=Path(temp)/'assets';stage.mkdir()
        rng=random.Random(f'{VERSION}:{seed}')
        _materialize(stage,generate(rows,rng),rng)
        (stage/'pipeline.sql').write_text(BUGGY+'\n',encoding='utf-8')
        if variant and variant['index']:
            db=sqlite3.connect(stage/'raw.sqlite')
            try:
                db.execute('CREATE INDEX raw_event_seq ON raw(event_id, seq)');db.commit()
            finally:db.close()
        meta=dict(version=VERSION,rows=rows,seed=seed,source='synthetic versioned event records')
        if variant is not None:meta['variant']=variant
        (stage/'source.json').write_text(json.dumps(meta,sort_keys=True)+'\n')
        fingerprint=_hash(stage)
        if root.exists():
            if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')) or _hash(root)!=fingerprint:raise ValueError('existing ETL assets differ')
        else:stage.rename(root)
    return PilotTask(f'etl-latest-v2-n{rows}-s{seed}'+variant_suffix(variant),'etl-sql-repair','synthetic-versioned-events-v2',root,{},fingerprint,(),
        'Repair pipeline.sql. raw contains versioned events: retain only the row with maximum seq for each event_id, then exclude events whose latest status is not paid. '
        'Group surviving events by region. Return columns region, event_count, net_cents, where net_cents sums gross_cents minus tax_cents. Keep negative/zero amounts. '
        'Order rows by region ascending. Use the etl tool to read the query/schema, write one read-only SELECT, and test its output. Return {done:true} when repaired. '
        'The repaired query must also work on additional inputs with this schema and the same rules. '
        'This is SQL query repair; no Python code or database mutation is permitted.')


def hidden_cases():
    """Verifier-only inputs; never copied to the model workspace."""
    # Hand-built edge cases: single-version events, latest non-paid after paid,
    # paid after non-paid, region change, negative/zero net, sparse and large
    # event ids, seq gaps, and a region whose only event ends cancelled.
    yield [(3,9,'east',500,20,'paid'),(40,9,'east',700,30,'cancelled'),
           (5,5,'north',100,10,'paid'),
           (7,2,'west',50,5,'cancelled'),(8,2,'west',60,80,'paid'),
           (11,1000000,'north',10,0,'paid'),(12,1000000,'south',20,0,'paid'),(90,1000000,'south',0,0,'paid'),
           (13,0,'north',300,1,'refunded'),(14,0,'north',300,2,'pending'),(15,0,'north',300,0,'paid'),
           (20,77,'central',1,1,'paid'),(21,77,'central',2,1,'paid'),(22,77,'central',3,1,'paid'),(23,77,'central',9,2,'paid'),
           (30,31,'coastal',400,0,'paid'),(31,31,'coastal',400,0,'cancelled')]
    # v1 pair layout with seq shifted by one: parity shortcuts select the
    # earlier version, and statuses/amounts differ within each pair.
    yield [(i+1,i//2,REGIONS[(i//2)%4],(i*37)%900,(i*11)%120,'paid' if i%3 else 'cancelled') for i in range(96)]
    for seed,rows in ((1009,97),(2027,211),(40961,64)):
        yield generate(rows,random.Random(f'{VERSION}:hidden:{seed}'))


def reference_records(records):
    latest={}
    for r in records:
        if r[1] not in latest or r[0]>latest[r[1]][0]:latest[r[1]]=r
    groups={}
    for _,_,region,gross,tax,status in latest.values():
        if status!='paid':continue
        n,cents=groups.get(region,(0,0))
        groups[region]=n+1,cents+gross-tax
    return [[region,*groups[region]] for region in sorted(groups)]


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


# Execution budget for the SQL tool and the verifier (stated to the model as 10 seconds).
QUERY_SECONDS=10.0
BUDGET_REASON='query did not complete within the execution budget'
# Optional environment variants (default None = the original task, unchanged identity and assets):
#   window_functions: expose SQLite window functions (ROW_NUMBER etc.) in the tool and the verifier
#   feedback: 'generic' (the SQLite error text, e.g. "interrupted") or 'explicit' (a stated budget message)
#   index: build an index on raw(event_id, seq) into the input database
WINDOW_FUNCTIONS=('row_number','rank','dense_rank','percent_rank','cume_dist','ntile','lag','lead',
                  'first_value','last_value','nth_value')
EXPLICIT_BUDGET_MESSAGE='query exceeded the 10-second execution budget and was stopped before returning results'


class QueryBudgetExceeded(Exception):
    pass


def validate_variant(variant):
    if variant is None:return None
    if not isinstance(variant,dict) or set(variant)!={'window_functions','feedback','index'} \
            or type(variant['window_functions']) is not bool or type(variant['index']) is not bool \
            or variant['feedback'] not in ('generic','explicit'):
        raise ValueError('ETL variant requires window_functions (bool), feedback (generic|explicit), index (bool)')
    return dict(variant)


def variant_suffix(variant):
    if variant is None:return ''
    return '-w%df%si%d' % (variant['window_functions'],variant['feedback'][0],variant['index'])


def _variant_of(directory):
    meta=json.loads((Path(directory)/'source.json').read_text())
    return meta.get('variant')


def _functions(variant):
    return WINDOW_FUNCTIONS if variant and variant['window_functions'] else ()


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
        variant=_variant_of(self.root)
        query=QueryTool(str(self.root/'raw.sqlite'),max_seconds=QUERY_SECONDS,tables=('raw',),extra_functions=_functions(variant))
        if action=='read':return dict(source=path.read_text(encoding='utf-8'),schema=query.execute('schema'))
        try:
            return query.execute('query',path.read_text(encoding='utf-8'))
        except sqlite3.OperationalError as exc:
            if variant and variant['feedback']=='explicit' and 'interrupted' in str(exc):
                raise QueryBudgetExceeded(EXPLICIT_BUDGET_MESSAGE) from None
            raise


class ETLRuntime:
    def __init__(self,root):self.root=Path(root)
    def begin(self,task,lease):
        if _hash(task.asset_path)!=task.asset_sha256:raise ValueError('ETL inputs changed')
        self.workspace=self.root/'workspaces'/lease.execution_id
        shutil.copytree(task.asset_path,self.workspace)
    def context(self,task):
        return dict(family=task.family,tools={'etl':{
            'description':'The action argument is mandatory on every call. action="read" takes no content and returns the current SQL and table schema. '
            'action="write" requires content containing the complete replacement SQL and returns written=true. '
            'action="test" takes no content and runs the saved query, returning columns, rows and truncated. '
            'This is bounded read-only SQLite: one SELECT, at most 32768 SQL bytes, 10 seconds, 128 result rows and 65536 output bytes. '
            + ('Joins, subqueries, aggregate functions such as MAX, SUM and COUNT, and window functions such as ROW_NUMBER are supported. '
               if _functions(_variant_of(task.asset_path)) else
               'Joins, subqueries and aggregate functions such as MAX, SUM and COUNT are supported; ranking functions such as ROW_NUMBER are not exposed. ')
            + 'Read, write and test must occur in separate decisions or explicitly ordered dependencies; never run a test concurrently with its write.',
            'args':{'action':'required: read, write or test','content':'required only for write; complete SQL'},
            'parameters':action_contract(ETL_ACTIONS),
            'example_call':{'id':'read_1','tool':'etl','args':{'action':'read'}}}},
            instruction='Return only JSON {"tool_calls":[{"id":"unique","tool":"etl","args":{"action":"read"}}]} or {"answer":{"done":true}}. '
            'Read first, then write the repair, then test the saved query. Use the observed schema and tool outputs. Include action every time; do not supply content to read/test.')
    def tool(self,task,call):
        if call.get('tool')!='etl':raise ValueError('invalid ETL tool schema')
        validate_action(call.get('args'),ETL_ACTIONS)
        return ETLTool(self.workspace)
    def verify(self,task,answer):
        if not isinstance(answer,dict) or set(answer)!={'done'} or answer['done'] is not True:return dict(passed=False,reason='invalid completion answer')
        if _hash(task.asset_path)!=task.asset_sha256:raise ValueError('ETL inputs changed')
        # Reuse immutable original DB, not a model-writable workspace database.
        sql=(self.workspace/'pipeline.sql').read_text(encoding='utf-8')
        def check(database,expected):
            # 'budget' when the query was interrupted by the execution budget, so a correct but too-slow
            # query is not reported as a wrong result.
            try:
                result=QueryTool(str(database),max_seconds=QUERY_SECONDS,tables=('raw',),
                                 extra_functions=_functions(_variant_of(task.asset_path))).execute('query',sql)
            except sqlite3.OperationalError as exc:
                return 'budget' if 'interrupted' in str(exc) else 'error'
            except (ValueError,sqlite3.DatabaseError):return 'error'
            rows=result['rows']
            ok=(result['columns']==['region','event_count','net_cents'] and not result['truncated']
                and all(len(r)==3 and type(r[0]) is str and type(r[1]) is int and type(r[2]) is int for r in rows)
                and rows==expected)
            return 'match' if ok else 'mismatch'
        first=check(task.asset_path/'raw.sqlite',reference(task))
        if first=='budget':return dict(passed=False,reason=BUDGET_REASON+' on the original input',failure='budget')
        if first!='match':return dict(passed=False,reason='query failed independent input check',failure=first)
        with tempfile.TemporaryDirectory() as directory:
            for index,records in enumerate(hidden_cases()):
                stage=Path(directory)/f'case{index}';stage.mkdir()
                _materialize(stage,records,random.Random(index))
                outcome=check(stage/'raw.sqlite',reference_records(records))
                if outcome=='budget':return dict(passed=False,reason=BUDGET_REASON+' on an additional input',failure='budget')
                if outcome!='match':return dict(passed=False,reason='query failed additional input check',failure=outcome)
        return dict(passed=True,reason='independent CSV checks on original and irregular additional inputs')
