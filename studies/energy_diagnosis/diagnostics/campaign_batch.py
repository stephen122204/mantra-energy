"""One campaign batch = one guarded goal with the frozen start-state protocol.

Used as the argv of a node_batches batch. Steps: refuse an existing batch directory (no
silent reruns), warm the host page cache for the declared model/offload paths, snapshot
idle-state and frequency counters for the declared CPUs, run run_bounded with a captured
process baseline and declared supervisor CPUs around `moe.run ... --output <batch>/campaign`,
snapshot the counters again, and write the protocol-only acceptance audit. Exit status:
run_bounded's return code if it failed; 6 if the goal ran but protocol validity failed
(node_batches then stops for review); otherwise 0. Task failures never change the exit status.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def idle_snapshot(cpus, root=Path("/sys/devices/system/cpu")):
    out = {}
    for cpu in cpus:
        base = root / f"cpu{cpu}"
        states = {}
        for state in sorted((base / "cpuidle").glob("state*")):
            states[(state / "name").read_text().strip()] = dict(
                usage=int((state / "usage").read_text()), time_us=int((state / "time").read_text()))
        freq = base / "cpufreq/scaling_cur_freq"
        out[str(cpu)] = dict(idle=states, cur_khz=int(freq.read_text()) if freq.exists() else None)
    return dict(monotonic_ns=time.monotonic_ns(), cpus=out)


def warm(paths, chunk=16 * 2**20):
    started, total = time.monotonic(), 0
    for root in paths:
        for path in sorted(Path(root).rglob("*")):
            if path.is_file():
                with path.open("rb") as stream:
                    while block := stream.read(chunk):
                        total += len(block)
    return dict(paths=list(map(str, paths)), bytes=total, seconds=round(time.monotonic() - started, 3))


def meminfo():
    try:
        rows = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        return {k: rows[k].strip() for k in ("MemAvailable", "Cached") if k in rows}
    except OSError:
        return None


def main(argv=None):
    from .run_bounded import cpu_list
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True, help="Campaign result root (node_batches remote_directory)")
    p.add_argument("--id", required=True)
    p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--cutoff-utc", required=True)
    p.add_argument("--lock", required=True)
    p.add_argument("--supervisor-cpus", required=True)
    p.add_argument("--warm", action="append", default=[])
    p.add_argument("--idle-cpus", type=cpu_list, default=[])
    p.add_argument("--required-domain", action="append", default=[])
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not command or "--output" in command or "/" in a.id:
        p.error("give the moe.run argv without --output, and a one-component batch id")
    out = Path(a.root) / a.id
    out.mkdir(parents=True, exist_ok=False)  # an existing batch is never silently repeated
    import fcntl
    # Held for the batch's whole life and inherited by the supervisor (pass_fds): recovery can
    # only classify this batch once no process of it holds the lock.
    active = open(out / "active.lock", "w")
    fcntl.flock(active, fcntl.LOCK_EX | fcntl.LOCK_NB)
    record = dict(id=a.id, started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), command=command)
    record["meminfo_before_warm"] = meminfo()
    record["warm"] = warm(a.warm)
    record["meminfo_after_warm"] = meminfo()
    (out / "idle-before.json").write_text(json.dumps(idle_snapshot(a.idle_cpus)))
    bounded = [sys.executable, "-m", "studies.energy_diagnosis.diagnostics.run_bounded", "--output", str(out / "job"),
               "--cwd", str(Path.cwd()), "--seconds", str(a.seconds), "--cutoff-utc", a.cutoff_utc, "--lock", a.lock,
               "--capture-process-baseline", "--supervisor-cpus", a.supervisor_cpus, "--",
               *command, "--output", str(out / "campaign")]
    record["run_bounded_argv"] = bounded
    (out / "batch.json").write_text(json.dumps(record, indent=2) + "\n")
    rc = subprocess.run(bounded, stdin=subprocess.DEVNULL, pass_fds=(active.fileno(),)).returncode
    (out / "idle-after.json").write_text(json.dumps(idle_snapshot(a.idle_cpus)))
    from studies.energy_diagnosis.moe.audit_pilot import audit
    result = audit(out, prefix_mode="exact_prefix", required_domains=a.required_domain, require_timing=True)
    (out / "acceptance.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if rc:
        return rc
    return 0 if result["protocol_valid"] else 6


if __name__ == "__main__":
    raise SystemExit(main())
