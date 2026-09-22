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

from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash

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
        import shutil
        if _hash(task.asset_path) != task.asset_sha256:
            raise ValueError('task assets changed')
        self.workspace = self.root / 'workspaces' / lease.execution_id
        if self.workspace.exists():
            raise ValueError('workspace already exists')
        shutil.copytree(task.asset_path, self.workspace)

    def context(self, task):
        return dict(family=task.family, tools={'regression': {
            'description': 'Inspect input metadata or compute per-group OLS fits locally. '
                           'Fit filters valid=1 and returns count, slope, intercept and RMSE. '
                           'Output size is bounded independently of input size.',
            'args': {'action': 'inspect|fit'}}},
            instruction='Return only JSON: {"tool_calls":[{"id":"unique","tool":"regression",'
                        '"args":{"action":"inspect or fit"}}]} or {"answer":{...}}. '
                        'Use actual tool outputs. No other arguments are permitted.')

    def tool(self, task, call):
        args = call.get('args')
        if call.get('tool') != 'regression' or not isinstance(args,dict) or set(args) != {'action'} or args['action'] not in {'inspect','fit'}:
            raise ValueError('tool request outside declared schema')
        return RegressionTool(str(self.workspace))

    def verify(self, task, answer):
        return verify(task, answer)
