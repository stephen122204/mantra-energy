"""Small native Qwen expert arithmetic check; not full-model qualification.

Run only in the isolated, built CUDA backend environment under the hardware lock.
Synthetic weights exercise single/multiple tokens, reversed submissions and a
nondefault caller stream against independent BF16 and framework-style operations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def probe(output):
    os.environ['ALEMS_QWEN_REFERENCE_MATH']='1'
    import torch
    import torch.nn.functional as F
    from moe_infinity import _store
    from transformers import Qwen3MoeConfig
    from transformers.models.qwen3_moe.modeling_qwen3_moe import Qwen3MoeExperts
    if torch.cuda.device_count()!=1:
        raise ValueError('expose exactly one allocated GPU')
    torch.manual_seed(137);torch.set_num_threads(4)
    experts=8;hidden=128;intermediate=128
    weights=[]
    for expert in range(experts):
        weights.append([torch.randn(intermediate,hidden,dtype=torch.bfloat16)*.05,
                        torch.randn(intermediate,hidden,dtype=torch.bfloat16)*.05,
                        torch.randn(hidden,intermediate,dtype=torch.bfloat16)*.05])
    with tempfile.TemporaryDirectory(prefix='alems-native-expert-') as temp:
        handle=_store.prefetch_handle(temp+'/',.5)
        ids=[]
        for expert,tensors in enumerate(weights):
            group=list(range(3*expert,3*expert+3));ids.append(group)
            for i,t in zip(group,tensors):handle.offload(t,i)
        dense=list(range(experts*3,experts*3+12))
        for i in dense:handle.offload(torch.zeros(1,dtype=torch.bfloat16),i)
        topology=[(f'dense.before.{j}',[[i]]) for j,i in enumerate(dense[:6])]
        topology += [('model.layers.0.mlp.experts',ids)]
        topology += [(f'dense.after.{j}',[[i]]) for j,i in enumerate(dense[6:])]
        handle.set_topology(topology)
        dispatcher=_store.expert_dispatcher(experts,1,0,5,2)
        for expert,group in enumerate(ids):dispatcher.register_expert(0,expert,group,'')
        gpuweights=[[t.cuda() for t in group] for group in weights]
        reference=Qwen3MoeExperts(Qwen3MoeConfig(hidden_size=hidden,
            moe_intermediate_size=intermediate,num_experts=experts,num_experts_per_tok=4))
        reference=reference.to(device='cuda',dtype=torch.bfloat16).eval()
        with torch.no_grad():
            for e,(gate,up,down) in enumerate(gpuweights):
                reference.gate_up_proj[e].copy_(torch.cat([gate,up]))
                reference.down_proj[e].copy_(down)
        results=[]
        for count in (1,17,127):
            x=torch.randn(count,hidden,dtype=torch.bfloat16,device='cuda')
            topweights,indices=torch.topk(torch.softmax(torch.randn(count,experts,device='cuda'),dim=-1),4,dim=-1)
            topweights/=topweights.sum(-1,keepdim=True)
            mask=F.one_hot(indices,experts).any(1)
            routing=torch.zeros(count,experts,device='cuda').scatter_(1,indices,topweights)
            expected=torch.zeros_like(x)
            with torch.no_grad():
                framework=reference(x,indices,topweights)
            for e,(gate,up,down) in enumerate(gpuweights):
                tokens=mask[:,e].nonzero().squeeze(1)
                if not len(tokens):continue
                h=x[tokens]
                v=F.linear(F.silu(F.linear(h,gate))*F.linear(h,up),down)
                expected.index_add_(0,tokens,(v.float()*routing[tokens,e,None]).to(x.dtype))
            active=mask.any(0).nonzero().flatten().tolist()
            for reverse in (False,True):
                stream=torch.cuda.Stream();stream.wait_stream(torch.cuda.current_stream())
                with torch.cuda.stream(stream):
                    dispatcher.set_inputs(x,mask,routing)
                    dispatcher.set_expected_queue(len(active))
                    for e in sorted(active,reverse=reverse):dispatcher.enqueue_expert(0,e,0,False)
                    dispatcher.notify_fetch_start()
                    actual=dispatcher.wait_expert().clone()
                stream.synchronize()
                diff=(actual.float()-expected.float()).abs()
                results.append(dict(tokens=count,reversed=reverse,bitwise_equal=torch.equal(actual,expected),framework_bitwise_equal=torch.equal(actual,framework),max_abs=float(diff.max()),framework_max_abs=float((actual.float()-framework.float()).abs().max())))
                (output/'expert-probe.json').write_text(json.dumps(results,indent=2)+'\n')
                if not torch.equal(actual,expected) or not torch.equal(actual,framework):
                    torch.save(dict(actual=actual.cpu(),expected=expected.cpu(),framework=framework.cpu()),output/f'expert-probe-failure-{count}-{reverse}.pt')
                    raise RuntimeError('native expert arithmetic differs from independently calculated BF16 result')
        del dispatcher
        handle.clean_up_resources()
    return results


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    config_path=Path(args.config).resolve(strict=True)
    config=json.loads(config_path.read_text())
    if config.get('reference_arithmetic')!='transformers-5.3-bf16-v1':
        raise ValueError('explicit reference arithmetic configuration required')
    from studies.energy_diagnosis.moe.prepare import verify_build
    build=verify_build(Path(config['build_manifest']))
    if subprocess.check_output(['git','status','--porcelain'],text=True).strip():
        raise ValueError('native arithmetic check requires a clean checkout')
    output=Path(args.output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    metadata=dict(config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                  build=build,source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                  scope='synthetic native expert arithmetic; not full-model, energy or task qualification',
                  status='running')
    def save():
        temporary=output/'status.tmp'
        temporary.write_text(json.dumps(metadata,indent=2)+'\n')
        temporary.replace(output/'status.json')
    save()
    try:
        metadata['results']=probe(output)
        metadata['status']='completed'
    except BaseException as error:
        metadata.update(status='failed',error=str(error))
        raise
    finally:
        save()
    print(json.dumps(metadata,indent=2))


if __name__=='__main__':
    main()
