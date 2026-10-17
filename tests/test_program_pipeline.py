"""Real CLI, isolated tools/verifiers, simulated model/sensors, saved failure records."""
import json
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('case',['success','wrong_answer','missing_telemetry'])
def test_program_tasks_cli_and_resume(tmp_path,case):
    spec=tmp_path/'spec.json'
    spec.write_text(json.dumps([dict(kind='program',case=c,rows=128,seed=7)
        for c in ('conditional-dedup','user-histogram')]))
    output=tmp_path/'run'
    cmd=[sys.executable,'-m','studies.energy_diagnosis.moe.run','--mode','fixture',
         '--output',str(output),'--task-pack',str(spec),'--policies','demand',
         '--max-runs','2','--deadline','30','--fixture-case',case]
    run=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=90)
    assert run.returncode==0,run.stdout+run.stderr
    records=[json.loads(p.read_text()) for p in (output/'goals').glob('*/record.json')]
    assert len(records)==2
    for record in records:
        assert record['simulated']
        assert record['execution_status']=='completed'
        assert record['verifier']['outcome']==('fail' if case=='wrong_answer' else 'pass')
        if case=='missing_telemetry':assert any(m['energy_j'] is None for m in record['measurements'])
        else:assert all(m['status']=='valid' for m in record['measurements'])
    export=output/'exports/attempts.jsonl';before=export.read_bytes()
    assert len(before.splitlines())==2
    rerun=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=90)
    assert rerun.returncode==0,rerun.stdout+rerun.stderr
    assert json.loads(rerun.stdout)['executed']==0
    assert export.read_bytes()==before
