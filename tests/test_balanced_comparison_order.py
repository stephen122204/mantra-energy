"""Balanced pair ordering, declared identities and actual CLI resume behavior."""
from collections import Counter, defaultdict
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import pytest
from studies.energy_diagnosis.campaign import CampaignSchedule, PlannedRun, ScheduleBlock, LedgerValidationError

ROOT=Path(__file__).resolve().parents[1]

def blocks(repeats=6):
    result=[]
    for repeat in range(repeats):
        for task in ('a','b','c','d'):
            runs=tuple(PlannedRun(f'{task}-{repeat}-{setting}',i+1,task,setting,False,1,
                '1'*40,'2'*64,'3'*64,'v1','4'*64,simulated=True)
                for i,setting in enumerate(('demand','fixed')))
            result.append(ScheduleBlock(f'{task}-{repeat}','same-session','5'*64,runs))
    return result


def test_balanced_pairs_have_equal_first_positions_and_seeded_complements():
    original=blocks()
    first=CampaignSchedule.build(original,seed=17,balanced_pairs=True)
    assert first==CampaignSchedule.build(original,seed=17,balanced_pairs=True)
    assert first!=CampaignSchedule.build(original,seed=18,balanced_pairs=True)
    positions=defaultdict(Counter); orders=defaultdict(list)
    for offset,block in enumerate(original):
        pair=first.entries[2*offset:2*offset+2]
        assert {p.planned_run.planned_run_id for p in pair}=={r.planned_run_id for r in block.runs}
        assert all(p.block_id==block.block_id for p in pair)
        positions[pair[0].planned_run.task_id][pair[0].planned_run.setting_id]+=1
        orders[pair[0].planned_run.task_id].append([p.planned_run.setting_id for p in pair])
    assert all(count=={'demand':3,'fixed':3} for count in positions.values())
    for order in orders.values():
        assert all(order[i]==order[i+1][::-1] for i in range(0,6,2))
    assert [p.declared_order for p in first.entries]==list(range(1,49))
    assert CampaignSchedule.build(original,seed=17)==CampaignSchedule.build(original,seed=17,balanced_pairs=False)


def test_balance_refuses_odd_pairs_mixed_inputs_and_nonpairs():
    with pytest.raises(LedgerValidationError,match='even'):
        CampaignSchedule.build(blocks(3),seed=7,balanced_pairs=True)
    for change in ('task_id','task_asset_sha256','model_sha256','verifier_sha256'):
        rows=blocks(2); pair=rows[0].runs
        value='other' if change=='task_id' else 'a'*64
        rows[0]=replace(rows[0],runs=(pair[0],replace(pair[1],**{change:value})))
        with pytest.raises(LedgerValidationError):CampaignSchedule.build(rows,seed=7,balanced_pairs=True)
    rows=blocks(2);rows[0]=replace(rows[0],runs=rows[0].runs[:1])
    with pytest.raises(LedgerValidationError,match='two settings'):
        CampaignSchedule.build(rows,seed=7,balanced_pairs=True)


def test_cli_records_balanced_order_and_resumes_without_reordering(tmp_path):
    spec=tmp_path/'spec.json';spec.write_text(json.dumps([dict(kind='numerical',rows=128,seed=7)]))
    output=tmp_path/'campaign'
    base=[sys.executable,'-m','studies.energy_diagnosis.moe.run','--mode','fixture','--output',str(output),
          '--task-pack',str(spec),'--policies','demand,fixed','--repeats','2','--deadline','30']
    def launch(order,count):
        return subprocess.run(base+['--comparison-order',order,'--max-runs',str(count)],cwd=ROOT,capture_output=True,text=True,timeout=90)
    initial=launch('balanced-pairs',1);assert initial.returncode==0,initial.stderr
    manifest_bytes=(output/'moe-manifest.json').read_bytes()
    resumed=launch('balanced-pairs',4);assert resumed.returncode==0,resumed.stderr
    assert json.loads(resumed.stdout)['executed']==3
    assert (output/'moe-manifest.json').read_bytes()==manifest_bytes
    manifest=json.loads(manifest_bytes);assert manifest['comparison_order']=='balanced-pairs'
    entries=manifest['schedule']['entries']
    assert entries[0]['planned_run']['setting_id']==entries[3]['planned_run']['setting_id']
    before=(output/'exports/attempts.jsonl').read_bytes()
    changed=launch('random',4)
    assert changed.returncode!=0 and 'manifest changed' in changed.stderr
    assert (output/'exports/attempts.jsonl').read_bytes()==before
    invalid=subprocess.run(base+['--repeats','3','--comparison-order','balanced-pairs'],cwd=ROOT,capture_output=True,text=True,timeout=15)
    assert invalid.returncode==2 and 'even repetitions' in invalid.stderr
