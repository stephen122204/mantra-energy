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
