"""POSIX job launcher with a lock, process-group cleanup and durable status.

Commands must not daemonize/escape their process group. Nested supervisors must
own and terminate their detached workers. This is not a cgroup containment API.
"""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time


def descendants(pid):
    """Every process below pid by parent links, captured while the tree is intact.

    Workers that start their own session (model worker, isolated tool processes)
    leave the child's process group, so a group signal alone cannot reach them.
    """
    listing = subprocess.run(['ps','-A','-o','pid=,ppid='],capture_output=True,text=True,check=True).stdout
    children = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]),[]).append(int(parts[0]))
    found, stack = [], [pid]
    while stack:
        for item in children.get(stack.pop(),[]):
            found.append(item)
            stack.append(item)
    return found


def alive(pid):
    try:
        os.kill(pid,0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    state = subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True).stdout.strip()
    return bool(state) and not state.startswith('Z')


def stop_group(child,grace=20,extra_owned=()):
    """Terminate the child's group, then every descendant seen before the stop.

    Returns the descendant PIDs that are still alive afterwards; an empty list is
    the only evidence of complete cleanup. A process spawned after the snapshot
    and outside the group can be missed; supervisors of detached workers must
    still terminate their own work.
    """
    owned = sorted(set(descendants(child.pid)) | set(extra_owned))
    try:
        os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid,signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=5)
    for pid in owned:
        if alive(pid):
            try:
                os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(alive(pid) for pid in owned):
        time.sleep(0.05)
    for pid in owned:
        if alive(pid):
            try:
                os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(alive(pid) for pid in owned):
        time.sleep(0.05)
    return [pid for pid in owned if alive(pid)]


def cpu_list(text):
    """Linux cpu-list syntax ("8-15,20") -> sorted unique CPU ids."""
    cpus = set()
    for part in text.split(','):
        lo, _, hi = part.strip().partition('-')
        lo, hi = int(lo), int(hi or lo)
        if lo < 0 or hi < lo:
            raise ValueError(f'invalid CPU range: {part!r}')
        cpus.update(range(lo, hi + 1))
    return sorted(cpus)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    p.add_argument('--cwd',required=True)
    p.add_argument('--seconds',type=float,required=True)
    p.add_argument('--cutoff-utc',required=True)
    p.add_argument('--lock',required=True)
    p.add_argument('--grace-seconds',type=float,default=20,help='SIGTERM grace before SIGKILL; model release can take seconds')
    p.add_argument('--process-baseline', help='Reviewed Linux process snapshot; abort on unrelated new processes or background load')
    p.add_argument('--supervisor-cpus', type=cpu_list, metavar='CPULIST',
                   help='Pin this supervisor (and its polling guard) to declared CPUs, away from the measured worker. '
                        'The child inherits them unless it sets its own affinity (moe.run --cpu-affinity).')
    p.add_argument('command',nargs=argparse.REMAINDER)
    a = p.parse_args()
    if os.name != 'posix':
        p.error('requires POSIX')
    if a.supervisor_cpus:
        if not hasattr(os, 'sched_setaffinity'):
            p.error('supervisor CPU affinity is not supported on this platform')
        os.sched_setaffinity(0, a.supervisor_cpus)
        if sorted(os.sched_getaffinity(0)) != a.supervisor_cpus:
            p.error('supervisor CPU affinity was not applied')
    import fcntl
    command = a.command[1:] if a.command[:1] == ['--'] else a.command
    try:
        cutoff = dt.datetime.fromisoformat(a.cutoff_utc.replace('Z','+00:00'))
        if cutoff.utcoffset() != dt.timedelta(0):
            raise ValueError('cutoff must include UTC timezone')
    except ValueError as e:
        p.error(str(e))
    if not command or not math.isfinite(a.seconds) or not 0 < a.seconds <= cutoff.timestamp()-time.time()-60:
        p.error('invalid command/budget or insufficient time before cutoff and cleanup')
    if not math.isfinite(a.grace_seconds) or not 0 < a.grace_seconds <= 300:
        p.error('grace must be within (0, 300] seconds')
    out = Path(a.output)
    out.mkdir(parents=True,exist_ok=False)
    state = dict(command=command,cwd=a.cwd,started_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                 max_seconds=a.seconds,cutoff_utc=a.cutoff_utc,status='starting',supervisor_pid=os.getpid(),cleanup_complete=False,
                 supervisor_cpus=sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None)
    def save():
        tmp = out/'status.tmp'
        tmp.write_text(json.dumps(state,indent=2)+'\n')
        tmp.replace(out/'status.json')
    def interrupted(signum,frame):
        raise InterruptedError(f'supervisor received signal {signum}')
    save()
    child = None
    from .process_guard import ProcessGuard, InterferenceDetected
    guard = None
    previous = {s:signal.signal(s,interrupted) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        with open(a.lock,'a') as lock, (out/'run.log').open('w') as log:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                state.update(status='blocked_by_other_job',returncode=75)
            else:
                try:
                    if a.process_baseline:
                        baseline = json.loads(Path(a.process_baseline).read_text())
                        (out/'process-baseline.json').write_text(json.dumps(baseline, indent=2)+'\n')
                        guard = ProcessGuard(baseline, out/'process-observations.jsonl', os.getpid())
                    child = subprocess.Popen(command,cwd=a.cwd,stdout=log,stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL,start_new_session=True)
                    state.update(status='running',child_pid=child.pid)
                    save()
                    if guard is None:
                        rc = child.wait(timeout=a.seconds)
                    else:
                        deadline = time.monotonic() + a.seconds
                        while child.poll() is None:
                            guard.check()
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise subprocess.TimeoutExpired(command, a.seconds)
                            try:
                                child.wait(timeout=min(0.5, remaining))
                            except subprocess.TimeoutExpired:
                                pass
                        guard.check()
                        rc = child.returncode
                    state.update(status='completed' if rc == 0 else 'failed',returncode=rc)
                finally:
                    if child is not None:
                        survivors = stop_group(child,a.grace_seconds,guard.surviving_owned()) if guard else stop_group(child,a.grace_seconds)
                        state['cleanup_complete'] = not survivors
                        if survivors:
                            state['surviving_pids'] = survivors
    except InterferenceDetected as e:
        state.update(status='interference_detected',returncode=76,error=str(e),measurement_batch_valid=False)
    except subprocess.TimeoutExpired:
        state.update(status='timed_out',returncode=124)
    except InterruptedError as e:
        state.update(status='interrupted',returncode=130,error=str(e))
    except (OSError,ValueError,KeyError,subprocess.SubprocessError) as e:
        state.update(status='failed',returncode=1,error=str(e))
    finally:
        for s,handler in previous.items():
            signal.signal(s,handler)
        if state.get('surviving_pids') and state.get('status') == 'completed':
            state.update(status='failed',returncode=1,error='owned descendants survived cleanup')
        state['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        save()
    return state['returncode']


if __name__ == '__main__':
    raise SystemExit(main())
