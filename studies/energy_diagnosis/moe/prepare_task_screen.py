"""Materialize the available task inventory locally; never launch a model or campaign."""
import argparse
import json
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


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--networkx-source',type=Path,required=True)
    parser.add_argument('--tool-python',type=Path,required=True)
    parser.add_argument('--rows',type=int,default=8192)
    parser.add_argument('--seed',type=int,default=7)
    parser.add_argument('--repo-case',action='append',choices=tuple(repo_workload.CASES))
    args=parser.parse_args(argv)
    specs=specifications(args.networkx_source,args.tool_python,args.rows,args.seed,args.repo_case)
    pack=prepare(args.output/'assets',specs)
    catalog=pack.catalog()
    write_immutable(args.output/'specifications.json',specs)
    write_immutable(args.output/'inventory.json',dict(version='task-screen-inventory-v1',tasks=catalog,
        counts={family:sum(t['family']==family for t in catalog) for family in sorted({t['family'] for t in catalog})},
        readiness='assets prepared; run software qualification and then separate live-model qualification',
        limitations=['Repository cases share one library and injected-defect format.',
                     'Business questions share one generated schema.',
                     'Python tasks adapt DS-1000 semantics, not its official execution environment or score.',
                     'Numerical tool computes the regression; this is an orchestration task.',
                     'Additional seeds and input sizes are variants, not independent task types.']))
    print(json.dumps(dict(tasks=len(catalog),specifications=str(args.output/'specifications.json'),inventory=str(args.output/'inventory.json'))))


if __name__=='__main__':main()
