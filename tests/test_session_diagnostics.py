import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from studies.energy_diagnosis.diagnostics import copy_results, audit_counters, run_qualification


def launcher(tmp_path,code,seconds=2,output='job'):
    return [sys.executable,'-m','studies.energy_diagnosis.diagnostics.run_bounded',
            '--output',str(tmp_path/output),'--cwd',str(tmp_path),'--seconds',str(seconds),
            '--cutoff-utc',(dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=5)).isoformat(),
            '--lock',str(tmp_path/'lock'),'--',sys.executable,'-c',code]


@pytest.mark.skipif(os.name!='posix',reason='POSIX process group supervisor')
@pytest.mark.parametrize('code,status,rc',[("print('retained')",'completed',0),
    ("print('failure');raise SystemExit(7)",'failed',7),
    ('import time;time.sleep(30)','timed_out',124)])
def test_bounded_terminal_status_and_log(tmp_path,code,status,rc):
    r=subprocess.run(launcher(tmp_path,code,seconds=.2 if status=='timed_out' else 3),timeout=15)
    assert r.returncode==rc
    record=json.loads((tmp_path/'job/status.json').read_text())
    assert record['status']==status and record['returncode']==rc and record['finished_utc']
    assert (tmp_path/'job/run.log').is_file()
    with pytest.raises(ProcessLookupError):os.kill(record['child_pid'],0)


@pytest.mark.skipif(os.name!='posix',reason='POSIX process group supervisor')
def test_lock_interruption_and_resume_after_cleanup(tmp_path):
    process=subprocess.Popen(launcher(tmp_path,'import time;time.sleep(30)',seconds=60))
    status=tmp_path/'job/status.json'
    try:
        for _ in range(150):
            if status.exists() and json.loads(status.read_text())['status']=='running':break
            time.sleep(.02)
        else:raise AssertionError('supervisor never started')
        child=json.loads(status.read_text())['child_pid']
        blocked=subprocess.run(launcher(tmp_path,'pass',output='blocked'),timeout=15)
        assert blocked.returncode==75
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15)==130
        assert json.loads(status.read_text())['status']=='interrupted'
        with pytest.raises(ProcessLookupError):os.kill(child,0)
        assert subprocess.run(launcher(tmp_path,'pass',output='next'),timeout=15).returncode==0
    finally:
        if process.poll() is None:process.kill();process.wait()


@pytest.mark.skipif(os.name!='posix',reason='POSIX supervisor')
def test_spawn_failure_is_recorded(tmp_path):
    command=launcher(tmp_path,'pass')
    command[-3:]=['/definitely/missing/command']
    assert subprocess.run(command,timeout=15).returncode==1
    record=json.loads((tmp_path/'job/status.json').read_text())
    assert record['status']=='failed' and 'error' in record


def test_copy_verifier_rejects_corruption_missing_and_escape(tmp_path):
    (tmp_path/'a').write_text('raw')
    hashes={'a':copy_results.digest(tmp_path/'a')}
    assert copy_results.verify(tmp_path,hashes)==[]
    (tmp_path/'a').write_text('changed')
    assert copy_results.verify(tmp_path,hashes)==['a']
    assert copy_results.verify(tmp_path,{'absent':'x'})==['absent']
    for name in ['../outside','/absolute','..\\outside']:
        with pytest.raises(ValueError):copy_results.verify(tmp_path,{name:'x'})


def test_copy_terminal_failure_is_retained_not_relabelled_as_success(tmp_path,monkeypatch):
    source=tmp_path/'raw';source.write_text('preserved')
    target=tmp_path/'receipt'
    cutoff=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=5)).isoformat()
    monkeypatch.setattr(sys,'argv',['copy','--host','cc@example.invalid','--identity-file','key',
        '--known-hosts','hosts','--remote-directory','/home/cc/results','--remote-status','job/status.json',
        '--destination',str(target),'--cutoff-utc',cutoff])
    calls=[]
    def fake_run(command,**kwargs):
        calls.append(command)
        if command[0]=='rsync':
            (target/'artifacts/raw').write_bytes(source.read_bytes())
            return subprocess.CompletedProcess(command,0,stdout='')
        assert 'StrictHostKeyChecking=yes' in command
        payload={'status':'failed','returncode':2} if command[-1].startswith('cat ') else {'raw':copy_results.digest(source)}
        return subprocess.CompletedProcess(command,0,stdout=json.dumps(payload))
    monkeypatch.setattr(subprocess,'run',fake_run)
    assert copy_results.main()==0
    result=json.loads((target/'status.json').read_text())
    assert result['status']=='copied_and_verified' and result['remote_job']['status']=='failed'
    assert result['files']==1 and sum(c[0]=='rsync' for c in calls)==2


def counter_packet():
    return dict(goal_start_ns=0,goal_end_ns=1_000_000_000,
        measurements=[dict(domain_id='cpu',status='valid',energy_j=1)],
        samples=[dict(domain_id='cpu',sample_id=f'id:{tag}:cpu',status='ok',unit='microjoules',
                      acquired_start_ns=i,acquired_end_ns=i+1,value=v)
                 for i,(tag,v) in enumerate([('goal_start',0),('goal_end',1_000_000)])])


def test_counter_audit_rejects_missing_wrong_energy_and_wrap(tmp_path):
    with pytest.raises(ValueError):audit_counters.audit(tmp_path)
    for i in range(2):
        for kind in ('idle','cpu','gpu','combined'):
            (tmp_path/f'{i}-{kind}.json').write_text(json.dumps(counter_packet()))
    assert len(audit_counters.audit(tmp_path))==8
    path=tmp_path/'0-idle.json'
    packet=counter_packet();packet['measurements'][0]['energy_j']=2
    path.write_text(json.dumps(packet))
    with pytest.raises(ValueError,match='derived energy'):audit_counters.audit(tmp_path)
    packet=counter_packet();packet['samples'][1]['value']=-1
    path.write_text(json.dumps(packet))
    with pytest.raises(ValueError,match='wrap/reset'):audit_counters.audit(tmp_path)


def test_qualification_stops_at_failed_preparation(tmp_path,monkeypatch):
    out=tmp_path/'q'
    monkeypatch.setattr(sys,'argv',['q','--config','c','--case','k','--output',str(out)])
    calls=[]
    def fake_run(command):
        calls.append(command)
        return subprocess.CompletedProcess(command,2 if 'native-preparation' in command else 0)
    monkeypatch.setattr(subprocess,'run',fake_run)
    assert run_qualification.main()==2
    assert len(calls)==4
    assert json.loads((out/'stages.json').read_text())[-1]['stage']=='preparation'
    assert not any('reference' in c for c in calls)
