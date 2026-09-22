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
    assert record['cleanup_complete'] is True
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
    assert record['cleanup_complete'] is False


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


@pytest.mark.skipif(os.name != 'posix', reason='OpenSSH config parser on POSIX receiver')
def test_copy_ssh_preserves_known_hosts_path_with_spaces(tmp_path):
    import shlex
    import shutil
    if shutil.which('ssh') is None:
        pytest.skip('OpenSSH client unavailable')
    hosts = tmp_path / "Team Results" / "known_hosts"
    hosts.parent.mkdir()
    hosts.write_text('')
    command = copy_results.ssh_arguments(str(tmp_path / 'identity key'), str(hosts))
    # rsync passes -e through another argv parser; both routes must preserve it.
    assert shlex.split(shlex.join(command)) == command
    result = subprocess.run(command + ['-G', 'example.invalid'],
                            capture_output=True, text=True, check=True, timeout=10)
    fields = dict(line.split(' ', 1) for line in result.stdout.splitlines() if ' ' in line)
    assert fields['userknownhostsfile'] == str(hosts)
    assert fields['stricthostkeychecking'] in {'true', 'yes'}


def test_copy_rejects_multiline_known_hosts_path(tmp_path):
    with pytest.raises(ValueError, match='known-hosts'):
        copy_results.ssh_arguments('key', str(tmp_path / 'hosts\nother'))


@pytest.mark.skipif(os.name != 'posix', reason='POSIX supervisor')
def test_cleanup_failure_does_not_claim_success(tmp_path, monkeypatch):
    from studies.energy_diagnosis.diagnostics import run_bounded
    monkeypatch.setattr(sys, 'argv', ['run_bounded', *launcher(tmp_path, 'pass')[3:]])
    def fail_cleanup(child, *grace):
        raise OSError('fixture cleanup failure')
    monkeypatch.setattr(run_bounded, 'stop_group', fail_cleanup)
    assert run_bounded.main() == 1
    record = json.loads((tmp_path / 'job/status.json').read_text())
    assert record['status'] == 'failed'
    assert record['finished_utc']
    assert record['cleanup_complete'] is False


@pytest.mark.skipif(os.name != 'posix', reason='POSIX supervisor')
def test_detached_descendants_are_terminated_before_cleanup_is_claimed(tmp_path):
    # The child starts a worker in its own session, as the model worker and
    # isolated tool processes do; a process-group signal alone cannot reach it.
    code = ("import subprocess,sys,time;"
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],start_new_session=True);"
            "open(sys.argv[1] if len(sys.argv)>1 else 'worker.pid','w').write(str(p.pid));time.sleep(120)")
    process = subprocess.Popen(launcher(tmp_path, code, seconds=60))
    status = tmp_path / 'job/status.json'
    pid_file = tmp_path / 'worker.pid'
    try:
        for _ in range(300):
            if pid_file.exists() and pid_file.read_text().strip():
                break
            time.sleep(.02)
        else:
            raise AssertionError('detached worker never started')
        worker = int(pid_file.read_text())
        os.kill(worker, 0)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=60) == 130
        record = json.loads(status.read_text())
        assert record['status'] == 'interrupted' and record['cleanup_complete'] is True
        assert 'surviving_pids' not in record
        with pytest.raises(ProcessLookupError):
            os.kill(worker, 0)
    finally:
        if process.poll() is None:
            process.kill(); process.wait()
        try:
            os.kill(int(pid_file.read_text()), signal.SIGKILL)
        except (OSError, ValueError):
            pass
