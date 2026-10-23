"""Generated grouped-regression tasks with bounded tools and an exact reference.

These are synthetic workload variants, not independent benchmark lineages.
No model or hardware jobs are launched by asset preparation.
"""
from dataclasses import dataclass
import csv
from fractions import Fraction
import json
import math
from pathlib import Path
import tempfile

from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash, copy_workspace

from .tool_contracts import REGRESSION_ACTIONS, action_contract

VERSION = 'grouped-regression-v1'


def create_task(root, *, rows=8192, seed=7):
    if type(rows) is not int or not 32 <= rows <= 1_000_000:
        raise ValueError('rows must be an integer in 32..1000000')
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('seed must be a nonnegative int32')
    root = Path(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as staging:
        stage = Path(staging) / 'assets'
        stage.mkdir()
        with (stage / 'observations.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream, lineterminator='\n')
            writer.writerow(['group', 'x', 'y', 'valid'])
            for i in range(rows):
                g = i % 4
                x = (i // 4 + seed) % 997 - 498
                noise = ((i * 17 + seed * 11) % 23) - 11
                writer.writerow([f'g{g}', x, (g + 1) * x + seed % 13 + noise, int(i % 19 != 0)])
        (stage / 'source.json').write_text(json.dumps(dict(
            version=VERSION, source='deterministic synthetic observations', rows=rows,
            seed=seed, lineage='synthetic-grouped-regression-v1'), sort_keys=True) + '\n')
        expected_hash = _hash(stage)
        if root.exists():
            if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')) or _hash(root) != expected_hash:
                raise ValueError('existing numerical assets differ; use a new directory')
        else:
            stage.rename(root)
    return PilotTask(f'grouped-fit-v1-n{rows}-s{seed}', 'grouped-regression',
        'synthetic-grouped-regression-v1', root, {}, expected_hash, (),
        'For each group in observations.csv, exclude records whose valid flag is 0. '
        'Fit ordinary least squares y=slope*x+intercept with an intercept. '
        'Return {by_group:{group:{count:integer,slope:number,intercept:number,rmse:number}}}. '
        'RMSE is sqrt(sum of squared residuals/count), not sample standard deviation. '
        'Use the regression tool to inspect or compute on the local dataset. '
        'Return finite numbers accurate to absolute tolerance 0.000001. Do not include excluded rows.')


def load_task(root, *, task_id, lineage, asset_sha256):
    """Load a checksum-pinned, prepared integer regression dataset.

    Source conversion belongs to the caller. This checks the normalized contract,
    not the scientific validity or attribution of that conversion.
    """
    import re
    for value in (task_id, lineage):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
            raise ValueError('invalid prepared task identity')
    if not isinstance(asset_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', asset_sha256):
        raise ValueError('invalid prepared asset checksum')
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('prepared assets must be a regular directory')
    if {p.name for p in root.iterdir()} != {'observations.csv', 'source.json'}:
        raise ValueError('prepared assets require exactly observations.csv and source.json')
    if any(p.is_symlink() or not p.is_file() for p in root.iterdir()):
        raise ValueError('prepared assets must be regular files')
    if (root / 'observations.csv').stat().st_size > 128 * 1024 * 1024 or (root / 'source.json').stat().st_size > 65536:
        raise ValueError('prepared assets exceed size limit')
    if _hash(root) != asset_sha256:
        raise ValueError('prepared asset checksum mismatch')
    source = json.loads((root / 'source.json').read_text(encoding='utf-8'))
    if not isinstance(source, dict) or not isinstance(source.get('source'), str) or not source['source'].strip():
        raise ValueError('source.json requires a source description')
    groups = {}
    with (root / 'observations.csv').open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['group', 'x', 'y', 'valid']:
            raise ValueError('invalid prepared CSV columns')
        rows = 0
        for row in reader:
            rows += 1
            if rows > 1_000_000 or None in row or any(v is None for v in row.values()):
                raise ValueError('invalid prepared CSV row')
            group = row['group']
            if not group or len(group) > 128 or any(ord(c) < 32 for c in group) or row['valid'] not in {'0', '1'}:
                raise ValueError('invalid group or valid flag')
            for name in ('x', 'y'):
                if not re.fullmatch(r'-?[0-9]{1,10}', row[name]) or abs(int(row[name])) > 1_000_000_000:
                    raise ValueError('prepared coordinates must be bounded integers')
            if row['valid'] == '1':
                x = int(row['x'])
                n, sx, sxx = groups.get(group, (0, 0, 0))
                groups[group] = n + 1, sx + x, sxx + x*x
                if len(groups) > 64:
                    raise ValueError('too many regression groups')
    if not groups or any(n < 2 or n*sxx == sx*sx for n,sx,sxx in groups.values()):
        raise ValueError('each included group requires a defined regression')
    return PilotTask(task_id, 'grouped-regression', lineage, root, {}, asset_sha256, (),
        'For each group in observations.csv, exclude valid=0 records. Fit ordinary least '
        'squares y=slope*x+intercept with an intercept. Return '
        '{by_group:{group:{count:integer,slope:number,intercept:number,rmse:number}}}. '
        'RMSE is sqrt(sum of squared residuals/count). Use the regression tool; inspect '
        'source metadata for units. Return finite values within absolute tolerance 0.000001. '
        'Report the stored x/y units without rescaling.')


def _groups(root):
    groups = {}
    with (Path(root) / 'observations.csv').open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            if int(row['valid']) == 1:
                groups.setdefault(row['group'], []).append((int(row['x']), int(row['y'])))
    return groups


@dataclass
class RegressionTool:
    root: str

    def execute(self, action, workers=1):
        if workers != 1 or action not in {'inspect', 'fit'}:
            raise ValueError('one worker and action inspect|fit required')
        if action == 'inspect':
            return dict(columns=['group','x','y','valid'], excluded_flag=0,
                        source=json.loads((Path(self.root) / 'source.json').read_text()))
        output = {}
        for group, points in _groups(self.root).items():
            n = len(points)
            mx = math.fsum(x for x, _ in points) / n
            my = math.fsum(y for _, y in points) / n
            xx = math.fsum((x-mx)**2 for x, _ in points)
            if xx == 0:
                raise ValueError('undefined regression: constant x')
            slope = math.fsum((x-mx)*(y-my) for x,y in points) / xx
            intercept = my - slope * mx
            rmse = math.sqrt(math.fsum((y-slope*x-intercept)**2 for x,y in points)/n)
            output[group] = dict(count=n,slope=slope,intercept=intercept,rmse=rmse)
        return dict(by_group=output)


def verify(task, answer):
    if _hash(task.asset_path) != task.asset_sha256:
        raise ValueError('task inputs changed before verification')
    if not isinstance(answer, dict) or set(answer) != {'by_group'} or not isinstance(answer['by_group'],dict):
        return dict(passed=False, reason='invalid answer shape')
    # Independent raw CSV reader and exact integer sufficient-statistic formula.
    accum = {}
    with (task.asset_path / 'observations.csv').open(newline='',encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            if row['valid'] != '1':
                continue
            n,sx,sy,sxx,sxy,syy = accum.get(row['group'], (0,0,0,0,0,0))
            x,y = int(row['x']),int(row['y'])
            accum[row['group']] = n+1,sx+x,sy+y,sxx+x*x,sxy+x*y,syy+y*y
    if set(answer['by_group']) != set(accum):
        return dict(passed=False, reason='group set mismatch')
    for group,(n,sx,sy,sxx,sxy,syy) in accum.items():
        actual = answer['by_group'][group]
        if not isinstance(actual,dict) or set(actual) != {'count','slope','intercept','rmse'}:
            return dict(passed=False,reason='invalid group shape')
        if type(actual['count']) is not int or actual['count'] != n:
            return dict(passed=False,reason='incorrect count')
        b = Fraction(n*sxy-sx*sy,n*sxx-sx*sx)
        a = Fraction(sy-b*sx,n)
        residual = syy-2*b*sxy-2*a*sy+b*b*sxx+2*a*b*sx+n*a*a
        expected = dict(slope=float(b),intercept=float(a),rmse=math.sqrt(float(residual/n)))
        for key,target in expected.items():
            value = actual[key]
            if type(value) not in (int,float) or not math.isfinite(value) or abs(value-target)>1e-6:
                return dict(passed=False,reason='numerical mismatch or invalid type')
    return dict(passed=True,reason='independent exact reference')


class RegressionRuntime:
    """GoalExecutor-compatible adapter; runner selection is integrated separately."""
    def __init__(self, root):
        self.root = Path(root)

    def begin(self, task, lease):
        if _hash(task.asset_path) != task.asset_sha256:
            raise ValueError('task assets changed')
        self.workspace = self.root / 'workspaces' / lease.execution_id
        if self.workspace.exists():
            raise ValueError('workspace already exists')
        copy_workspace(task.asset_path, self.workspace)

    def context(self, task):
        return dict(family=task.family, tools={'regression': {
            'description': 'Inspect input metadata or compute per-group OLS fits locally. '
                           'Fit filters valid=1 and returns count, slope, intercept and RMSE. '
                           'Output size is bounded independently of input size.',
            'args': {'action': 'required: inspect or fit'},
            'parameters': action_contract(REGRESSION_ACTIONS),
            'example_call': {'id':'fit_1','tool':'regression','args':{'action':'fit'}}}},
            instruction='Return only JSON: {"tool_calls":[{"id":"unique","tool":"regression",'
                        '"args":{"action":"fit"}}]} or {"answer":{...}}. '
                        'Use actual tool outputs. No other arguments are permitted.')

    def tool(self, task, call):
        args = call.get('args')
        if call.get('tool') != 'regression' or not isinstance(args,dict) or set(args) != {'action'} or args['action'] not in {'inspect','fit'}:
            raise ValueError('tool request outside declared schema')
        return RegressionTool(str(self.workspace))

    def verify(self, task, answer):
        return verify(task, answer)
