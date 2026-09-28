"""Node-owned serial execution with immutable between-batch backup snapshots.

A receiver may be offline indefinitely. This is local durability, not off-node
redundancy. A shared lock excludes transfer and snapshot work from measurement.
Existing ambiguous dispatch intents stop rather than silently repeat a batch.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .archive_results import export_bundle, verify_bundle, safe_name
from .batch_coordinator import validate, write, dispatch_wait, timer_wait


def read(path):
    return json.loads(Path(path).read_text())


def successful(job):
    return job.get('status') == 'completed' and job.get('returncode') == 0 and job.get('cleanup_complete') is True


def recovery_valid(recovery, jobpath):
    """A recovery record written by campaign_check recover for exactly the status still on disk."""
    if not recovery.exists():
        return False
    rec = read(recovery)
    current = jobpath.read_bytes() if jobpath.exists() else b'missing'
    return (rec.get('status') == 'interrupted' and isinstance(rec.get('partial_artifacts'), list)
            and rec.get('status_sha256') == hashlib.sha256(current).hexdigest())


def checkpoint(root, spool, batch, previous):
    name = safe_name(batch['id'])
    target = spool / (name + '.bundle')
    if target.exists():
        return verify_bundle(target, previous)
    partial = spool / (name + '.partial')
    # Only an unpublished partial is replaceable; terminal evidence is immutable.
    with partial.open('wb') as stream:
        export_bundle(root, batch['status'], previous, stream, 1024 * 1024 * 1024)
        stream.flush()
        os.fsync(stream.fileno())
    header = verify_bundle(partial, previous)
    partial.replace(target)
    return header


# A reviewed specification revision may change only how batches are admitted or which reviewed invalid batches
# are retained; the batches themselves (ids, argv, status and log paths, order) must be identical.
REVISABLE = {'maintenance', 'retained_invalid', 'plan_sha256'}


def revision_allowed(new, old, recorded_sha):
    if hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest() != recorded_sha:
        return False, 'superseded specification does not match the recorded one'
    for key in (set(new) | set(old)) - REVISABLE:
        if new.get(key) != old.get(key):
            return False, f'field {key} differs; only {sorted(REVISABLE)} may change'
    return True, None


def run(spec, out, *, gap=45, free_bytes=8 * 1024**3, clock=time.time, sleep=time.sleep, supersedes=None):
    cutoff = validate(spec)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    root = Path(spec['remote_directory'])
    spool = out / 'spool'; spool.mkdir(exist_ok=True)
    identity = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    with (out/'owner.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = read(out/'state.json') if (out/'state.json').exists() else dict(spec_sha256=identity, completed=[])
        if state['spec_sha256'] != identity:
            ok, why = revision_allowed(spec, supersedes, state['spec_sha256']) if supersedes else (False, None)
            if not ok:
                raise ValueError('changed node specification' + (f': {why}' if why else ''))
            state.setdefault('revisions', []).append(dict(
                from_spec_sha256=state['spec_sha256'], to_spec_sha256=identity,
                utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                changed=sorted(k for k in REVISABLE if spec.get(k) != supersedes.get(k))))
            state['spec_sha256'] = identity
            write(out/'state.json', state)
        previous = {}; catalog = []
        # Validate every published incremental snapshot, including after restart.
        for batch in spec['batches']:
            target = spool / (batch['id']+'.bundle')
            if not target.exists(): break
            header = verify_bundle(target, previous); previous = header['files']
            catalog.append(dict(id=batch['id'], file=target.name, sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
        if not set(state['completed']).issubset({x['id'] for x in catalog}):
            raise ValueError('completed state lacks verified snapshots')
        if catalog:
            write(out/'catalog.json',dict(root=str(root),snapshots=catalog))
        def save(status, **kw):
            state.update(status=status, updated_utc=dt.datetime.now(dt.timezone.utc).isoformat(), **kw)
            write(out/'state.json', state)
        try:
            for batch in spec['batches']:
                jobpath = root / batch['status']
                if batch['id'] not in state['completed'] and not jobpath.exists():
                    # Outside the io lock: transfers may run during the maintenance window.
                    while True:
                        wait = dispatch_wait(spec, clock())
                        if wait > 0:
                            save('maintenance_window', batch=batch['id'], resume_utc=dt.datetime.fromtimestamp(clock()+wait, dt.timezone.utc).isoformat())
                            sleep(min(wait, 60)); continue
                        # The host's own maintenance timer drifts against fixed windows; never overlap it.
                        hold = timer_wait(spec)
                        if hold > 0:
                            save('host_maintenance_hold', batch=batch['id'], unit=spec['maintenance']['systemd_timer'])
                            sleep(hold); continue
                        break
                with (out/'io.lock').open('a') as gate:
                    fcntl.flock(gate, fcntl.LOCK_EX)
                    jobpath = root / batch['status']
                    if batch['id'] in state['completed']:
                        if not successful(read(jobpath)):
                            raise ValueError('previously completed status changed')
                        continue
                    if clock() >= cutoff:
                        raise TimeoutError('node cutoff reached')
                    if shutil.disk_usage(out).free < free_bytes:
                        raise RuntimeError('low disk: stop before further work')
                    intent = root/'dispatch'/(batch['id']+'.json')
                    if not jobpath.exists():
                        if intent.exists():
                            raise RuntimeError('ambiguous prior dispatch; operator review required')
                        if clock()+spec['minimum_batch_seconds'] >= cutoff:
                            raise TimeoutError('insufficient next-batch time budget')
                        intent.parent.mkdir(parents=True, exist_ok=True)
                        with intent.open('x') as stream:
                            json.dump(dict(status='node_dispatch_intent', argv=batch['argv']),stream)
                        save('measuring', batch=batch['id'])
                        logfile=root/batch['log'];logfile.parent.mkdir(parents=True,exist_ok=True)
                        with logfile.open('xb') as stream:
                            # Synchronous parent sleeps through measurement; wrapper retains
                            # its own timeout, process guard and cleanup/SSH restoration.
                            result=subprocess.run(batch['argv'],cwd=spec['remote_repository'],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,timeout=spec['minimum_batch_seconds'])
                        if not jobpath.exists():
                            raise RuntimeError('wrapper exited without terminal status')
                        if result.returncode and successful(read(jobpath)):
                            raise RuntimeError('wrapper failed after job completion')
                    job=read(jobpath)
                    recovered=jobpath.parent.parent/'recovery.json'
                    if job.get('status') not in {'completed','failed','timed_out','interrupted','interference_detected','blocked_by_other_job'}:
                        # An interrupted batch is never adopted or rerun. Only an explicit, verified
                        # recovery record (campaign_check recover) classifies it so dispatch can continue.
                        if not recovery_valid(recovered, jobpath):
                            raise RuntimeError('existing batch not terminal; no adoption or duplicate launch')
                        job=dict(status='interrupted_recovered')
                    save('checkpointing',batch=batch['id'])
                    if not any(x['id']==batch['id'] for x in catalog):
                        header=checkpoint(root,spool,batch,previous);previous=header['files']
                        target=spool/(batch['id']+'.bundle')
                        catalog.append(dict(id=batch['id'],file=target.name,sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
                        write(out/'catalog.json',dict(root=str(root),snapshots=catalog))
                    if job.get('status')=='interrupted_recovered':
                        if batch['id'] not in state.setdefault('recovered',[]):
                            state['recovered'].append(batch['id']);save('between_batches')
                        sleep(gap)  # the same settling gap as after any batch
                        continue
                    if not successful(job):
                        # A reviewed invalid batch named in the specification (retained_invalid; e.g. host
                        # interference) is kept as evidence, never rerun, and collection continues.
                        if (batch['id'] in spec.get('retained_invalid', []) and job.get('status') == 'interference_detected'
                                and job.get('cleanup_complete') is True):
                            if batch['id'] not in state.setdefault('retained_invalid', []):
                                state['retained_invalid'].append(batch['id']); save('between_batches')
                            sleep(gap)
                            continue
                        raise RuntimeError('invalid batch retained; no further dispatch')
                    state['completed'].append(batch['id']);save('between_batches')
                sleep(gap)
            save('completed')
        except BaseException as error:
            save('stopped',error=str(error));raise


def serve(out, after):
    """One bounded transfer opportunity; caller retries if measurement owns gate."""
    import tarfile
    out=Path(out)
    with (out/'io.lock').open('a') as gate:
        fcntl.flock(gate,fcntl.LOCK_EX | fcntl.LOCK_NB)
        catalog=read(out/'catalog.json');items=catalog['snapshots']
        if after and after not in [x['id'] for x in items]:raise ValueError('unknown receiver cursor')
        start=0 if not after else [x['id'] for x in items].index(after)+1
        with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as tar:
            tar.add(out/'catalog.json',arcname='catalog.json',recursive=False)
            tar.add(out/'state.json',arcname='state.json',recursive=False)
            for item in items[start:]:
                name=safe_name(item['file']);tar.add(out/'spool'/name,arcname=name,recursive=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec');p.add_argument('--output',required=True)
    p.add_argument('--serve',action='store_true');p.add_argument('--after',default='')
    p.add_argument('--gap-seconds',type=int,default=45)
    p.add_argument('--supersedes',help='previous node specification (reviewed revision; batches must be identical)')
    a=p.parse_args()
    if a.serve:serve(a.output,a.after)
    else:
        if not a.spec or not 0<=a.gap_seconds<=300:p.error('spec and bounded gap required')
        run(read(a.spec),a.output,gap=a.gap_seconds,supersedes=read(a.supersedes) if a.supersedes else None)

if __name__=='__main__':main()
