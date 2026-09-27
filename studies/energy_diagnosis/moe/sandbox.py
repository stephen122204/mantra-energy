"""Run submitted Python inside a kernel-enforced sandbox (Linux Landlock) with resource limits.

The child is ``python -I -S`` reading one JSON job on stdin. Before any submitted code runs it:
  * reads the whole job (source, entry point, inputs, optional example statement) into memory;
  * sets no-new-privileges and a Landlock ruleset that allows only READ_FILE/READ_DIR beneath the Python
    standard-library directories: no other file can be read, nothing can be written, created, removed or
    executed anywhere (execve is denied, so no subprocesses of any program), /proc is unreadable (no inspection
    of other processes) and, where the kernel supports it (Landlock ABI >= 4), TCP bind/connect are denied;
  * sets RLIMIT_AS, RLIMIT_CPU, RLIMIT_FSIZE=0 and RLIMIT_NPROC=0 (no fork).
Results go back as one JSON line on stdout. Expected outputs are never given to the child; comparison happens in
the calling (grader) process. If Landlock is unavailable the job is refused (``require_landlock=True``) rather
than run without the boundary; tests on non-Linux hosts pass ``require_landlock=False`` explicitly.
"""
import json
import os
import subprocess
import sys
import sysconfig

CHILD = r'''
import json, sys, time
job = json.loads(sys.stdin.read())

def _landlock(paths):
    import ctypes, os
    libc = ctypes.CDLL(None, use_errno=True)
    SYS_CREATE, SYS_ADD, SYS_RESTRICT = 444, 445, 446  # x86_64 and aarch64 share these numbers
    abi = libc.syscall(SYS_CREATE, None, ctypes.c_size_t(0), ctypes.c_uint32(1))
    if abi < 1:
        return 0
    fs = (1 << 13) - 1                      # ABI 1: execute .. make_sym
    if abi >= 2: fs |= 1 << 13              # refer
    if abi >= 3: fs |= 1 << 14              # truncate
    if abi >= 5: fs |= 1 << 15              # ioctl_dev
    net = 3 if abi >= 4 else 0              # bind_tcp | connect_tcp
    class Attr(ctypes.Structure):
        _fields_ = [("fs", ctypes.c_uint64), ("net", ctypes.c_uint64)]
    class Beneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed", ctypes.c_uint64), ("fd", ctypes.c_int32)]
    attr = Attr(fs, net)
    size = ctypes.sizeof(Attr) if abi >= 4 else 8
    rfd = libc.syscall(SYS_CREATE, ctypes.byref(attr), ctypes.c_size_t(size), ctypes.c_uint32(0))
    if rfd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset")
    READ = (1 << 2) | (1 << 3)              # read_file | read_dir
    for path in paths:
        pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        rule = Beneath(READ, pfd)
        if libc.syscall(SYS_ADD, rfd, ctypes.c_int(1), ctypes.byref(rule), ctypes.c_uint32(0)) != 0:
            raise OSError(ctypes.get_errno(), "landlock_add_rule")
        os.close(pfd)
    if libc.prctl(38, 1, 0, 0, 0) != 0:     # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), "no_new_privs")
    if libc.syscall(SYS_RESTRICT, rfd, ctypes.c_uint32(0)) != 0:
        raise OSError(ctypes.get_errno(), "landlock_restrict_self")
    os.close(rfd)
    return abi

abi = 0
if sys.platform.startswith("linux"):
    abi = _landlock(job["read_paths"])
if job["require_landlock"] and abi < 1:
    print(json.dumps(dict(status="refused", error="landlock unavailable"))); sys.exit(3)
try:
    import resource
    for lim, val in ((resource.RLIMIT_AS, job["memory_bytes"]), (resource.RLIMIT_CPU, job["cpu_seconds"]),
                     (resource.RLIMIT_FSIZE, 0), (resource.RLIMIT_NPROC, 0)):
        try:
            resource.setrlimit(lim, (val, val))
        except (ValueError, OSError):
            pass
except ImportError:
    pass

def enc(x):
    if isinstance(x, (set, frozenset)): return {"__set__": sorted((enc(v) for v in x), key=repr)}
    if isinstance(x, tuple): return {"__tuple__": [enc(v) for v in x]}
    if isinstance(x, list): return [enc(v) for v in x]
    if isinstance(x, dict): return {"__dict__": sorted(([enc(k), enc(v)] for k, v in x.items()), key=repr)}
    if isinstance(x, float) and x != x: return {"__nan__": True}
    return x

out = dict(status="ok", landlock_abi=abi)
try:
    g = {"__name__": "solution"}
    exec(compile(job["source"], "solution.py", "exec"), g)
    if job.get("example"):
        exec(compile(job["example"], "example_check", "exec"), g)
        out["example"] = "passed"
    if job.get("inputs") is not None:
        fn = g[job["entry"]]
        results = []
        t0 = time.perf_counter()
        for args in job["inputs"]:
            results.append(enc(fn(*args)))
        out.update(seconds=time.perf_counter() - t0, outputs=results)
except AssertionError as exc:
    out = dict(status="example_failed", error=("AssertionError: " + str(exc))[-1500:], landlock_abi=abi)
except BaseException as exc:
    out = dict(status="error", error=(type(exc).__name__ + ": " + str(exc))[-1500:], landlock_abi=abi)
sys.stdout.write("\n" + json.dumps(out) + "\n")
sys.stdout.flush()
'''


def stdlib_paths():
    paths = {sysconfig.get_path("stdlib"), sysconfig.get_path("platstdlib")}
    dyn = os.path.join(sysconfig.get_path("platstdlib"), "lib-dynload")
    if os.path.isdir(dyn):
        paths.add(dyn)
    return sorted(p for p in paths if p and os.path.isdir(p))


def run(source, entry, inputs, seconds, *, example=None, memory_bytes=8 << 30, require_landlock=True, cwd=None):
    """Returns (status, payload). status: ok, timeout, error, example_failed, refused."""
    job = dict(source=source, entry=entry, inputs=inputs, example=example, memory_bytes=int(memory_bytes),
               cpu_seconds=int(seconds) + 5, read_paths=stdlib_paths(), require_landlock=require_landlock)
    try:
        p = subprocess.run([sys.executable, "-I", "-S", "-c", CHILD], input=json.dumps(job), text=True,
                           capture_output=True, timeout=seconds, cwd=cwd or "/",
                           env=dict(PATH="/usr/bin:/bin", PYTHONHASHSEED="0", LANG="C.UTF-8"))
    except subprocess.TimeoutExpired:
        return "timeout", None
    lines = [l for l in p.stdout.splitlines() if l.strip()]
    try:
        payload = json.loads(lines[-1])
    except (ValueError, IndexError):
        return "error", dict(error=(p.stderr or "no result")[-1500:], returncode=p.returncode)
    if not isinstance(payload, dict) or payload.get("status") not in {"ok", "error", "example_failed", "refused"}:
        return "error", dict(error="malformed result")
    return payload["status"], payload
