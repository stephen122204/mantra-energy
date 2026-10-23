"""Explicit additive task-pack preparation and per-task runtime dispatch.

Requires the numerical and business workload components. No campaign is launched.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from . import numerical_workload, business_workload, etl_workload, repo_workload, program_workload, impl_workload, bird_workload
from . import sandbox, repo_oracle, repo_test_process, private_challenges

MODULES = {'numerical':numerical_workload, 'business':business_workload, 'etl':etl_workload, 'repo':repo_workload, 'program':program_workload, 'impl':impl_workload, 'bird':bird_workload}


def support_components(kinds):
    modules = set()
    if 'repo' in kinds:
        modules.update((sandbox, repo_oracle, repo_test_process))
    if 'impl' in kinds:
        modules.add(sandbox)
    if {'etl','program'} & set(kinds):
        modules.add(private_challenges)
    return {m.__name__.rsplit('.', 1)[-1]: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in sorted(modules, key=lambda m: m.__name__)}


@dataclass
class TaskPack:
    tasks: tuple
    modules: dict
    root: Path

    def catalog(self):
        return [dict(task_id=t.task_id, family=t.family,lineage=t.lineage,
                     asset_sha256=t.asset_sha256, workload_version=self.modules[t.task_id].VERSION,
                     verifier_sha256=hashlib.sha256(Path(self.modules[t.task_id].__file__).read_bytes()).hexdigest())
                for t in self.tasks]

    def runtime(self, output):
        return PackRuntime(self.modules,output)


class PackRuntime:
    def __init__(self, modules, output):
        self.modules=modules;self.output=output;self.active=None;self.task_id=None
    def begin(self,task,lease):
        module=self.modules[task.task_id]
        cls={numerical_workload:numerical_workload.RegressionRuntime, business_workload:business_workload.BusinessRuntime, etl_workload:etl_workload.ETLRuntime, repo_workload:repo_workload.RepoRuntime, program_workload:program_workload.ProgramRuntime, impl_workload:impl_workload.ImplRuntime, bird_workload:bird_workload.BirdRuntime}[module]
        self.active=cls(self.output);self.task_id=task.task_id
        self.active.begin(task,lease)
    def _runtime(self,task):
        if self.active is None or task.task_id!=self.task_id:raise ValueError('task runtime not initialized')
        return self.active
    def context(self,task):return self._runtime(task).context(task)
    def tool(self,task,call):return self._runtime(task).tool(task,call)
    def verify(self,task,answer):return self._runtime(task).verify(task,answer)
    def verification_callable(self,task):
        # Capture the active implementation, not the module dispatcher, for an
        # isolated verifier process (including injected diagnostic verifiers).
        return self._runtime(task).verify


def prepare(root, specifications, *, prepared_assets=None):
    """Each specification has kind, rows, seed; sizes are explicit, not inferred."""
    if not isinstance(specifications,list) or not 1<=len(specifications)<=64:
        raise ValueError('provide 1..64 task specifications')
    seen=set()
    external={}
    for index,spec in enumerate(specifications):
        if not isinstance(spec,dict):
            raise ValueError('task specification must be an object')
        if set(spec)=={'kind','assets','asset_sha256','task_id','lineage'} and spec['kind']=='numerical':
            if not isinstance(spec['assets'],str) or not Path(spec['assets']).is_absolute():
                raise ValueError('prepared asset path must be absolute')
            external[index]=numerical_workload.load_task(spec['assets'],task_id=spec['task_id'],
                lineage=spec['lineage'],asset_sha256=spec['asset_sha256'])
            key=('prepared',spec['task_id'])
        elif spec.get('kind')=='program':
            if set(spec)!={'kind','case','rows','seed'} or spec['case'] not in program_workload.CASES or type(spec['rows']) is not int or not 32<=spec['rows']<=program_workload.MAX_ROWS or type(spec['seed']) is not int or not 0<=spec['seed']<2**31:
                raise ValueError('program specification requires a supported case, rows and seed')
            key=('program',spec['case'],spec['rows'],spec['seed'])
        elif spec.get('kind')=='impl':
            # Python implementation problem from a prepared bundle (impl_prepare.py).
            # Optional prompt version (impl_workload.PROMPTS); v2 is the default.
            if not {'kind','problem','bundle'}<=set(spec)<={'kind','problem','bundle','prompt'} or not isinstance(spec['problem'],str) \
                    or not isinstance(spec['bundle'],str) or not Path(spec['bundle']).is_absolute() \
                    or spec.get('prompt','v2') not in impl_workload.PROMPTS:
                raise ValueError('impl specification requires problem and absolute bundle')
            key=('impl',spec['problem'],spec.get('prompt','v2'))
        elif spec.get('kind')=='bird':
            # BIRD dev questions of one database from the extracted, pinned release folder (bird_workload.py).
            if set(spec)!={'kind','db_id','question_ids','source'} or not isinstance(spec['db_id'],str) \
                    or not isinstance(spec['source'],str) or not Path(spec['source']).is_absolute() \
                    or not isinstance(spec['question_ids'],list) or not spec['question_ids'] \
                    or any(type(q) is not int for q in spec['question_ids']) or spec['question_ids']!=sorted(set(spec['question_ids'])):
                raise ValueError('bird specification requires db_id, increasing question_ids and absolute source')
            key=('bird',spec['db_id'])
        elif spec.get('kind')=='repo':
            # Repository repair: an explicit case over a pinned source checkout and tool Python.
            if set(spec)!={'kind','case','source','python'} or spec['case'] not in repo_workload.CASES \
                    or not all(isinstance(spec[k],str) and Path(spec[k]).is_absolute() for k in ('source','python')):
                raise ValueError('repo specification requires case, absolute source and absolute python')
            key=('repo',spec['case'])
        else:
            if not (set(spec)=={'kind','rows','seed'} or (set(spec)=={'kind','rows','seed','variant'} and spec.get('kind')=='etl')):
                raise ValueError('task specification requires generated or prepared fields')
            if 'variant' in spec:etl_workload.validate_variant(spec['variant'])
            if not isinstance(spec['kind'],str) or spec['kind'] not in MODULES or type(spec['rows']) is not int or not 32<=spec['rows']<=1_000_000 or type(spec['seed']) is not int or not 0<=spec['seed']<2**31:
                raise ValueError('invalid task specification')
            key=(spec['kind'],spec['rows'],spec['seed'],json.dumps(spec.get('variant'),sort_keys=True))
        if key in seen:raise ValueError('duplicate task specification')
        seen.add(key)
    root=Path(root)
    manifest=root/'task-pack.json'
    envelope={'version':'task-pack-v1','specifications':specifications,
              'components':{k:hashlib.sha256(Path(MODULES[k].__file__).read_bytes()).hexdigest() for k in sorted({s['kind'] for s in specifications})},
              'support_components':support_components({s['kind'] for s in specifications})}
    if prepared_assets is not None:
        _snapshot_prepared(root, Path(prepared_assets), envelope)
    if manifest.exists() and json.loads(manifest.read_text())!=envelope:
        raise ValueError('task pack changed; use a new directory')
    root.mkdir(parents=True,exist_ok=True)
    tasks=[];modules={}
    for index,spec in enumerate(specifications):
        module=MODULES[spec['kind']]
        if index in external:
            import shutil
            import tempfile
            path=root/f"prepared-{spec['task_id']}"
            if not path.exists():
                with tempfile.TemporaryDirectory(dir=root) as staging:
                    snapshot=Path(staging)/'assets'
                    shutil.copytree(external[index].asset_path,snapshot)
                    numerical_workload.load_task(snapshot,task_id=spec['task_id'],lineage=spec['lineage'],asset_sha256=spec['asset_sha256'])
                    snapshot.rename(path)
            created=(numerical_workload.load_task(path,task_id=spec['task_id'],lineage=spec['lineage'],asset_sha256=spec['asset_sha256']),)
        elif spec['kind']=='program':
            path=root/f"program-{spec['case']}-n{spec['rows']}-s{spec['seed']}"
            created=(program_workload.create_task(path,case=spec['case'],rows=spec['rows'],seed=spec['seed']),)
        elif spec['kind']=='impl':
            path=root/f"impl-{spec['problem'].lower().replace('/','-')}"
            created=(impl_workload.create_task(path,problem=spec['problem'],bundle=spec['bundle'],prompt=spec.get('prompt','v2')),)
        elif spec['kind']=='bird':
            path=root/f"bird-{spec['db_id']}"
            created=bird_workload.create_tasks(path,db_id=spec['db_id'],question_ids=spec['question_ids'],source=spec['source'])
        elif spec['kind']=='repo':
            path=root/f"repo-{spec['case']}"
            created=(repo_workload.create_task(path,case=spec['case'],source=spec['source'],python=spec['python']),)
        else:
            path=root/f"{spec['kind']}-n{spec['rows']}-s{spec['seed']}"
            if spec.get('variant') is not None:
                path=root/(path.name+etl_workload.variant_suffix(spec['variant']))
                created=(etl_workload.create_task(path,rows=spec['rows'],seed=spec['seed'],variant=spec['variant']),)
            elif module in (numerical_workload,etl_workload):
                created=(module.create_task(path,rows=spec['rows'],seed=spec['seed']),)
            else:created=module.create_tasks(path,rows=spec['rows'],seed=spec['seed'])
        for task in created:
            if task.task_id in modules:raise ValueError('duplicate task identity')
            tasks.append(task);modules[task.task_id]=module
    if not manifest.exists():
        temporary=root/'task-pack.tmp'
        temporary.write_text(json.dumps(envelope,indent=2,sort_keys=True)+'\n')
        temporary.replace(manifest)
    return TaskPack(tuple(tasks),modules,root)


def _snapshot_prepared(root, source, envelope):
    """Reuse frozen private challenges across separately launched model arms."""
    import shutil
    import tempfile
    from studies.energy_diagnosis.workloads.pilot_tasks import _hash
    root, source = root.absolute(), source.absolute()
    if root.resolve() == source.resolve() or root.resolve() in source.resolve().parents or source.resolve() in root.resolve().parents:
        raise ValueError('prepared assets and run assets must be disjoint')
    def fingerprint(path):
        if path.is_symlink() or not path.is_dir() or any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in path.rglob('*')):
            raise ValueError('prepared assets require ordinary files and directories without symlinks')
        if json.loads((path/'task-pack.json').read_text()) != envelope:
            raise ValueError('prepared task pack differs from specifications or verifier code')
        return _hash(path)
    before = fingerprint(source)
    if root.exists():
        if fingerprint(root) != before:
            raise ValueError('run assets differ from frozen prepared assets')
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='prepared-pack-', dir=root.parent) as temp:
        snapshot=Path(temp)/'assets'
        shutil.copytree(source, snapshot)
        if fingerprint(snapshot) != before or fingerprint(source) != before:
            raise ValueError('prepared assets changed while copying')
        # Linux needs write permission on a moved directory when its parent changes.
        # copytree preserves the frozen source's read-only mode. Only the run's
        # pack root needs owner write access for rename and factory staging;
        # frozen source and copied task files retain their original permissions.
        mode = snapshot.stat().st_mode & 0o7777
        snapshot.chmod(mode | 0o200)
        snapshot.rename(root)
