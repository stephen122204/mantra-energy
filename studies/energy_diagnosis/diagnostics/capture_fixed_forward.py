"""Bounded fidelity capture. No energy or full-task acceptance claim."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
import uuid


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_case(case, vocab, max_context):
    for field in ('prompt_ids', 'continuation_ids'):
        ids = case[field]
        if not isinstance(ids, list) or not ids or any(type(x) is not int or not 0 <= x < vocab for x in ids):
            raise ValueError(f'invalid {field}')
    if len(case['continuation_ids']) > 32:
        raise ValueError('diagnostic continuation exceeds 32 tokens')
    if len(case['prompt_ids']) + len(case['continuation_ids']) > min(max_context, 4096):
        raise ValueError('diagnostic context exceeded')


def fixed_forward(model, case, device, after_prefill=None, synchronize=lambda: None):
    """Same forced prefixes across modes; retains one score vector per position."""
    import torch
    validate_case(case, model.config.vocab_size, model.config.max_position_embeddings)
    cache = None
    scores, lengths = [], []
    total = 0
    with torch.no_grad():
        for index, ids in enumerate([case['prompt_ids']] + [[x] for x in case['continuation_ids']]):
            tensor = torch.tensor([ids], dtype=torch.long, device=device)
            positions = torch.arange(total, total + len(ids), device=device)[None, :]
            total += len(ids)
            result = model(input_ids=tensor,
                           attention_mask=torch.ones((1,total),dtype=torch.long,device=device),
                           position_ids=positions, past_key_values=cache, use_cache=True)
            synchronize()
            cache = result.past_key_values
            if cache is None or int(cache.get_seq_length()) != total:
                raise RuntimeError('unexpected incremental cache length')
            score = result.logits[:, -1, :].detach().cpu()
            if not torch.isfinite(score).all():
                raise RuntimeError('nonfinite logits')
            scores.append(score)
            lengths.append(total)
            del result
            if index == 0 and after_prefill is not None:
                after_prefill()
    return dict(logits=torch.stack(scores, dim=1), cache_lengths=lengths,
                prompt_ids=case['prompt_ids'], continuation_ids=case['continuation_ids'])


def preparation_effect(records, ack, selected):
    allowed = {int(e['node']) for e in selected}
    completed = [r for r in records if r.get('kind') != 'placement' and
                 r.get('generation') == 9001 and r.get('outcome') == 'completed' and
                 r.get('transferred_bytes',0) > 0 and r.get('node') in allowed]
    return bool(ack.get('accepted_bytes',0) > 0 and completed)


def sequence_forward(model, case, device, boundary, reset_request=lambda: None,
                     synchronize=lambda: None):
    """Optional earlier request populates expert state, never target KV state."""
    primer = None
    if 'primer' in case:
        primer = fixed_forward(model,case['primer'],device,synchronize=synchronize)
        boundary()
        reset_request()
        result = fixed_forward(model,case,device,synchronize=synchronize)
    else:
        result = fixed_forward(model,case,device,boundary,synchronize)
    return result, primer


def capture(args):
    import torch
    from transformers import AutoModelForCausalLM
    config = json.loads(Path(args.config).read_text())
    case = json.loads(Path(args.case).read_text())
    if config.get('request_prefix_cache', 'disabled') != 'disabled':
        raise ValueError('qualify request-prefix reuse separately')
    if config.get('model_revision') != case['model_revision']:
        raise ValueError('case/checkpoint revision mismatch')
    model_path = Path(config['model_path']).resolve(strict=True)
    manifest = json.loads((model_path/'alems-weights.json').read_text())
    if manifest['revision'] != config['model_revision']:
        raise ValueError('checkpoint manifest mismatch')
    for name, expected in case['tokenizer_files'].items():
        path = model_path/name
        if path.resolve().parent != model_path or digest(path) != expected:
            raise ValueError(f'case tokenizer hash mismatch: {name}')
    for name, expected in manifest['files'].items():
        path = model_path/name
        if path.resolve().parent != model_path or digest(path) != expected:
            raise ValueError(f'checkpoint hash mismatch: {name}')
    if torch.cuda.device_count() != 1:
        raise ValueError('expose exactly one allocated GPU')
    torch.manual_seed(args.seed)
    torch.set_num_threads(8)
    native = None
    intervention = dict(mode=args.mode, selected=[], ack={}, transfers=[], effective=False,
                        requested_budget_bytes=args.budget_bytes,
                        boundary='after_primer_before_target_prefill' if 'primer' in case else 'after_target_prefill_before_decode')
    if args.mode == 'reference':
        from accelerate import cpu_offload
        model = AutoModelForCausalLM.from_pretrained(model_path, dtype=torch.bfloat16,
                    device_map='cpu',local_files_only=True,trust_remote_code=False,
                    attn_implementation=args.attention)
        model.eval()
        cpu_offload(model,execution_device=torch.device('cuda:0'),offload_buffers=True)
    else:
        from studies.energy_diagnosis.moe.native_backend import NativeDevice
        native = NativeDevice(config)
        model = native.model.model
        model.eval()
        if model.config._attn_implementation != args.attention:
            raise ValueError('native attention differs from requested comparison setting')
        native.request_work.reset()
        intervention['initial_snapshot'] = native.snapshot({})

    def at_boundary():
        if native is None:
            return
        intervention['history_demands'] = native.demands_rpc({})
        intervention['history_transfers'] = native.transfers({})
        intervention['boundary_snapshot'] = native.snapshot({})
        if args.mode != 'native-preparation':
            return
        from studies.energy_diagnosis.moe.control import Expert, Policy
        history = Counter({})
        for row in intervention['history_demands']:
            history[(row['layer'],row['expert'])] += row['tokens']
        snapshot = [Expert(**r) for r in intervention['boundary_snapshot']]
        selected, reason = Policy('fixed',args.budget_bytes).select(snapshot,history)
        intervention['selected'] = [asdict(e) for e in selected]
        intervention['reason'] = reason
        intervention['ack'] = native.prepare(dict(experts=intervention['selected'],
                                  generation=9001,budget=args.budget_bytes))
        native.drain(dict(timeout=30))
        packet = native.transfers({})
        intervention['transfers'] = packet['records']
        intervention['dropped'] = packet['dropped']
        intervention['effective'] = preparation_effect(packet['records'],intervention['ack'],intervention['selected'])
        # Preserve scores even if no preparation was effective; never mark that
        # case an intervention-invariance pass in the result's qualification flag.

    result, primer = sequence_forward(model,case,'cuda:0',at_boundary,
                        (lambda: native.request_work.reset()) if native else (lambda: None),
                        torch.cuda.synchronize)
    if native is not None:
        native.drain(dict(timeout=30))
        intervention['remaining_demands'] = native.demands_rpc({})
        intervention['final_transfers'] = native.transfers({})
        intervention['final_snapshot'] = native.snapshot({})
    out = Path(args.output)
    torch.save(result,out/'scores.pt')
    if primer is not None:
        torch.save(primer,out/'primer-scores.pt')
    metadata = dict(mode=args.mode,case_sha256=digest(args.case),config_sha256=digest(args.config),
                    script_sha256=digest(__file__),scores_sha256=digest(out/'scores.pt'),
                    primer_scores_sha256=None if primer is None else digest(out/'primer-scores.pt'),
                    checkpoint_manifest_sha256=digest(model_path/'alems-weights.json'),
                    model_revision=config['model_revision'],seed=args.seed,
                    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                    source_dirty=bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
                    torch_version=torch.__version__,cuda=torch.version.cuda,
                    transformers_version=importlib.metadata.version('transformers'),
                    accelerate_version=importlib.metadata.version('accelerate'),
                    attention=model.config._attn_implementation,model_training=model.training,
                    gpu=torch.cuda.get_device_name(0),intervention=intervention,
                    scope='Fixed forced prefixes; optional earlier request primes expert state with a fresh target KV cache. Preparation is drained at the declared boundary; no actual tool-overlap, full-task, energy or asynchronous-race claim.',
                    native_boot=None if native is None else native.boot)
    (out/'capture.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True)
    p.add_argument('--case',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--mode',choices=['reference','native-demand','native-preparation'],required=True)
    p.add_argument('--attention',choices=['eager','sdpa'],default='eager')
    p.add_argument('--seed',type=int,default=20260913)
    p.add_argument('--budget-bytes',type=int,default=536870912)
    p.add_argument('--timeout',type=int,default=900)
    p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=p.parse_args()
    if not 1 <= args.budget_bytes <= 536870912 or not 1 <= args.timeout <= 1800:
        p.error('budget must be 1..512 MiB; timeout 1..1800 seconds')
    if args.worker:
        try:
            code=capture(args)
        except BaseException:
            traceback.print_exc()
            code=1
        sys.stdout.flush();sys.stderr.flush()
        # Native owns C++ threads. Parent observes terminal process state; no
        # claim that Python destructor cleanup itself was successfully exercised.
        os._exit(code)
    if os.name != 'posix':
        p.error('the bounded hardware supervisor requires POSIX')
    out=Path(args.output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    cmd=[sys.executable,'-m','studies.energy_diagnosis.diagnostics.capture_fixed_forward',*sys.argv[1:],'--worker']
    start=time.monotonic_ns()
    from studies.energy_diagnosis.diagnostics.run_bounded import stop_group
    def interrupted(signum, frame):
        raise InterruptedError(f'capture supervisor received signal {signum}')
    previous = {sig:signal.signal(sig, interrupted) for sig in (signal.SIGTERM,signal.SIGINT)}
    interrupted_run = False
    with (out/'worker.log').open('w') as log:
        process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        timed_out=False
        try:
            code=process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            code = 124
        except InterruptedError:
            interrupted_run = True
            code = 130
        finally:
            stop_group(process)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    capture_path=out/'capture.json'
    metadata=json.loads(capture_path.read_text()) if capture_path.exists() else None
    effective=metadata is not None and (args.mode!='native-preparation' or metadata['intervention']['effective'])
    drops=0 if metadata is None else sum(metadata['intervention'].get(k,{}).get('dropped',0) for k in ['history_transfers','final_transfers'])+metadata['intervention'].get('dropped',0)
    valid=code==0 and not timed_out and not interrupted_run and effective and drops==0
    (out/'supervisor.json').write_text(json.dumps(dict(run_id=str(uuid.uuid4()),worker_pid=process.pid,
          capture_sha256=digest(capture_path) if capture_path.exists() else None,
          returncode=code,timed_out=timed_out,interrupted=interrupted_run,
          elapsed_ns=time.monotonic_ns()-start,owned_worker_exited=process.poll() is not None,
          capture_qualified=valid,qualification_scope='capture and nonvacuous intervention only; compare scores separately',
          dropped_events=drops),indent=2)+'\n')
    return 0 if valid else 2


if __name__=='__main__':
    sys.exit(main())
