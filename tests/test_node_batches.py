import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from studies.energy_diagnosis.diagnostics.node_batches import run
from studies.energy_diagnosis.diagnostics.receive_node_batches import ingest
from studies.energy_diagnosis.diagnostics.archive_results import restore_snapshot

class NodeBatchesTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'results';self.root.mkdir();self.out=self.base/'control'
        self.spec=dict(host='example',remote_directory=str(self.root),remote_repository=str(self.base),remote_python=sys.executable,cutoff_utc='2099-01-01T00:00:00Z',retry_seconds=1,first_poll_delay_seconds=1,minimum_batch_seconds=10,batches=[])
        for i in range(2):
            status=f'batch-{i}/status.json'
            code="import pathlib,json; p=pathlib.Path("+repr(str(self.root/status))+");p.parent.mkdir();p.write_text(json.dumps(dict(status='completed',returncode=0,cleanup_complete=True)))"
            self.spec['batches'].append(dict(id=f'batch-{i}',argv=[sys.executable,'-c',code],status=status,log=f'logs/{i}'))
    def test_offline_completion_resume_and_later_restore(self):
        run(self.spec,self.out,gap=0,free_bytes=0)
        run(self.spec,self.out,gap=0,free_bytes=0) # no duplicate execution (mkdir would fail)
        catalog=json.loads((self.out/'catalog.json').read_text());self.assertEqual(len(catalog['snapshots']),2)
        wire=self.base/'wire.tar'
        with tarfile.open(wire,'w') as t:
            for n in ['catalog.json','state.json']:t.add(self.out/n,arcname=n)
            for x in catalog['snapshots']:t.add(self.out/'spool'/x['file'],arcname=x['file'])
        state=ingest(wire,self.base/'receiver','example',str(self.root))
        restore_snapshot(state['previous'],self.base/'restored')
        self.assertTrue((self.base/'restored/batch-1/status.json').exists())
        ingest(wire,self.base/'receiver','example',str(self.root)) # repeated receive idempotent
    def test_existing_completed_batch_not_rerun(self):
        p=self.root/'batch-0/status.json';p.parent.mkdir();p.write_text(json.dumps(dict(status='completed',returncode=0,cleanup_complete=True)))
        run(self.spec,self.out,gap=0,free_bytes=0)
        self.assertEqual(json.loads((self.out/'state.json').read_text())['status'],'completed')
    def test_ambiguous_dispatch_refused(self):
        p=self.root/'dispatch/batch-0.json';p.parent.mkdir();p.write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):run(self.spec,self.out,gap=0,free_bytes=0)
        self.assertFalse((self.root/'batch-0').exists())
    def test_failure_saved_and_stops_next_batch(self):
        p=self.root/'batch-0/status.json';p.parent.mkdir();p.write_text(json.dumps(dict(status='failed',returncode=1,cleanup_complete=True)))
        with self.assertRaisesRegex(RuntimeError,'invalid batch'):run(self.spec,self.out,gap=0,free_bytes=0)
        self.assertTrue((self.out/'spool/batch-0.bundle').exists());self.assertFalse((self.root/'batch-1').exists())
    def test_storage_guard(self):
        with self.assertRaisesRegex(RuntimeError,'low disk'):run(self.spec,self.out,gap=0,free_bytes=10**30)
        self.assertFalse((self.root/'batch-0').exists())
    def test_cutoff(self):
        self.spec['cutoff_utc']='2000-01-01T00:00:00Z'
        with self.assertRaises(TimeoutError):run(self.spec,self.out,gap=0,free_bytes=0)
    def test_changed_spec_refused(self):
        run(self.spec,self.out,gap=0,free_bytes=0);self.spec['minimum_batch_seconds']=11
        with self.assertRaisesRegex(ValueError,'changed'):run(self.spec,self.out,gap=0,free_bytes=0)
    def test_transfer_tampering_rejected(self):
        run(self.spec,self.out,gap=0,free_bytes=0)
        with (self.out/'spool/batch-0.bundle').open('ab') as f:f.write(b'x')
        wire=self.base/'wire.tar'
        with tarfile.open(wire,'w') as t:
            for n in ['catalog.json','state.json']:t.add(self.out/n,arcname=n)
            for n in ['batch-0.bundle','batch-1.bundle']:t.add(self.out/'spool'/n,arcname=n)
        with self.assertRaisesRegex(ValueError,'hash mismatch'):ingest(wire,self.base/'receiver','example',str(self.root))
    def test_receiver_cannot_enter_measurement_lock(self):
        import fcntl,subprocess,os
        run(self.spec,self.out,gap=0,free_bytes=0)
        with (self.out/'io.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            result=subprocess.run([sys.executable,'-m','studies.energy_diagnosis.diagnostics.node_batches','--serve','--output',str(self.out)],capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,b'')
    def test_partial_transport_then_reconnect(self):
        self.test_offline_completion_resume_and_later_restore()
        wire=self.base/'wire.tar';damaged=self.base/'truncated.tar';damaged.write_bytes(wire.read_bytes()[:200])
        with self.assertRaises((tarfile.ReadError,EOFError)):ingest(damaged,self.base/'receiver2','example',str(self.root))
        state=ingest(wire,self.base/'receiver2','example',str(self.root))
        self.assertEqual(state['after'],'batch-1')
    def test_cut_transfer_keeps_complete_leading_snapshots(self):
        run(self.spec,self.out,gap=0,free_bytes=0)
        catalog=json.loads((self.out/'catalog.json').read_text())
        wire=self.base/'wire.tar'
        with tarfile.open(wire,'w') as t:
            for n in ['catalog.json','state.json']:t.add(self.out/n,arcname=n)
            for x in catalog['snapshots']:t.add(self.out/'spool'/x['file'],arcname=x['file'])
        with tarfile.open(wire) as t:
            members={m.name:m for m in t.getmembers()}
        raw=wire.read_bytes();last=members[catalog['snapshots'][1]['file']]
        receiver=self.base/'receiver3'
        self.assertIsNone(ingest(self._cut(raw,members['catalog.json'].offset_data+5),receiver,'example',str(self.root),partial=True))
        self.assertFalse((receiver/'receiver.json').exists())
        cut=self._cut(raw,last.offset_data+last.size//2)
        with self.assertRaises((tarfile.ReadError,EOFError)):ingest(cut,receiver,'example',str(self.root))
        state=ingest(cut,receiver,'example',str(self.root),partial=True)
        self.assertEqual((state['after'],state['caught_up']),('batch-0',False))
        self.assertFalse((receiver/'batch-1').exists())
        state=ingest(wire,receiver,'example',str(self.root))
        self.assertEqual((state['after'],state['caught_up']),('batch-1',True))
        restore_snapshot(state['previous'],self.base/'restored3')
        self.assertTrue((self.base/'restored3/batch-0/status.json').exists())
        self.assertTrue((self.base/'restored3/batch-1/status.json').exists())
    def test_receiver_loop_resumes_after_timed_out_transfer(self):
        import subprocess
        from studies.energy_diagnosis.diagnostics import receive_node_batches as rnb
        run(self.spec,self.out,gap=0,free_bytes=0)
        catalog=json.loads((self.out/'catalog.json').read_text())
        wire=self.base/'wire.tar'
        with tarfile.open(wire,'w') as t:
            for n in ['catalog.json','state.json']:t.add(self.out/n,arcname=n)
            for x in catalog['snapshots']:t.add(self.out/'spool'/x['file'],arcname=x['file'])
        with tarfile.open(wire) as t:
            last=[m for m in t.getmembers()][-1]
        raw=wire.read_bytes();sends=[raw[:last.offset_data+last.size//2],raw]
        def fake(cmd,stdout,stderr,check,timeout):
            stdout.write(sends.pop(0))
            if sends:raise subprocess.TimeoutExpired(cmd,timeout)
        spec=dict(host='example',identity_file='/dev/null',known_hosts='/dev/null',remote_python='python3',
                  node_output=str(self.out),remote_repository=str(self.base),remote_directory=str(self.root))
        (self.base/'spec.json').write_text(json.dumps(spec));receiver=self.base/'receiver4'
        argv=['receive_node_batches','--spec',str(self.base/'spec.json'),'--output',str(receiver),'--once']
        with patch.object(rnb.subprocess,'run',side_effect=fake),patch.object(sys,'argv',argv):
            rnb.main()
            self.assertEqual(json.loads((receiver/'receiver.json').read_text())['after'],'batch-0')
            self.assertEqual(json.loads((receiver/'transport-state.json').read_text())['status'],'waiting_to_reconnect_or_for_batch_boundary')
            rnb.main()
        self.assertEqual(json.loads((receiver/'receiver.json').read_text())['after'],'batch-1')
        self.assertFalse((receiver/'transfer.partial').exists())
    def _cut(self,raw,size):
        path=self.base/f'cut-{size}.tar';path.write_bytes(raw[:size]);return path


class MaintenanceWindowTest(unittest.TestCase):
    def spec(self, **m):
        return dict(minimum_batch_seconds=600, maintenance=dict(anchor_utc='2026-01-01T00:00:00Z', period_seconds=3600, window_seconds=600, **m))

    def test_schedule_and_dispatch_rule(self):
        from studies.energy_diagnosis.diagnostics.batch_coordinator import maintenance_windows, dispatch_wait
        import datetime as dt
        t0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
        s = self.spec()
        self.assertEqual(maintenance_windows(s, t0 + 100), (True, t0, t0 + 600))
        self.assertEqual(maintenance_windows(s, t0 + 700), (False, t0 + 3600, t0 + 4200))
        self.assertEqual(dispatch_wait(s, t0 + 100), 500)            # inside a window: wait for its end
        self.assertEqual(dispatch_wait(s, t0 + 700), 0)              # 700+600+60 < 3600: may start
        self.assertEqual(dispatch_wait(s, t0 + 3000), 4200 - 3000)   # would reach the next window
        self.assertEqual(dispatch_wait(dict(minimum_batch_seconds=600), t0), 0)

    def test_validation(self):
        from studies.energy_diagnosis.diagnostics.batch_coordinator import validate
        base = dict(host='h', remote_directory='/a/b/c/d', remote_repository='/r', remote_python='/p', cutoff_utc='2099-01-01T00:00:00Z',
                    retry_seconds=1, first_poll_delay_seconds=1, minimum_batch_seconds=600,
                    batches=[dict(id='b0', argv=['x'], status='b0/s.json', log='l0')])
        validate(dict(base, maintenance=self.spec()['maintenance']))
        for bad in (dict(period_seconds=3600, window_seconds=200), dict(period_seconds=1200, window_seconds=600)):
            with self.assertRaises(ValueError):
                validate(dict(base, maintenance=dict(anchor_utc='2026-01-01T00:00:00Z', **bad)))

    def test_node_never_dispatches_into_a_window(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); root = base / 'results'; root.mkdir()
        import datetime as dt
        t0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
        clock = [t0 + 3000]  # 600 s batch + margin would overlap the window at t0+3600
        starts = []
        def sleep(seconds): clock[0] += seconds
        status = 'b0/status.json'
        code = "import pathlib,json; p=pathlib.Path(" + repr(str(root / status)) + ");p.parent.mkdir();p.write_text(json.dumps(dict(status='completed',returncode=0,cleanup_complete=True)))"
        spec = dict(host='h', remote_directory=str(root), remote_repository=str(base), remote_python=sys.executable,
                    cutoff_utc='2099-01-01T00:00:00Z', retry_seconds=1, first_poll_delay_seconds=1, minimum_batch_seconds=600,
                    maintenance=self.spec()['maintenance'],
                    batches=[dict(id='b0', argv=[sys.executable, '-c', code], status=status, log='l0')])
        import subprocess as sp
        real = sp.run
        def recording(*a, **k):
            starts.append(clock[0]); return real(*a, **k)
        with patch('studies.energy_diagnosis.diagnostics.node_batches.subprocess.run', recording):
            run(spec, base / 'control', gap=0, free_bytes=0, clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(starts, [t0 + 4200])


def test_real_mid_batch_scheduler_kill_refuses_duplicate_then_restores(tmp_path):
    """Kill an actual coordinator while its owned fixture batch is still alive.

    This exercises scheduler recovery and backup, not GPU process cleanup or
    energy validity. The fixture batch exits only after an explicit release.
    """
    import os
    import subprocess
    import time
    import psutil
    import pytest
    if os.name != 'posix':
        pytest.skip('POSIX scheduler termination')
    root=tmp_path/'results';root.mkdir();control=tmp_path/'control'
    release=tmp_path/'release'
    worker=tmp_path/'batch.py'
    worker.write_text('''import json,os,pathlib,sys,time
root=pathlib.Path(sys.argv[1]);release=pathlib.Path(sys.argv[2]);name=sys.argv[3]
p=root/name/'status.json';p.parent.mkdir()
with (root/'launches.txt').open('a') as out:out.write(name+'\\n')
def save(value):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(value));t.replace(p)
save(dict(status='running',child_pid=os.getpid(),cleanup_complete=False))
limit=time.monotonic()+30
while name=='first' and not release.exists():
 if time.monotonic()>limit:raise RuntimeError('fixture release timeout')
 time.sleep(.02)
save(dict(status='completed',returncode=0,cleanup_complete=True,child_pid=os.getpid()))
''')
    spec=dict(host='fixture',remote_directory=str(root),remote_repository=str(tmp_path),
              remote_python=sys.executable,cutoff_utc='2099-01-01T00:00:00Z',retry_seconds=1,
              first_poll_delay_seconds=1,minimum_batch_seconds=40,batches=[
                  dict(id=n,argv=[sys.executable,str(worker),str(root),str(release),n],
                       status=n+'/status.json',log='logs/'+n) for n in ('first','second')])
    specfile=tmp_path/'spec.json';specfile.write_text(json.dumps(spec))
    command=[sys.executable,'-c',
             'import json,sys;from studies.energy_diagnosis.diagnostics.node_batches import run;'
             'run(json.load(open(sys.argv[1])),sys.argv[2],gap=0,free_bytes=0)',str(specfile),str(control)]
    repository=Path(__file__).resolve().parents[1]
    child=None
    def until(predicate):
        deadline=time.monotonic()+10
        while not predicate():
            if time.monotonic()>deadline:raise AssertionError('fixture state did not arrive')
            time.sleep(.02)
    with (tmp_path/'coordinator.log').open('w') as log:
        coordinator=subprocess.Popen(command,cwd=repository,stdout=log,stderr=log)
        try:
            status=root/'first/status.json'
            until(status.exists)
            running=json.loads(status.read_text())
            child=psutil.Process(running['child_pid'])
            assert running['status']=='running' and child.is_running()
            coordinator.kill();coordinator.wait(timeout=10)
            assert child.is_running() and child.status()!=psutil.STATUS_ZOMBIE
            refused=subprocess.run(command,cwd=repository,capture_output=True,text=True,timeout=10)
            assert refused.returncode != 0 and 'existing batch not terminal' in refused.stderr
            assert (root/'launches.txt').read_text().splitlines()==['first']
            assert not (root/'second').exists()
            release.touch()
            until(lambda: not child.is_running() or child.status()==psutil.STATUS_ZOMBIE)
            resumed=subprocess.run(command,cwd=repository,capture_output=True,text=True,timeout=10)
            assert resumed.returncode==0,resumed.stdout+resumed.stderr
            assert (root/'launches.txt').read_text().splitlines()==['first','second']
            # A repeated resume cannot repeat either completed batch.
            again=subprocess.run(command,cwd=repository,capture_output=True,text=True,timeout=10)
            assert again.returncode==0,again.stderr
            assert (root/'launches.txt').read_text().splitlines()==['first','second']
            catalog=json.loads((control/'catalog.json').read_text())
            wire=tmp_path/'wire.tar'
            with tarfile.open(wire,'w') as bundle:
                for name in ('catalog.json','state.json'):bundle.add(control/name,arcname=name)
                for item in catalog['snapshots']:bundle.add(control/'spool'/item['file'],arcname=item['file'])
            received=ingest(wire,tmp_path/'receiver','fixture',str(root))
            restore_snapshot(received['previous'],tmp_path/'restored')
            assert (tmp_path/'restored/launches.txt').read_bytes()==(root/'launches.txt').read_bytes()
            assert json.loads((tmp_path/'restored/first/status.json').read_text())['status']=='completed'
        finally:
            release.touch()
            if coordinator.poll() is None:coordinator.kill();coordinator.wait(timeout=10)
            if child is not None and child.is_running() and child.status()!=psutil.STATUS_ZOMBIE:
                child.terminate()


class RecoveredBatchTest(unittest.TestCase):
    def test_interrupted_batch_is_retained_not_rerun_and_dispatch_continues(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); root = base / 'results'; root.mkdir()
        batches = []
        for i in range(2):
            status = f'b{i}/job/status.json'
            code = "import pathlib,json; p=pathlib.Path(" + repr(str(root / status)) + ");p.parent.mkdir(parents=True);p.write_text(json.dumps(dict(status='completed',returncode=0,cleanup_complete=True)))"
            batches.append(dict(id=f'b{i}', argv=[sys.executable, '-c', code], status=status, log=f'l{i}'))
        spec = dict(host='h', remote_directory=str(root), remote_repository=str(base), remote_python=sys.executable,
                    cutoff_utc='2099-01-01T00:00:00Z', retry_seconds=1, first_poll_delay_seconds=1, minimum_batch_seconds=30,
                    batches=batches)
        # b0 was interrupted mid-goal: non-terminal status, dispatch intent present.
        (root / 'b0/job').mkdir(parents=True)
        (root / 'b0/job/status.json').write_text(json.dumps(dict(status='running')))
        (root / 'dispatch').mkdir(); (root / 'dispatch/b0.json').write_text('{}')
        with self.assertRaises(RuntimeError):
            run(spec, base / 'control', gap=0, free_bytes=0)
        import hashlib
        # A hand-written record without the evidence fields is refused.
        (root / 'b0/recovery.json').write_text(json.dumps(dict(status='interrupted')))
        with self.assertRaises(RuntimeError):
            run(spec, base / 'control', gap=0, free_bytes=0)
        # A record for a different status than the one on disk is refused.
        (root / 'b0/recovery.json').write_text(json.dumps(dict(status='interrupted', partial_artifacts=[],
                                                              status_sha256='0' * 64)))
        with self.assertRaises(RuntimeError):
            run(spec, base / 'control', gap=0, free_bytes=0)
        seen = hashlib.sha256((root / 'b0/job/status.json').read_bytes()).hexdigest()
        (root / 'b0/recovery.json').write_text(json.dumps(dict(status='interrupted', partial_artifacts=[],
                                                              status_sha256=seen)))
        run(spec, base / 'control', gap=0, free_bytes=0)
        state = json.loads((base / 'control/state.json').read_text())
        self.assertEqual(state['completed'], ['b1'])
        self.assertEqual(state['recovered'], ['b0'])
        self.assertEqual(json.loads((root / 'b0/job/status.json').read_text())['status'], 'running')
        run(spec, base / 'control', gap=0, free_bytes=0)  # relaunch: nothing rerun, no duplicate entries
        self.assertEqual(json.loads((base / 'control/state.json').read_text())['recovered'], ['b0'])


class RecoveredSnapshotVerificationTest(unittest.TestCase):
    def test_recovered_label_requires_its_record(self):
        from studies.energy_diagnosis.diagnostics.archive_results import export_bundle, verify_bundle
        import hashlib
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / 'r'; (root / 'b0/job').mkdir(parents=True)
        (root / 'b0/job/status.json').write_text(json.dumps(dict(status='running')))
        rec = dict(status='interrupted', partial_artifacts=[],
                   status_sha256=hashlib.sha256((root / 'b0/job/status.json').read_bytes()).hexdigest())
        (root / 'b0/recovery.json').write_text(json.dumps(rec))
        out = Path(tmp.name) / 'b.bundle'
        with out.open('wb') as stream:
            export_bundle(root, 'b0/job/status.json', {}, stream, 2**30)
        header = verify_bundle(out, {})
        self.assertEqual(header['remote_job']['status'], 'interrupted_recovered')
        # Forge: same label, recovery record removed from the manifest.
        raw = out.read_bytes().split(b'\n', 2)
        forged = json.loads(raw[1]); del forged['changed']['b0/recovery.json']
        bad = Path(tmp.name) / 'bad.bundle'
        bad.write_bytes(raw[0] + b'\n' + json.dumps(forged, separators=(',', ':')).encode() + b'\n' + raw[2])
        with self.assertRaises(ValueError):
            verify_bundle(bad, {})


def test_export_refuses_unbound_or_stale_recovery_note(tmp_path):
    import hashlib
    import io
    import pytest
    from studies.energy_diagnosis.diagnostics.archive_results import export_bundle
    root=tmp_path/'results';job=root/'b0/job';job.mkdir(parents=True)
    status=job/'status.json';status.write_text(json.dumps({'status':'running'}))
    recovery=root/'b0/recovery.json'
    for note in ({'status':'interrupted'},
                 {'status':'interrupted','partial_artifacts':[],'status_sha256':'0'*64}):
        recovery.write_text(json.dumps(note))
        with pytest.raises(ValueError,match='not terminal'):
            export_bundle(root,'b0/job/status.json',{},io.BytesIO(),2**20)
    recovery.write_text(json.dumps(dict(status='interrupted',partial_artifacts=[],
                                       status_sha256=hashlib.sha256(status.read_bytes()).hexdigest())))
    header=export_bundle(root,'b0/job/status.json',{},io.BytesIO(),2**20)
    assert header['remote_job']['status']=='interrupted_recovered'


class HostTimerAdmissionTest(unittest.TestCase):
    """Admission against the host's own drifting maintenance timer (systemd), in addition to fixed windows."""

    def fake(self, timer='active', service='inactive', next_elapse='1h 0min 0s', realtime=''):
        from types import SimpleNamespace
        def run(argv, **kw):
            if argv[1] == 'is-active':
                return SimpleNamespace(stdout=(timer if argv[2].endswith('.timer') else service) + '\n', returncode=0)
            value = next_elapse if argv[-1] == 'NextElapseUSecMonotonic' else realtime
            return SimpleNamespace(stdout=value + '\n', returncode=0)
        return run

    def spec(self, **m):
        return dict(minimum_batch_seconds=780, maintenance=dict(anchor_utc='2026-01-01T00:00:00Z', period_seconds=3600,
                                                                window_seconds=600, systemd_timer='cache-vendordata.timer', **m))

    def test_parse_monotonic(self):
        from studies.energy_diagnosis.diagnostics.batch_coordinator import parse_monotonic
        self.assertAlmostEqual(parse_monotonic('6d 11h 13min 54.330386s'), 6 * 86400 + 11 * 3600 + 13 * 60 + 54.330386)
        self.assertEqual(parse_monotonic('500ms'), 0.5)
        for bad in ('', 'n/a', '5 minutes', '3h garbage'):
            with self.assertRaises(ValueError):
                parse_monotonic(bad)

    def test_timer_wait_rules(self):
        from studies.energy_diagnosis.diagnostics.batch_coordinator import timer_wait
        s = self.spec()
        now = lambda: 3600 - 2000.0                                   # 2000 s before the trigger: 780+60 fits
        self.assertEqual(timer_wait(s, run=self.fake(), monotonic=now), 0)
        self.assertEqual(timer_wait(s, run=self.fake(), monotonic=lambda: 3600 - 800.0), 30)   # would overlap
        self.assertEqual(timer_wait(s, run=self.fake(service='active'), monotonic=now), 30)  # updater running
        self.assertEqual(timer_wait(s, run=self.fake(service='failed'), monotonic=now), 0)   # nothing running
        self.assertEqual(timer_wait(s, run=self.fake(timer='inactive'), monotonic=now), 0)   # stopped: cannot elapse
        with self.assertRaises(RuntimeError):
            timer_wait(s, run=self.fake(timer='reloading'), monotonic=now)                  # untrusted schedule
        with self.assertRaises(RuntimeError):
            timer_wait(s, run=self.fake(service='reloading'), monotonic=now)
        with self.assertRaises(ValueError):
            timer_wait(s, run=self.fake(next_elapse='garbage'), monotonic=now)              # fails closed
        with self.assertRaises(RuntimeError):
            timer_wait(s, run=self.fake(next_elapse='', realtime=''), monotonic=now)         # active but no elapse
        self.assertEqual(timer_wait(dict(minimum_batch_seconds=780, maintenance=dict(anchor_utc='2026-01-01T00:00:00Z',
                         period_seconds=3600, window_seconds=600)), run=None), 0)           # not configured

    def test_validation_of_timer_unit(self):
        from studies.energy_diagnosis.diagnostics.batch_coordinator import validate
        base = dict(host='h', remote_directory='/a/b/c/d', remote_repository='/r', remote_python='/p', cutoff_utc='2099-01-01T00:00:00Z',
                    retry_seconds=1, first_poll_delay_seconds=1, minimum_batch_seconds=600,
                    batches=[dict(id='b0', argv=['x'], status='b0/s.json', log='l0')])
        validate(dict(base, maintenance=self.spec()['maintenance']))
        for bad in ('cache-vendordata', 'x.timer; rm -rf /', '../a.timer'):
            with self.assertRaises(ValueError):
                validate(dict(base, maintenance=dict(self.spec()['maintenance'], systemd_timer=bad)))

    def test_node_holds_batch_until_timer_clear(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); root = base / 'results'; root.mkdir()
        import datetime as dt
        t0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
        clock = [t0 + 700]                          # outside the fixed window, so only the host timer can hold
        holds = []
        def sleep(seconds): clock[0] += seconds
        waits = iter([30, 30, 0])
        def fake_timer(spec):
            w = next(waits); holds.append(w); return w
        status = 'b0/status.json'
        code = "import pathlib,json; p=pathlib.Path(" + repr(str(root / status)) + ");p.parent.mkdir();p.write_text(json.dumps(dict(status='completed',returncode=0,cleanup_complete=True)))"
        spec = dict(host='h', remote_directory=str(root), remote_repository=str(base), remote_python=sys.executable,
                    cutoff_utc='2099-01-01T00:00:00Z', retry_seconds=1, first_poll_delay_seconds=1, minimum_batch_seconds=600,
                    maintenance=dict(anchor_utc='2026-01-01T00:00:00Z', period_seconds=3600, window_seconds=600,
                                     systemd_timer='cache-vendordata.timer'),
                    batches=[dict(id='b0', argv=[sys.executable, '-c', code], status=status, log='l0')])
        starts = []
        import subprocess as sp
        real = sp.run
        def recording(*a, **k):
            starts.append(clock[0]); return real(*a, **k)
        with patch('studies.energy_diagnosis.diagnostics.node_batches.timer_wait', fake_timer), \
                patch('studies.energy_diagnosis.diagnostics.node_batches.subprocess.run', recording):
            run(spec, base / 'control', gap=0, free_bytes=0, clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(holds, [30, 30, 0])
        self.assertEqual(starts, [t0 + 760])


class CalendarTimerAndRetainedInvalidTest(unittest.TestCase):
    """Reproduced on LIQID05 (C2, 02:51 UTC): fwupd-refresh.timer (hourly, randomized delay, realtime) started
    fwupdmgr during a measured batch; the guard invalidated it and the scheduler stopped."""

    def test_realtime_timers_and_multiple_units(self):
        from types import SimpleNamespace
        from studies.energy_diagnosis.diagnostics.batch_coordinator import timer_wait, parse_realtime
        import datetime as dt
        now = dt.datetime(2026, 9, 28, 3, 21, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(parse_realtime('Mon 2026-09-28 03:36:03 UTC') - now, 15 * 60 + 3)
        schedule = {'cache-vendordata.timer': ('1h 0min 0s', ''), 'fwupd-refresh.timer': ('0', 'Mon 2026-09-28 03:36:03 UTC')}
        def run(argv, **kw):
            unit = argv[2]
            if argv[1] == 'is-active':
                return SimpleNamespace(stdout='active\n' if unit.endswith('.timer') else 'inactive\n', returncode=0)
            mono, real = schedule[unit]
            return SimpleNamespace(stdout=(mono if argv[-1] == 'NextElapseUSecMonotonic' else real) + '\n', returncode=0)
        spec = dict(minimum_batch_seconds=780, maintenance=dict(anchor_utc='2026-01-01T00:00:00Z', period_seconds=3600,
                    window_seconds=600, systemd_timers=['cache-vendordata.timer', 'fwupd-refresh.timer']))
        # fwupd elapses in 903 s <= 780 + 60? no: 903 > 840 -> clear; vendordata far away
        self.assertEqual(timer_wait(spec, run=run, monotonic=lambda: 0.0, now=lambda: now), 0)
        # two minutes later fwupd is within the batch horizon -> hold
        self.assertEqual(timer_wait(spec, run=run, monotonic=lambda: 0.0, now=lambda: now + 120), 30)

    def spec(self, root, base, retained, middle='interference_detected', cleanup=True):
        import json as _json
        batches = []
        for i, status in enumerate(['completed', middle, 'completed']):
            st = f'b{i}/job/status.json'
            code = ("import pathlib,json; p=pathlib.Path(" + repr(str(root / st)) + ");p.parent.mkdir(parents=True);"
                    "p.write_text(json.dumps(dict(status=" + repr(status) + ",returncode=0 if " + repr(status) + "=='completed' else 76,cleanup_complete=" + repr(cleanup) + ")))")
            batches.append(dict(id=f'b{i}', argv=[sys.executable, '-c', code], status=st, log=f'l{i}'))
        return dict(host='h', remote_directory=str(root), remote_repository=str(base), remote_python=sys.executable,
                    cutoff_utc='2099-01-01T00:00:00Z', retry_seconds=1, first_poll_delay_seconds=1, minimum_batch_seconds=10,
                    batches=batches, **({'retained_invalid': retained} if retained else {}))

    def test_unreviewed_invalid_batch_still_stops(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); root = base / 'r' / 'e' / 's'; root.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'invalid batch retained'):
            run(self.spec(root, base, []), base / 'control', gap=0, free_bytes=0)
        self.assertFalse((root / 'b2').exists())

    def test_reviewed_invalid_batch_is_kept_and_collection_continues(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); root = base / 'r' / 'e' / 's'; root.mkdir(parents=True)
        state = run(self.spec(root, base, ['b1']), base / 'control', gap=0, free_bytes=0)
        saved = json.loads((base / 'control' / 'state.json').read_text())
        self.assertEqual(saved['completed'], ['b0', 'b2']); self.assertEqual(saved['retained_invalid'], ['b1'])
        self.assertEqual(json.loads((root / 'b1/job/status.json').read_text())['status'], 'interference_detected')

    def test_reviewed_failed_batch_with_confirmed_cleanup_is_kept(self):
        # Reproduced on LIQID05 (r02-etl-etl-latest-v3-n1000000-s7-q8): the harness failed after measurement
        # (backend release), leaving a failed batch with confirmed cleanup that stopped collection.
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); root = base / 'r' / 'e' / 's'; root.mkdir(parents=True)
        run(self.spec(root, base, ['b1'], middle='failed'), base / 'control', gap=0, free_bytes=0)
        saved = json.loads((base / 'control' / 'state.json').read_text())
        self.assertEqual(saved['completed'], ['b0', 'b2']); self.assertEqual(saved['retained_invalid'], ['b1'])

    def test_reviewed_failed_batch_without_confirmed_cleanup_still_stops(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); root = base / 'r' / 'e' / 's'; root.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'invalid batch retained'):
            run(self.spec(root, base, ['b1'], middle='failed', cleanup=False), base / 'control', gap=0, free_bytes=0)
        self.assertFalse((root / 'b2').exists())

    def test_unreviewed_failed_batch_still_stops(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); root = base / 'r' / 'e' / 's'; root.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'invalid batch retained'):
            run(self.spec(root, base, [], middle='failed'), base / 'control', gap=0, free_bytes=0)
        self.assertFalse((root / 'b2').exists())


class SpecificationRevisionTest(unittest.TestCase):
    """Reproduced on LIQID05: continuing a stopped campaign under a revised specification in a fresh control
    directory must re-snapshot every earlier batch at once and exceeded the 1 GiB snapshot bound. A reviewed
    revision instead continues the existing control directory (and snapshot chain) when batches are identical."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.root = self.base / 'r' / 'e' / 's'; self.root.mkdir(parents=True)

    def spec(self, statuses, **extra):
        batches = []
        for i, status in enumerate(statuses):
            st = f'b{i}/job/status.json'
            code = ("import pathlib,json; p=pathlib.Path(" + repr(str(self.root / st)) + ");p.parent.mkdir(parents=True);"
                    "p.write_text(json.dumps(dict(status=" + repr(status) + ",returncode=0 if " + repr(status) + "=='completed' else 76,cleanup_complete=True)))")
            batches.append(dict(id=f'b{i}', argv=[sys.executable, '-c', code], status=st, log=f'l{i}'))
        return dict(host='h', remote_directory=str(self.root), remote_repository=str(self.base), remote_python=sys.executable,
                    cutoff_utc='2099-01-01T00:00:00Z', retry_seconds=1, first_poll_delay_seconds=1, minimum_batch_seconds=10,
                    batches=batches, **extra)

    def test_reviewed_revision_continues_same_control_without_rerun(self):
        from studies.energy_diagnosis.diagnostics.node_batches import run
        old = self.spec(['completed', 'interference_detected', 'completed'])
        control = self.base / 'control'
        with self.assertRaisesRegex(RuntimeError, 'invalid batch retained'):
            run(old, control, gap=0, free_bytes=0)
        new = dict(old, retained_invalid=['b1'])
        with self.assertRaisesRegex(ValueError, 'changed node specification'):
            run(new, control, gap=0, free_bytes=0)                         # no reviewed predecessor given
        run(new, control, gap=0, free_bytes=0, supersedes=old)
        state = json.loads((control / 'state.json').read_text())
        self.assertEqual(state['completed'], ['b0', 'b2']) ; self.assertEqual(state['retained_invalid'], ['b1'])
        self.assertEqual(state['revisions'][0]['changed'], ['retained_invalid'])
        self.assertEqual(len(list((control / 'spool').glob('*.bundle'))), 3)

    def test_revision_refused_if_batches_or_predecessor_differ(self):
        from studies.energy_diagnosis.diagnostics.node_batches import run, revision_allowed
        old = self.spec(['completed', 'completed'])
        run(old, self.base / 'control', gap=0, free_bytes=0)
        changed = self.spec(['completed', 'completed']); changed['batches'][1]['argv'] = changed['batches'][1]['argv'] + ['x']
        with self.assertRaisesRegex(ValueError, 'field batches differs'):
            run(changed, self.base / 'control', gap=0, free_bytes=0, supersedes=old)
        other = dict(old, cutoff_utc='2098-01-01T00:00:00Z')
        self.assertFalse(revision_allowed(dict(old, retained_invalid=[]), other, 'x')[0])


class HostTimerHoldTest(unittest.TestCase):
    """Reproduced on LIQID05 (2026-09-28 17:59 UTC): with maintenance.systemd_timers (a list) the scheduler's
    hold path read the removed singular key and crashed with KeyError the first time a timer actually held."""

    def test_hold_with_timer_list_records_units_and_continues(self):
        from unittest import mock
        from studies.energy_diagnosis.diagnostics import node_batches as nb
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); root = base / 'r' / 'e' / 's'; root.mkdir(parents=True)
        st = 'b0/job/status.json'
        code = ("import pathlib,json; p=pathlib.Path(" + repr(str(root / st)) + ");p.parent.mkdir(parents=True);"
                "p.write_text(json.dumps(dict(status='completed',returncode=0,cleanup_complete=True)))")
        spec = dict(host='h', remote_directory=str(root), remote_repository=str(base), remote_python=sys.executable,
                    cutoff_utc='2099-01-01T00:00:00Z', retry_seconds=1, first_poll_delay_seconds=1, minimum_batch_seconds=10,
                    maintenance=dict(anchor_utc='2026-01-01T00:00:00Z', period_seconds=3600, window_seconds=600,
                                     systemd_timers=['systemd-tmpfiles-clean.timer']),
                    batches=[dict(id='b0', argv=[sys.executable, '-c', code], status=st, log='l0')])
        holds = iter([7, 0]); saved = []
        real_write = nb.write
        def write(path, data):
            if Path(path).name == 'state.json': saved.append(dict(data))
            return real_write(path, data)
        with mock.patch.object(nb, 'dispatch_wait', lambda *a: 0), mock.patch.object(nb, 'timer_wait', lambda *a: next(holds)), \
                mock.patch.object(nb, 'write', write):
            nb.run(spec, base / 'control', gap=0, free_bytes=0, sleep=lambda s: None)
        hold = [s for s in saved if s['status'] == 'host_maintenance_hold']
        self.assertEqual(hold[0]['units'], ['systemd-tmpfiles-clean.timer'])
        self.assertEqual(json.loads((base / 'control' / 'state.json').read_text())['completed'], ['b0'])
