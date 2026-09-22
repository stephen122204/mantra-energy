"""Production CLI wiring with real owned fixture worker and real task tools."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
from studies.energy_diagnosis.moe.task_pack import MODULES

ROOT=Path(__file__).resolve().parents[1]
SPECS=[dict(kind=k,rows=128,seed=7) for k in ('numerical','business','etl')]

def launch(output,spec,case='success',max_runs=10):
    return subprocess.run([sys.executable,'-m','studies.energy_diagnosis.moe.run','--mode','fixture',
        '--output',str(output),'--task-pack',str(spec),'--policies','demand,fixed',
        '--max-runs',str(max_runs),'--deadline','30','--fixture-case',case],cwd=ROOT,capture_output=True,text=True,timeout=90)

@pytest.mark.parametrize('case',['success','wrong_answer','missing_telemetry'])
def test_cli_pack_records_true_verifier_identity_and_resumes(tmp_path,case):
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(SPECS))
    output=tmp_path/'run'
    first=launch(output,spec,case,max_runs=3)
    assert first.returncode==0,first.stdout+first.stderr
    second=launch(output,spec,case,max_runs=10)
    assert second.returncode==0,second.stdout+second.stderr
    report=json.loads(second.stdout)
    assert report['executed']==7 and report['validation']['valid']
    manifest=json.loads((output/'moe-manifest.json').read_text())
    assert manifest['task_pack']['specifications']==SPECS
    expected={m.VERSION:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in MODULES.values()}
    for task in manifest['task_catalog']:
        assert task['verifier_sha256']==expected[task['workload_version']]
    entries=[json.loads(line) for line in (output/'exports/attempts.jsonl').read_text().splitlines()]
    assert len(entries)==10
    for row in entries:
        plan=row['plan'];record=row['attempt']['execution_record']
        assert plan['verifier_sha256']==expected[plan['verifier_version']]
        assert record['simulated']
        assert record['verifier']['outcome']==('fail' if case=='wrong_answer' else 'pass')
        if case=='missing_telemetry':assert any(m['energy_j'] is None for m in record['measurements'])
    before=(output/'exports/attempts.jsonl').read_bytes()
    third=launch(output,spec,case)
    assert third.returncode==0,third.stdout+third.stderr
    assert json.loads(third.stdout)['executed']==0
    assert (output/'exports/attempts.jsonl').read_bytes()==before
    spec.write_text(json.dumps([dict(kind='numerical',rows=256,seed=7)]))
    changed=launch(output,spec,case)
    assert changed.returncode!=0 and 'task pack changed' in changed.stderr
    assert (output/'exports/attempts.jsonl').read_bytes()==before
