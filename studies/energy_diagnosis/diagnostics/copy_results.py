"""Copy an explicit result directory over verified SSH, then verify file hashes.

Run on the receiving computer. It must stay awake and connected. Never point
--remote-directory at a home directory, model cache, credentials or repository.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import time


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def verify(destination,hashes):
    root = Path(destination).resolve()
    mismatches = []
    for name,expected in hashes.items():
        rel = PurePosixPath(name)
        if rel.is_absolute() or '..' in rel.parts or '\\' in name:
            raise ValueError('unsafe manifest path')
        target = root.joinpath(*rel.parts)
        if not target.resolve().is_relative_to(root):
            raise ValueError('manifest path escapes destination')
        if target.is_symlink() or not target.is_file() or digest(target) != expected:
            mismatches.append(name)
    return mismatches



def ssh_arguments(identity_file, known_hosts):
    # OpenSSH parses -o values again, even when subprocess receives an argv list.
    # Quote the single filename inside that option, not only at the shell layer.
    path = str(Path(known_hosts).expanduser().resolve())
    if any(c in path for c in ('\n', '\r', '\x00')):
        raise ValueError('invalid known-hosts filename')
    quoted = '"' + path.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return ['ssh', '-i', identity_file, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + quoted]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',required=True,help='verified user@host for the current lease')
    p.add_argument('--identity-file',required=True)
    p.add_argument('--known-hosts',required=True)
    p.add_argument('--remote-directory',required=True,help='dedicated result directory only')
    p.add_argument('--remote-status',required=True,help='status JSON relative to result directory')
    p.add_argument('--destination',required=True,help='new local directory for this copy job')
    p.add_argument('--cutoff-utc',required=True)
    p.add_argument('--interval',type=int,default=60)
    a = p.parse_args()
    remote = PurePosixPath(a.remote_directory)
    status = PurePosixPath(a.remote_status)
    if (not remote.is_absolute() or len(remote.parts)<4 or '..' in remote.parts or
            status.is_absolute() or '..' in status.parts or a.host.startswith('-') or
            any(c.isspace() for c in a.host) or a.interval<1):
        p.error('invalid host, directory, status path or interval')
    cutoff = dt.datetime.fromisoformat(a.cutoff_utc.replace('Z','+00:00'))
    if cutoff.utcoffset() != dt.timedelta(0) or cutoff.timestamp() <= time.time():
        p.error('cutoff must be a future UTC timestamp')
    root = Path(a.destination).resolve()
    root.mkdir(parents=True,exist_ok=False)
    dest = root/'artifacts'
    dest.mkdir()
    ssh = ssh_arguments(a.identity_file, a.known_hosts)
    def write(report):
        tmp = root/'status.tmp'
        tmp.write_text(json.dumps(report,indent=2)+'\n')
        tmp.replace(root/'status.json')
    def run(args,timeout=60):
        return subprocess.run(args,check=True,text=True,capture_output=True,timeout=timeout).stdout
    def copy():
        # No delete and no symlink following. Use a private, explicit result root.
        run(['rsync','-rltz','--protect-args','-e',shlex.join(ssh),'--',
             a.host+':'+str(remote)+'/',str(dest)+'/'],180)
    code = '''import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]); result={}
for f in root.rglob('*'):
 if f.is_symlink(): raise ValueError('symlinks are not result files')
 if f.is_file():
  h=hashlib.sha256()
  with f.open('rb') as stream:
   for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
  result[str(f.relative_to(root))]=h.hexdigest()
print(json.dumps(result))'''
    terminal = {'completed','failed','timed_out','interrupted','blocked_by_other_job','interference_detected'}
    while time.time() < cutoff.timestamp():
        try:
            state = json.loads(run(ssh+[a.host,'cat '+shlex.quote(str(remote/status))]))
            copy()
            if state['status'] in terminal:
                hashes = json.loads(run(ssh+[a.host,'python3 -c '+shlex.quote(code)+' '+shlex.quote(str(remote))],180))
                copy()
                mismatches = verify(dest,hashes)
                (root/'remote-file-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
                report = dict(status='copy_hash_mismatch' if mismatches else 'copied_and_verified',
                              remote_job=state,files=len(hashes),mismatches=mismatches)
                write(report)
                print(json.dumps(report),flush=True)
                return 1 if mismatches else 0
            if state['status'] not in {'starting','running'}:
                raise ValueError('unrecognized remote job status')
            write(dict(status='waiting_for_remote_job',remote_job=state,last_copy_utc=dt.datetime.now(dt.timezone.utc).isoformat()))
        except (OSError,subprocess.SubprocessError,ValueError,KeyError) as e:
            write(dict(status='retrying',error=str(e)))
        time.sleep(min(a.interval,max(0,cutoff.timestamp()-time.time())))
    write(dict(status='cutoff_reached',note='latest copy retained; final verification did not complete'))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
