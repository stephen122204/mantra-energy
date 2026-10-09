"""Bounded on-node consistency check; not external electrical calibration."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import select
import time


def worker(kind):
    if kind == 'gpu':
        import torch
        torch.set_num_threads(1)
        a = torch.ones((2048, 2048), device='cuda', dtype=torch.bfloat16)
        b = torch.ones_like(a)
        out = torch.empty_like(a)
        torch.mm(a, b, out=out)
        torch.cuda.synchronize()
    else:
        payload = bytes(8 * 1024 * 1024)
    print('ready', flush=True)
    seconds = float(sys.stdin.readline())
    end = time.monotonic() + seconds
    count = 0
    while time.monotonic() < end:
        if kind == 'gpu':
            torch.mm(a, b, out=out)
            torch.cuda.synchronize()
        else:
            hashlib.sha256(payload).digest()
        count += 1
    print(json.dumps({'kind': kind, 'iterations': count}), flush=True)


def main(args):
    from studies.energy_diagnosis.runtime.node_measurement import NodeCounterReader, NodeMeasurement, environment_identity
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    revision = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    env = environment_identity(revision, args.allocation, args.isolation_note)
    results=[]
    for repeat in range(2):
        for kind in ('idle', 'cpu', 'gpu', 'combined'):
            workers=[]
            reader=None
            measured=None
            finished=False
            try:
                kinds = (['cpu'] * 8 if kind in ('cpu','combined') else []) + (['gpu'] if kind in ('gpu','combined') else [])
                for device in kinds:
                    python = args.backend_python if device == 'gpu' else sys.executable
                    p = subprocess.Popen([python, str(Path(__file__).resolve()), '--worker', device], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                    workers.append(p)
                for p in workers:
                    if not select.select([p.stdout], [], [], 45)[0] or p.stdout.readline().strip() != 'ready':
                        raise RuntimeError('qualification worker failed initialization')
                reader = NodeCounterReader(0)
                measured = NodeMeasurement(reader, env)
                measured.start_goal()
                for p in workers:
                    p.stdin.write('8\n'); p.stdin.flush()
                if not workers: time.sleep(8)
                outcomes=[]
                for p in workers:
                    p.wait(timeout=20)
                    if p.returncode: raise RuntimeError('qualification worker failed')
                    outcomes.append(p.stdout.read().strip())
                artifact = measured.finish_goal().to_dict()
                finished=True
                (root/f'{repeat}-{kind}.json').write_text(json.dumps(artifact,indent=2)+'\n')
                row={'repeat':repeat, 'kind':kind, 'workers':outcomes, 'measurements':artifact['measurements'], 'seconds':(artifact['goal_end_ns']-artifact['goal_start_ns'])/1e9}
                results.append(row)
                print(json.dumps(row),flush=True)
            finally:
                for p in workers:
                    if p.poll() is None: p.kill(); p.wait()
                if measured and measured.thread and not finished:
                    measured.stop.set()
                    measured.thread.join(timeout=5)
                if reader: reader.close()
    (root/'summary.json').write_text(json.dumps(results,indent=2)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--worker',choices=['cpu','gpu'])
    p.add_argument('--backend-python')
    p.add_argument('--allocation')
    p.add_argument('--output')
    p.add_argument('--isolation-note')
    a=p.parse_args()
    if a.worker: worker(a.worker)
    else:
        if not all([a.backend_python,a.allocation,a.output,a.isolation_note]):
            p.error('--backend-python, --allocation, --output and --isolation-note are required')
        main(a)
