"""Explicit additive task-pack preparation and per-task runtime dispatch.

Requires the numerical and business workload components. No campaign is launched.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from . import numerical_workload, business_workload

MODULES = {'numerical':numerical_workload, 'business':business_workload}


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
        cls=numerical_workload.RegressionRuntime if module is numerical_workload else business_workload.BusinessRuntime
        self.active=cls(self.output);self.task_id=task.task_id
        self.active.begin(task,lease)
    def _runtime(self,task):
        if self.active is None or task.task_id!=self.task_id:raise ValueError('task runtime not initialized')
        return self.active
    def context(self,task):return self._runtime(task).context(task)
    def tool(self,task,call):return self._runtime(task).tool(task,call)
    def verify(self,task,answer):return self._runtime(task).verify(task,answer)


def prepare(root, specifications):
    """Each specification has kind, rows, seed; sizes are explicit, not inferred."""
    if not isinstance(specifications,list) or not 1<=len(specifications)<=64:
        raise ValueError('provide 1..64 task specifications')
    seen=set()
    for spec in specifications:
        if not isinstance(spec,dict) or set(spec)!={'kind','rows','seed'}:
            raise ValueError('task specification requires exactly kind, rows, seed')
        if spec['kind'] not in MODULES or type(spec['rows']) is not int or not 32<=spec['rows']<=1_000_000 or type(spec['seed']) is not int or not 0<=spec['seed']<2**31:
            raise ValueError('invalid task specification')
        key=(spec['kind'],spec['rows'],spec['seed'])
        if key in seen:raise ValueError('duplicate task specification')
        seen.add(key)
    root=Path(root)
    manifest=root/'task-pack.json'
    envelope={'version':'task-pack-v1','specifications':specifications,
              'components':{k:hashlib.sha256(Path(MODULES[k].__file__).read_bytes()).hexdigest() for k in sorted({s['kind'] for s in specifications})}}
    if manifest.exists() and json.loads(manifest.read_text())!=envelope:
        raise ValueError('task pack changed; use a new directory')
    root.mkdir(parents=True,exist_ok=True)
    tasks=[];modules={}
    for spec in specifications:
        module=MODULES[spec['kind']]
        path=root/f"{spec['kind']}-n{spec['rows']}-s{spec['seed']}"
        if module is numerical_workload:
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
