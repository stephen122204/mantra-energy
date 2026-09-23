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
