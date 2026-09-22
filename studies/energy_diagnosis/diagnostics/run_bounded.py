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


def stop_group(child):
    try:
        os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(child.pid,signal.SIGKILL)
    except ProcessLookupError:
        pass
    child.wait(timeout=5)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    p.add_argument('--cwd',required=True)
    p.add_argument('--seconds',type=float,required=True)
    p.add_argument('--cutoff-utc',required=True)
    p.add_argument('--lock',required=True)
    p.add_argument('command',nargs=argparse.REMAINDER)
    a = p.parse_args()
    if os.name != 'posix':
        p.error('requires POSIX')
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
    out = Path(a.output)
    out.mkdir(parents=True,exist_ok=False)
    state = dict(command=command,cwd=a.cwd,started_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                 max_seconds=a.seconds,cutoff_utc=a.cutoff_utc,status='starting',supervisor_pid=os.getpid(),cleanup_complete=False)
    def save():
        tmp = out/'status.tmp'
        tmp.write_text(json.dumps(state,indent=2)+'\n')
        tmp.replace(out/'status.json')
    def interrupted(signum,frame):
        raise InterruptedError(f'supervisor received signal {signum}')
    save()
    child = None
    previous = {s:signal.signal(s,interrupted) for s in (signal.SIGTERM,signal.SIGINT)}
    try:
        with open(a.lock,'a') as lock, (out/'run.log').open('w') as log:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                state.update(status='blocked_by_other_job',returncode=75)
            else:
                try:
                    child = subprocess.Popen(command,cwd=a.cwd,stdout=log,stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL,start_new_session=True)
                    state.update(status='running',child_pid=child.pid)
                    save()
                    rc = child.wait(timeout=a.seconds)
                    state.update(status='completed' if rc == 0 else 'failed',returncode=rc)
                finally:
                    if child is not None:
                        stop_group(child)
                        state['cleanup_complete'] = True
    except subprocess.TimeoutExpired:
        state.update(status='timed_out',returncode=124)
    except InterruptedError as e:
        state.update(status='interrupted',returncode=130,error=str(e))
    except (OSError,subprocess.SubprocessError) as e:
        state.update(status='failed',returncode=1,error=str(e))
    finally:
        for s,handler in previous.items():
            signal.signal(s,handler)
        state['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        save()
    return state['returncode']


if __name__ == '__main__':
    raise SystemExit(main())
