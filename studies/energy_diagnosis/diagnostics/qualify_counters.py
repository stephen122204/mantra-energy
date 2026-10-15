"""Bounded on-node consistency check; not external electrical calibration."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import select
import time


def gpu_dtype(capability, requested="auto"):
    """Keep the historical BF16 load on Ampere+, use FP16 on Volta/Turing."""
    if requested == "auto":
        return "bfloat16" if capability[0] >= 8 else "float16"
    if requested == "bfloat16" and capability[0] < 8:
        raise ValueError("BF16 qualification requires compute capability 8.0 or newer")
    if requested not in {"float16", "bfloat16", "float32"}:
        raise ValueError("unsupported GPU load dtype")
    return requested


def worker(kind, requested_dtype="auto"):
    metadata = {}
    if kind == 'gpu':
        import torch
        torch.set_num_threads(1)
        capability = torch.cuda.get_device_capability()
        dtype = gpu_dtype(capability, requested_dtype)
        metadata = dict(dtype=dtype, capability=capability, torch_version=torch.__version__,
                        cuda_version=torch.version.cuda, visible_device=os.environ.get('CUDA_VISIBLE_DEVICES'))
        a = torch.ones((2048, 2048), device='cuda', dtype=getattr(torch, dtype))
        b = torch.ones_like(a)
        out = torch.empty_like(a)
        torch.mm(a, b, out=out)
        torch.cuda.synchronize()
    else:
        payload = bytes(8 * 1024 * 1024)
    print('ready', flush=True)
    seconds = float(sys.stdin.readline())
    if not math.isfinite(seconds) or not 0 < seconds <= 30:
        raise ValueError('worker duration must be in (0, 30] seconds')
    end = time.monotonic() + seconds
    count = 0
    while time.monotonic() < end:
        if kind == 'gpu':
            torch.mm(a, b, out=out)
            torch.cuda.synchronize()
        else:
            hashlib.sha256(payload).digest()
        count += 1
    if kind == 'gpu':
        metadata['correct'] = bool(torch.all(out == 2048).item())
        if not metadata['correct']:
            raise RuntimeError('GPU matrix product failed independent expected-value check')
    print(json.dumps({'kind': kind, 'iterations': count, **metadata}), flush=True)


def main(args):
    from studies.energy_diagnosis.runtime.node_measurement import NodeCounterReader, NodeMeasurement, environment_identity
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    revision = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    (root/'configuration.json').write_text(json.dumps(dict(vars(args), source_revision=revision), indent=2)+'\n')
    results=[]
    for repeat in range(2):
        for kind in ('idle', 'cpu', 'gpu', 'combined'):
            workers=[]
            reader=None
            measured=None
            finished=False
            try:
                reader = NodeCounterReader(args.gpu_index)
                identity = reader.device_identity()
                if 'uuid' not in identity:
                    raise RuntimeError('selected GPU identity unavailable')
                env = environment_identity(revision, args.allocation, args.isolation_note, (identity['uuid'],))
                worker_env = dict(os.environ, CUDA_VISIBLE_DEVICES=identity['uuid'])
                kinds = (['cpu'] * 8 if kind in ('cpu','combined') else []) + (['gpu'] if kind in ('gpu','combined') else [])
                for device in kinds:
                    python = args.backend_python if device == 'gpu' else sys.executable
                    p = subprocess.Popen([python, str(Path(__file__).resolve()), '--worker', device, '--gpu-dtype', args.gpu_dtype], env=worker_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                    workers.append(p)
                for p in workers:
                    if not select.select([p.stdout], [], [], 45)[0] or p.stdout.readline().strip() != 'ready':
                        raise RuntimeError('qualification worker failed initialization')
                measured = NodeMeasurement(reader, env)
                measured.start_goal()
                for p in workers:
                    p.stdin.write(str(args.seconds)+'\n'); p.stdin.flush()
                if not workers: time.sleep(args.seconds)
                outcomes=[]
                for p in workers:
                    p.wait(timeout=args.seconds+12)
                    if p.returncode: raise RuntimeError('qualification worker failed')
                    outcomes.append(p.stdout.read().strip())
                artifact = measured.finish_goal().to_dict()
                finished=True
                (root/f'{repeat}-{kind}.json').write_text(json.dumps(artifact,indent=2)+'\n')
                row={'repeat':repeat, 'kind':kind, 'workers':outcomes, 'measurements':artifact['measurements'], 'seconds':(artifact['goal_end_ns']-artifact['goal_start_ns'])/1e9}
                results.append(row)
                print(json.dumps(row),flush=True)
            except BaseException as error:
                # Failed attempts keep their identity and error even before counters start.
                (root/f'{repeat}-{kind}-failure.json').write_text(json.dumps(dict(
                    repeat=repeat, kind=kind, error=f'{type(error).__name__}: {error}',
                    source_revision=revision, measurement_complete=finished), indent=2)+'\n')
                raise
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
    p.add_argument('--gpu-index',type=int,default=0)
    p.add_argument('--gpu-dtype',choices=['auto','float16','bfloat16','float32'],default='auto')
    p.add_argument('--seconds',type=float,default=8)
    p.add_argument('--allocation')
    p.add_argument('--output')
    p.add_argument('--isolation-note')
    a=p.parse_args()
    if a.worker: worker(a.worker, a.gpu_dtype)
    else:
        if not all([a.backend_python,a.allocation,a.output,a.isolation_note]):
            p.error('--backend-python, --allocation, --output and --isolation-note are required')
        if a.gpu_index < 0 or not math.isfinite(a.seconds) or not 0 < a.seconds <= 30:
            p.error('GPU index must be nonnegative and seconds within (0, 30]')
        main(a)
