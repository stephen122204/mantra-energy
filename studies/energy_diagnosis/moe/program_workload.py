"""Task-level Python transformations with bounded execution and private checks.

Task semantics adapted from DS-1000 7 and 229; see PROGRAM_TASKS.md.
The restricted Python subset is an explicit tool contract, not an OS sandbox.
"""
import ast
import bisect
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash
from .tool_contracts import action_contract, validate_action

VERSION = 'python-transform-v1'
CASES = ('conditional-dedup', 'user-histogram')
ACTIONS = {'read': None, 'write': 'content', 'test': None}
MAX_CODE_BYTES = 32768
MAX_ROWS = 100000
SAFE_BUILTINS = ('abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'float', 'int',
                 'len', 'list', 'max', 'min', 'range', 'reversed', 'round', 'set',
                 'sorted', 'str', 'sum', 'tuple', 'zip')
METHODS = {'append', 'extend', 'get', 'items', 'keys', 'values', 'setdefault',
           'add', 'discard', 'sort', 'count', 'index', 'copy', 'pop'}
PROMPTS = {
    'conditional-dedup': 'Implement solve(data). data is a list of records with integer id, string url, and boolean keep. '
        'Return a list of integer ids in original input order. Keep the first occurrence of every url, '
        'and also keep every record whose keep is true, even when its url occurred earlier. '
        'IDs are unique. A first occurrence with keep=false is still retained. Do not sort or modify the input.',
    'user-histogram': 'Implement solve(data). data has records (each with string user and integer views) and strictly increasing integer bins. '
        'Return a JSON object mapping EVERY user appearing in records to a list of counts, one per adjacent bin pair. '
        'For bins [a,b,c], intervals are (a,b] and (b,c]. Values equal to the first edge or outside the range do not count. '
        'Include users with zero counts. Count repeated records separately. Do not modify the input.',
}


def generate(case, rows, seed):
    if case not in CASES or type(rows) is not int or rows < 8:
        raise ValueError('unknown case or fewer than eight rows')
    rng = random.Random(f'{VERSION}:{case}:{seed}')
    if case == 'conditional-dedup':
        records = [dict(id=i*7+19, url=f'key-{rng.randrange(max(2, rows//5))}', keep=bool(rng.randrange(2))) for i in range(rows)]
        records[:4] = [dict(id=i*7+19, url='forced', keep=k) for i,k in enumerate([False, True, False, True])]
        return records
    edges = sorted(rng.sample(range(-30,150), 5))
    records = [dict(user=f'user-{rng.randrange(9)}', views=rng.randrange(-40,170)) for _ in range(rows)]
    records[:7] = [dict(user='boundary', views=x) for x in [edges[0]-1, *edges, edges[-1]+1]]
    records[7] = dict(user='outside-only', views=edges[-1]+50)
    return dict(records=records, bins=edges)


def reference(case, data):
    # Deliberately different from the fixture solutions; no submitted code is used.
    if case == 'conditional-dedup':
        first = {}
        for index in reversed(range(len(data))):
            first[data[index]['url']] = index
        return [r['id'] for i,r in enumerate(data) if r['keep'] or first[r['url']] == i]
    edges = data['bins']
    out = {r['user']: [0]*(len(edges)-1) for r in data['records']}
    for r in data['records']:
        index = bisect.bisect_left(edges, r['views'])-1
        if 0 <= index < len(edges)-1:
            out[r['user']][index] += 1
    return out


def validate_source(source):
    if not isinstance(source, str) or not source.strip() or len(source.encode()) > MAX_CODE_BYTES:
        raise ValueError('provide nonempty Python source up to 32768 bytes')
    tree = ast.parse(source)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError('define exactly one function solve(data)')
    fn = tree.body[0]
    if fn.name != 'solve' or fn.decorator_list or fn.returns or fn.args.defaults or fn.args.kw_defaults or fn.args.posonlyargs or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg or len(fn.args.args)!=1 or fn.args.args[0].arg!='data' or fn.args.args[0].annotation:
        raise ValueError('define undecorated solve(data) without annotations or defaults')
    banned = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef, ast.Global,
              ast.Nonlocal, ast.With, ast.AsyncWith, ast.Await, ast.Yield, ast.YieldFrom)
    for node in ast.walk(tree):
        if isinstance(node,banned) or (isinstance(node,ast.FunctionDef) and node is not fn):
            raise ValueError('unsupported Python construct')
        if isinstance(node,ast.Name) and node.id.startswith('_'):
            raise ValueError('private names are unavailable')
        if isinstance(node,ast.Attribute) and node.attr not in METHODS:
            raise ValueError('attribute outside permitted container methods')
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id not in SAFE_BUILTINS and node.func.id!='solve':
            raise ValueError('call outside permitted builtins')
    return tree


WORKER = r'''
import builtins, json, sys
try:
    import resource
    if sys.platform == 'linux':
        resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024,512*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU, (12,12))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0,0))
except ImportError:
    pass
job=json.load(sys.stdin)
ns={'__builtins__':{k:getattr(builtins,k) for k in job['builtins']}}
try:
    exec(compile(job['source'], '<submitted>', 'exec'),ns)
    before=json.dumps(job['data'],sort_keys=True,allow_nan=False)
    result=ns['solve'](job['data'])
    if json.dumps(job['data'],sort_keys=True,allow_nan=False)!=before:
        raise ValueError('input mutation')
    print(json.dumps({'status':'ok','result':result},allow_nan=False))
except BaseException as e:
    print(json.dumps({'status':'runtime_error','error':type(e).__name__+': '+str(e)[:200]}))
'''


def execute(source, data, seconds=10):
    try: validate_source(source)
    except (ValueError,SyntaxError) as error:
        return dict(status='invalid_program',error=str(error))
    if type(seconds) not in (int,float) or not 0<seconds<=10:
        raise ValueError('execution budget must be in (0,10] seconds')
    with tempfile.TemporaryDirectory(prefix='alems-program-') as directory:
        worker=Path(directory)/'worker.py';worker.write_text(WORKER)
        try:
            result=subprocess.run([sys.executable,'-I','-S',str(worker)],input=json.dumps(dict(source=source,data=data,builtins=SAFE_BUILTINS),allow_nan=False),
                text=True,capture_output=True,cwd=directory,timeout=seconds,
                env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR'}})
        except subprocess.TimeoutExpired:
            return dict(status='budget_exceeded',error=f'program exceeded {seconds:g} seconds')
        if result.returncode:
            return dict(status='worker_error',error=f'worker exit {result.returncode}')
        try:return json.loads(result.stdout)
        except ValueError:return dict(status='worker_error',error='invalid worker output')


def matches(case, actual, expected):
    # JSON equality alone accepts True == 1; exact output types are required.
    if case=='conditional-dedup':
        return isinstance(actual,list) and all(type(x) is int for x in actual) and actual==expected
    return (isinstance(actual,dict) and set(actual)==set(expected)
        and all(isinstance(v,list) and all(type(x) is int for x in v) for v in actual.values()) and actual==expected)


def create_task(root, *, case, rows=8192, seed=7):
    if case not in CASES or type(rows) is not int or not 32<=rows<=MAX_ROWS or type(seed) is not int or not 0<=seed<2**31:
        raise ValueError('invalid program task specification')
    root=Path(root);root.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as tmp:
        stage=Path(tmp)/'assets';stage.mkdir()
        (stage/'input.json').write_text(json.dumps(generate(case,rows,seed),sort_keys=True)+'\n')
        (stage/'solution.py').write_text('def solve(data):\n    return None\n')
        (stage/'source.json').write_text(json.dumps(dict(version=VERSION,case=case,rows=rows,seed=seed,source='DS-1000 semantics adaptation',problem_id=7 if case=='conditional-dedup' else 229),sort_keys=True)+'\n')
        fingerprint=_hash(stage)
        if root.exists():
            if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')) or _hash(root)!=fingerprint:raise ValueError('existing program assets differ')
        else:stage.rename(root)
    return PilotTask(f'python-{case}-v1-n{rows}-s{seed}','python-transformation',f'ds1000-origin-{7 if case=="conditional-dedup" else 229}',root,{},fingerprint,(),
        PROMPTS[case]+' Use program read/write/test. Submit {done:true} after implementing the function. Additional unseen inputs obey the same contract.')


class ProgramTool:
    def __init__(self,root):self.root=Path(root)
    def execute(self,action,content=None,workers=1):
        if workers!=1:raise ValueError('program tool uses one worker')
        args={'action':action}
        if content is not None:args['content']=content
        validate_action(args,ACTIONS)
        path=self.root/'solution.py'
        if action=='write':
            validate_source(content);path.write_text(content);return {'written':True}
        meta=json.loads((self.root/'source.json').read_text());data=json.loads((self.root/'input.json').read_text())
        if action=='read':
            sample=data[:8] if isinstance(data,list) else dict(records=data['records'][:8],bins=data['bins'])
            return dict(source=path.read_text(),sample=sample,rows=meta['rows'],case=meta['case'])
        result=execute(path.read_text(),data)
        if result['status']!='ok':return result
        ok=matches(meta['case'],result['result'],reference(meta['case'],data))
        return dict(status='ok',passed=ok,output_sha256=hashlib.sha256(json.dumps(result['result'],sort_keys=True).encode()).hexdigest())


class ProgramRuntime:
    def __init__(self,root):self.root=Path(root)
    def begin(self,task,lease):
        if _hash(task.asset_path)!=task.asset_sha256:raise ValueError('program inputs changed')
        self.workspace=self.root/'workspaces'/lease.execution_id
        shutil.copytree(task.asset_path,self.workspace)
    def context(self,task):
        return dict(family=task.family,tools={'program':dict(description=
            'read returns source, input sample and metadata; write replaces solution.py; test executes it on full visible input and checks output. '
            'Define exactly solve(data). Python loops, comprehensions, arithmetic and container operations are supported. '
            f'Builtins: {", ".join(SAFE_BUILTINS)}. Container methods: {", ".join(sorted(METHODS))}. '
            'No imports, file/network access, private attributes, helper definitions, annotations or input mutation. '
            'Execution limit: 10 seconds; on Linux 512 MiB address space. Read/write/test are separate decisions.',
            parameters=action_contract(ACTIONS),args={'action':'read, write, test','content':'source for write only'})},instruction='Return tool calls or final {"answer":{"done":true}}. Use tool feedback.')
    def tool(self,task,call):
        if call.get('tool')!='program':raise ValueError('invalid program tool')
        validate_action(call.get('args'),ACTIONS);return ProgramTool(self.workspace)
    def verify(self,task,answer):
        if type(answer) is not dict or set(answer)!={'done'} or answer['done'] is not True:return dict(passed=False,reason='invalid completion answer')
        if _hash(task.asset_path)!=task.asset_sha256:raise ValueError('program inputs changed')
        meta=json.loads((task.asset_path/'source.json').read_text());case=meta['case']
        path=self.workspace/'solution.py'
        if not path.is_file() or path.is_symlink():return dict(passed=False,reason='missing_or_invalid_program')
        source=path.read_text()
        inputs=[json.loads((task.asset_path/'input.json').read_text())]+[generate(case,n,s) for n,s in [(32,7919),(73,15401),(251,32443)]]
        inputs += edge_cases(case)
        for data in inputs:
            result=execute(source,data)
            # failure carries the class (budget_exceeded, runtime_error, worker_error, mismatch) to the attempt outcome.
            if result['status']!='ok':return dict(passed=False,reason=result['status'],failure=result['status'])
            if not matches(case,result['result'],reference(case,data)):return dict(passed=False,reason='incorrect_result',failure='mismatch')
        return dict(passed=True,reason='original and unseen input checks')


def edge_cases(case):
    """Small boundaries absent from the generated visible layout."""
    if case == 'conditional-dedup':
        return [[], [dict(id=9,url='a',keep=False)],
            [dict(id=900,url='a',keep=True), dict(id=-2,url='b',keep=False),
             dict(id=7,url='a',keep=False), dict(id=8,url='b',keep=True),
             dict(id=4,url='c',keep=False), dict(id=3,url='b',keep=False)]]
    return [dict(records=[],bins=[0,1]), dict(bins=[-3,0,2], records=[
        dict(user='a',views=-3),dict(user='b',views=0),dict(user='a',views=2),
        dict(user='b',views=0),dict(user='z',views=99)])]
