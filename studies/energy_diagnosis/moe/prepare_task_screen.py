"""Materialize the available task inventory locally; never launch a model or campaign."""
import argparse
import json
import re
from pathlib import Path
from . import program_workload, repo_workload
from .task_pack import prepare


def specifications(source, python, rows=8192, seed=7, repo_cases=None):
    cases=list(repo_workload.CASES) if repo_cases is None else list(repo_cases)
    if not cases or len(set(cases))!=len(cases) or any(c not in repo_workload.CASES for c in cases):
        raise ValueError('provide distinct supported repository cases')
    return ([dict(kind=k,rows=rows,seed=seed) for k in ('business','etl','numerical')]
        + [dict(kind='program',case=c,rows=rows,seed=seed) for c in program_workload.CASES]
        + [dict(kind='repo',case=c,source=str(Path(source).resolve()),python=str(Path(python).absolute())) for c in cases])


def write_immutable(path, value):
    text=json.dumps(value,sort_keys=True,indent=2)+'\n'
    if path.exists():
        if path.read_text()!=text:raise ValueError(f'{path.name} changed; use a new output directory')
    else:
        temporary=path.with_suffix(path.suffix+'.tmp')
        temporary.write_text(text);temporary.replace(path)


def inventory(pack):
    catalog = pack.catalog()
    for row in catalog:
        # Size and generator seed are variants, not additional problem types.
        row['task_type'] = re.split(r'-n\d+-s\d+', row['task_id'], maxsplit=1)[0]
        row['qualification'] = 'pending: software, sandbox, budget and live-model evidence required'
    families = sorted({t['family'] for t in catalog})
    return dict(version='task-screen-inventory-v2', tasks=catalog,
        task_cases=len(catalog), task_types=len({t['task_type'] for t in catalog}),
        counts={f:sum(t['family']==f for t in catalog) for f in families},
        readiness='assets prepared only; this inventory does not authorize a campaign',
        limitations=['Repository cases share one library and injected-defect format.',
                     'Business questions share one generated schema.',
                     'Python tasks adapt DS-1000 semantics, not its official environment or score.',
                     'Implementation tasks are benchmark adaptations, not official benchmark scores.',
                     'Numerical tool computes the regression; this is an orchestration task.',
                     'Input size alone does not prove long duration; record measured reference and model times.',
                     'Additional seeds and input sizes are variants, not independent task types.'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--networkx-source',type=Path,required=True)
    parser.add_argument('--tool-python',type=Path,required=True)
    parser.add_argument('--rows',type=int,default=8192)
    parser.add_argument('--seed',type=int,default=7)
    parser.add_argument('--repo-case',action='append',choices=tuple(repo_workload.CASES))
    parser.add_argument('--additional-specs',type=Path,
                        help='JSON list of explicit additional task specifications, including implementation bundle tasks or larger inputs')
    args=parser.parse_args(argv)
    specs=specifications(args.networkx_source,args.tool_python,args.rows,args.seed,args.repo_case)
    if args.additional_specs:
        extra=json.loads(args.additional_specs.read_text())
        if not isinstance(extra,list):raise ValueError('additional specifications must be a JSON list')
        specs.extend(extra)
    pack=prepare(args.output/'assets',specs)
    write_immutable(args.output/'specifications.json',specs)
    write_immutable(args.output/'inventory.json',inventory(pack))
    print(json.dumps(dict(tasks=len(pack.tasks),specifications=str(args.output/'specifications.json'),inventory=str(args.output/'inventory.json'))))


if __name__=='__main__':main()
