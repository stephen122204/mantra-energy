"""Reconnectable receiver for immutable node snapshots; never launches work."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import time

from .archive_results import verify_bundle, verified_chain, safe_name, bundle_files
from .batch_coordinator import write, maintenance_windows
from .copy_results import ssh_arguments


def ingest(wire, out, host, root, partial=False):
    """Verify and file the snapshots in one transfer. With partial=True (a transfer cut off by the transport bound) the
    complete leading snapshots are kept and the cursor advances past them, so the next transfer resumes after them;
    returns None when not even the catalog and state arrived."""
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    state=json.loads((out/'receiver.json').read_text()) if (out/'receiver.json').exists() else dict(after='',previous=None,files={})
    if state['previous']:verified_chain(state['previous'])
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        tmp=Path(tmp);complete=set()
        try:
            with tarfile.open(wire) as tar:
                seen=set()
                for member in tar:
                    name=safe_name(member.name)
                    if '/' in name or not member.isfile() or name in seen or member.size>1024**3+16*1024**2:raise ValueError('unsafe transfer member')
                    seen.add(name)
                    with (tmp/name).open('xb') as target:
                        import shutil
                        shutil.copyfileobj(tar.extractfile(member),target)
                    complete.add(name)
        except (tarfile.ReadError,EOFError):
            if not partial:raise
        if not {'catalog.json','state.json'}<=complete:
            if partial:return None
            raise ValueError('transfer lacks catalog or state')
        catalog=json.loads((tmp/'catalog.json').read_text());remote_state=json.loads((tmp/'state.json').read_text())
        if catalog['root']!=root:raise ValueError('wrong source root')
        items=catalog['snapshots'];ids=[x['id'] for x in items]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate snapshot')
        if state['after'] and state['after'] not in ids:raise ValueError('missing receiver cursor')
        start=0 if not state['after'] else ids.index(state['after'])+1
        for item in items[start:]:
            name=safe_name(item['file']);batch=safe_name(item['id'])
            if '/' in name or '/' in batch:raise ValueError('invalid snapshot name')
            if partial and name not in complete:break
            source=tmp/name
            if hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('snapshot transport hash mismatch')
            header=verify_bundle(source,state['files'])
            dest=out/batch;dest.mkdir(exist_ok=True)
            target=dest/'snapshot.bundle'
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('existing snapshot mismatch')
            else:source.replace(target)
            link=None
            if state['previous']:
                p=Path(state['previous']);link=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            receipt=dict(status='verified',host=host,remote_directory=root,previous=link,bundle_sha256=item['sha256'],manifest=header)
            write(dest/'receipt.json',receipt)
            state.update(after=batch,previous=str((dest/'receipt.json').resolve()),files=bundle_files(header,state['files']))
            write(out/'receiver.json',state)
        write(out/'remote-state.json',remote_state)
    return dict(state,caught_up=state['after']==(ids[-1] if ids else ''))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',required=True);p.add_argument('--output',required=True);p.add_argument('--once',action='store_true')
    a=p.parse_args();spec=json.loads(Path(a.spec).read_text());out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    import fcntl
    with (out/'receiver.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            schedule=maintenance_windows(spec,time.time())
            if schedule is not None:
                inside,start,end=schedule
                # Connect only inside a window with enough time left to finish the transfer.
                if not inside or end-time.time()<240:
                    nxt=start if not inside else start+spec['maintenance']['period_seconds']
                    write(out/'transport-state.json',dict(status='waiting_for_maintenance_window',next_window_start=nxt))
                    if a.once:return
                    time.sleep(max(5,min(nxt-time.time(),600)));continue
            state=json.loads((out/'receiver.json').read_text()) if (out/'receiver.json').exists() else {}
            cmd=['timeout','180',spec['remote_python'],'-m','studies.energy_diagnosis.diagnostics.node_batches','--serve','--output',spec['node_output'],'--after',state.get('after','')]
            ssh=ssh_arguments(spec['identity_file'],spec['known_hosts'])+[spec['host'],'env '+shlex.quote('PYTHONPATH='+spec['remote_repository'])+' '+shlex.join(cmd)]
            try:
                cut=None
                try:
                    with (out/'transfer.partial').open('wb') as wire,(out/'transport.stderr').open('wb') as err:
                        subprocess.run(ssh,stdout=wire,stderr=err,check=True,timeout=195)
                except subprocess.SubprocessError as error:
                    cut=error
                # A transfer cut off by the transport bound still carries whole leading snapshots; keep them.
                received=ingest(out/'transfer.partial',out,spec['host'],spec['remote_directory'],partial=cut is not None)
                (out/'transfer.partial').unlink()
                if cut is not None:raise cut
                remote=json.loads((out/'remote-state.json').read_text())
                if remote['status'] in {'completed','stopped'} and received['caught_up']:return
            except (OSError,subprocess.SubprocessError) as error:
                write(out/'transport-state.json',dict(status='waiting_to_reconnect_or_for_batch_boundary',error=str(error)))
            if a.once:return
            time.sleep(30)

if __name__=='__main__':main()
