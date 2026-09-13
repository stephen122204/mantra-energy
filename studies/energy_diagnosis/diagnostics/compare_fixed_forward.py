"""Compare separate qualified captures at exactly equal forced token prefixes."""
import argparse
import json
from pathlib import Path

from studies.energy_diagnosis.diagnostics.capture_fixed_forward import digest
from studies.energy_diagnosis.diagnostics.audit_saved_logits import compare


def load_capture(path):
    import torch
    path=Path(path).resolve(strict=True)
    supervisor=json.loads((path/'supervisor.json').read_text())
    metadata=json.loads((path/'capture.json').read_text())
    if not supervisor['capture_qualified'] or not supervisor['owned_worker_exited'] or supervisor['returncode'] != 0:
        raise ValueError('capture did not qualify; inspect saved failure first')
    if supervisor['capture_sha256'] != digest(path/'capture.json'):
        raise ValueError('capture metadata hash changed')
    if metadata['scores_sha256'] != digest(path/'scores.pt'):
        raise ValueError('score hash changed')
    if metadata.get('primer_scores_sha256') is not None and metadata['primer_scores_sha256'] != digest(path/'primer-scores.pt'):
        raise ValueError('primer score hash changed')
    scores=torch.load(path/'scores.pt',map_location='cpu',weights_only=True)
    if scores['logits'].shape[1] != 1+len(scores['continuation_ids']):
        raise ValueError('score count does not match forced continuation')
    expected=list(range(len(scores['prompt_ids']),len(scores['prompt_ids'])+len(scores['continuation_ids'])+1))
    if scores['cache_lengths'] != expected:
        raise ValueError('cache positions do not match tokens')
    return supervisor,metadata,scores


def comparison(left,right):
    a,ma,xa=load_capture(left)
    b,mb,xb=load_capture(right)
    if a['run_id']==b['run_id']:
        raise ValueError('same capture reused; not a separate execution')
    for key in ['case_sha256','config_sha256','model_revision','checkpoint_manifest_sha256','seed','attention',
                'torch_version','transformers_version','accelerate_version','cuda','gpu','source_commit','script_sha256']:
        if ma[key] != mb[key]:
            raise ValueError(f'unmatched {key}; use a separately declared diagnostic')
    if ma['source_dirty'] or mb['source_dirty'] or ma['model_training'] or mb['model_training']:
        raise ValueError('require clean source and evaluation mode')
    if ma['mode'].startswith('native') and mb['mode'].startswith('native'):
        def placement(m,key):
            return sorted((r['layer'],r['expert'],r['nbytes'],r['device']) for r in m['intervention'][key])
        for key in ['initial_snapshot','boundary_snapshot']:
            if placement(ma,key)!=placement(mb,key):
                raise ValueError(f'native {key} expert placement differs')
        for key in ['expert_cache_limit_bytes','expert_count','applied_config']:
            if ma['native_boot'][key]!=mb['native_boot'][key]:
                raise ValueError(f'native initial {key} differs')
    for key in ['prompt_ids','continuation_ids','cache_lengths']:
        if xa[key]!=xb[key]:
            raise ValueError(f'prefix mismatch: {key}')
    if xa['logits'].dtype!=xb['logits'].dtype:
        raise ValueError('dtype mismatch')
    report=compare(xa['logits'],xb['logits'])
    if bool(ma.get('primer_scores_sha256')) != bool(mb.get('primer_scores_sha256')):
        raise ValueError('primer presence differs')
    if ma.get('primer_scores_sha256'):
        import torch
        pa=torch.load(Path(left)/'primer-scores.pt',map_location='cpu',weights_only=True)
        pb=torch.load(Path(right)/'primer-scores.pt',map_location='cpu',weights_only=True)
        for key in ['prompt_ids','continuation_ids','cache_lengths']:
            if pa[key]!=pb[key]:raise ValueError(f'primer {key} mismatch')
        report['primer_comparison']=compare(pa['logits'],pb['logits'])
        report['both_stages_reference_relative_tolerance_pass']=report['reference_relative_tolerance_pass'] and report['primer_comparison']['reference_relative_tolerance_pass']
    report['dtype_saved']=str(xa['logits'].dtype)
    report['captured_prefix_lengths']=xa['cache_lengths']
    def annotate(source):
        position=dict(source)
        position['last_captured_position']=position.pop('input_final_position')
        position['phase']='prefill_endpoint' if position['position']==0 else 'cached_decode'
        position['prefix_tokens']=xa['cache_lengths'][position['position']]
        return position
    report['final_position']=annotate(report['final_position'])
    report['differing_argmax_positions']=[annotate(p) for p in report['differing_argmax_positions']]
    report.update(left=str(Path(left).resolve()),right=str(Path(right).resolve()),
                  left_mode=ma['mode'],right_mode=mb['mode'],
                  source_supervisor_sha256=[digest(Path(x)/'supervisor.json') for x in [left,right]],
                  source_capture_sha256=[digest(Path(x)/'capture.json') for x in [left,right]],
                  interpretation='Scores at one prefill endpoint and fixed cached-decode prefixes. No closed-loop correctness, tool-overlap or energy claim; no tolerance relaxation.')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--left',required=True);p.add_argument('--right',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    result=comparison(args.left,args.right)
    with Path(args.output).open('x') as f:
        json.dump(result,f,indent=2);f.write('\n')
    raise SystemExit(0 if result.get('both_stages_reference_relative_tolerance_pass',result['reference_relative_tolerance_pass']) else 3)
