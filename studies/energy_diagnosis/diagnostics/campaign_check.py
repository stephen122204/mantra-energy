"""Operator checks on the node. Run only before launch or inside a maintenance window.

    python -m studies.energy_diagnosis.diagnostics.campaign_check preflight --plan plan.json
    python -m studies.energy_diagnosis.diagnostics.campaign_check status --plan plan.json

preflight prints one JSON object of named checks and exits 0 only if every check passes.
status summarizes node_batches state and every finished batch (protocol validity, task outcome).
Neither command changes anything.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .campaign_plan import load


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, **kw)


def cpus(text):
    from .run_bounded import cpu_list
    return cpu_list(text)


def preflight(plan):
    try:
        return _preflight(plan)
    except Exception as exc:  # any unexpected condition is a failed preflight, never a crash
        return dict(passed=False, checks={"preflight_completed": False}, info={"error": f"{type(exc).__name__}: {exc}"})


STOCK_ENGINE_MANIFEST = "stock-engine-build-v1"


def stock_engine_unchanged(manifest, backend_python, *, runner=None):
    """(ok, error) for a stock-engine identity manifest: every listed file still has its sha256 and the backend
    interpreter's `pip freeze` still hashes to the recorded value."""
    runner = runner or run
    for name, digest in manifest["files"].items():
        if not Path(name).is_file() or sha(name) != digest:
            return False, f"changed or missing: {name}"
    freeze = runner([backend_python, "-m", "pip", "freeze"])
    if getattr(freeze, "returncode", 0) != 0:
        return False, "backend pip freeze failed"
    if hashlib.sha256(freeze.stdout.encode()).hexdigest() != manifest["backend_pip_freeze_sha256"]:
        return False, "backend packages changed"
    return True, None


def host_timer_check(plan, checks, info, *, run_timer_wait=None):
    """Chameleon's cache-vendordata timer: either disabled (legacy plans) or named in maintenance.systemd_timer,
    in which case the scheduler avoids it and its actual schedule must be readable now."""
    timer = run(["systemctl", "show", "cache-vendordata.timer", "--property=ActiveState"]).stdout.strip()
    info["vendor_timer"] = timer
    if plan["maintenance"].get("systemd_timer"):
        if run_timer_wait is None:
            from .batch_coordinator import timer_wait as run_timer_wait
        try:
            run_timer_wait(dict(minimum_batch_seconds=0, maintenance=plan["maintenance"]))
            checks["host_maintenance_timer_schedulable"] = True
        except Exception as exc:
            checks["host_maintenance_timer_schedulable"] = False
            info["host_timer_error"] = f"{type(exc).__name__}: {exc}"
    else:
        checks["vendor_cache_timer_inactive"] = timer in ("ActiveState=inactive", "")


def _preflight(plan):
    exp, node, host = plan["expected"], plan["node"], plan["host_condition"]
    checks, info = {}, {}
    repo = Path(node["remote_repository"])
    checks["repository_present"] = repo.is_dir()
    if not checks["repository_present"]:
        # Nothing else can be checked meaningfully without the frozen checkout.
        return dict(passed=False, checks=checks, info=dict(missing=str(repo)))
    head = run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()
    checks["repository_revision"] = head == exp["repository_revision"]
    checks["repository_clean"] = run(["git", "-C", str(repo), "status", "--porcelain"]).stdout.strip() == ""
    checks["build_manifest"] = sha(exp["build_manifest"]) == exp["build_manifest_sha256"]
    manifest = json.loads(Path(exp["build_manifest"]).read_text())
    if manifest.get("kind") == STOCK_ENGINE_MANIFEST:
        # Stock engines (llama.cpp): no MoE-Infinity native build; identity = hashed engine binary, configs,
        # model preflight identities, wrapper, plus the backend interpreter's installed packages.
        ok, error = stock_engine_unchanged(manifest, exp["backend_python"])
        checks["backend_dependencies_unchanged"] = ok
        info["backend_verify_error"] = error
    else:
        verify = run([exp["backend_python"], "-c", "import sys; from pathlib import Path; "
                      "from studies.energy_diagnosis.moe.prepare import verify_build; "
                      "print(verify_build(Path(sys.argv[1]))['manifest_sha256'])", exp["build_manifest"]],
                     cwd=repo, env=dict(os.environ, PYTHONPATH=str(repo)))
        checks["backend_dependencies_unchanged"] = verify.returncode == 0 and verify.stdout.strip() == exp["build_manifest_sha256"]
        info["backend_verify_error"] = verify.stderr.strip()[-300:] if verify.returncode else None
    checks["model_weights_manifest"] = sha(exp["weights_manifest"]) == exp["weights_manifest_sha256"]
    freeze = run([exp["tool_python"], "-m", "pip", "freeze"]).stdout
    checks["tool_environment"] = hashlib.sha256(freeze.encode()).hexdigest() == exp["tool_python_freeze_sha256"]
    checks["networkx_source"] = run(["git", "-C", exp["networkx_source"], "rev-parse", "HEAD"]).stdout.strip() == exp["networkx_commit"] \
        and run(["git", "-C", exp["networkx_source"], "status", "--porcelain"]).stdout.strip() == ""
    online = set(cpus(Path("/sys/devices/system/cpu/online").read_text().strip()))
    declared = {k: cpus(host[k]) if host[k] else [] for k in ("cpu_affinity", "keep_awake_cpus", "tool_cpus", "supervisor_cpus")}
    checks["declared_cpus_online"] = all(set(v) <= online for v in declared.values())
    sets = list(declared.values())
    checks["declared_cpu_sets_disjoint"] = all(not (set(a) & set(b)) for i, a in enumerate(sets) for b in sets[i + 1:])
    from studies.energy_diagnosis.moe.run import cpu_power_state
    power = cpu_power_state(sorted(set(declared["cpu_affinity"]) | set(declared["keep_awake_cpus"])))
    info["cpu_power"] = power
    checks["cpu_power_as_frozen"] = power == exp["cpu_power"]
    rapl = sorted(Path("/sys/class/powercap").glob("intel-rapl:[0-9]"))
    checks["rapl_packages_readable"] = bool(rapl) and all(os.access(p / "energy_uj", os.R_OK) for p in rapl)
    smi = run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"])
    used = [int(x.split(",")[0]) for x in smi.stdout.strip().splitlines()] if smi.returncode == 0 else []
    checks["gpu_idle"] = smi.returncode == 0 and bool(used) and max(used) < 1024
    host_timer_check(plan, checks, info)
    target = Path(node["remote_directory"])
    while not target.exists():
        target = target.parent  # measure the filesystem that will hold the results
    free = shutil.disk_usage(target).free
    checks["disk_free"] = free >= exp["min_free_gib"] * 2**30
    info["disk_free_gib"] = round(free / 2**30, 1)
    import fcntl
    with open(node["lock"], "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
            checks["gpu_lock_free"] = True
        except BlockingIOError:
            checks["gpu_lock_free"] = False
    users = {line.split()[0] for line in run(["who"]).stdout.splitlines() if line.strip()}
    info["logged_in_users"] = sorted(users)
    checks["no_other_users_logged_in"] = users <= {"cc"}
    from .campaign_plan import node_spec
    batches = len(node_spec(plan)["batches"])
    lease = dt.datetime.fromisoformat(exp["lease_end_utc"].replace("Z", "+00:00"))
    needed = dt.timedelta(seconds=batches * plan["estimated_batch_seconds"] * plan["maintenance"]["period_seconds"]
                          / (plan["maintenance"]["period_seconds"] - plan["maintenance"]["window_seconds"]))
    info["estimated_end_utc"] = (dt.datetime.now(dt.timezone.utc) + needed).isoformat()
    checks["lease_covers_campaign_plus_12h"] = dt.datetime.now(dt.timezone.utc) + needed + dt.timedelta(hours=12) <= lease
    cutoff = dt.datetime.fromisoformat(plan["cutoff_utc"].replace("Z", "+00:00"))
    checks["cutoff_before_lease_end"] = cutoff <= lease - dt.timedelta(hours=6)
    return dict(passed=all(checks.values()), checks=checks, info=info)


def status(plan):
    node = plan["node"]
    control = Path(node["node_output"])
    state = json.loads((control / "state.json").read_text()) if (control / "state.json").exists() else None
    rows = []
    root = Path(node["remote_directory"])
    for batch in sorted(p for p in root.iterdir() if (p / "batch.json").exists()) if root.exists() else []:
        job = json.loads((batch / "job/status.json").read_text()) if (batch / "job/status.json").exists() else {}
        acc = json.loads((batch / "acceptance.json").read_text()) if (batch / "acceptance.json").exists() else {}
        rows.append(dict(id=batch.name, job=job.get("status"), returncode=job.get("returncode"),
                         protocol_valid=acc.get("protocol_valid"), outcome=acc.get("outcome"),
                         recovered=(batch / "recovery.json").exists()))
    from .campaign_plan import node_spec
    total = len(node_spec(plan)["batches"])
    return dict(node_state=state, batches_total=total, batches_finished=len(rows),
                protocol_invalid=[r["id"] for r in rows if r["protocol_valid"] is False],
                needs_recovery=[r["id"] for r in rows if r["job"] not in TERMINAL and not r["recovered"]],
                recovered=[r["id"] for r in rows if r["recovered"]], batches=rows)


TERMINAL = {"completed", "failed", "timed_out", "interrupted", "interference_detected", "blocked_by_other_job"}


def _cmdline(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return None


def recover(plan, batch_id, proc=Path("/proc"), gpu_apps=None):
    """Classify one interrupted (non-terminal) batch after verifying nothing of it is still running.

    Never edits or deletes the batch's own records; writes <batch>/recovery.json exclusively. The
    scheduler then retains the batch as an interrupted, invalid attempt and continues; it is never
    rerun. Returns (ok, record_or_reasons)."""
    node = plan["node"]
    batch = Path(node["remote_directory"]) / batch_id
    status_path = batch / "job" / "status.json"
    reasons = []
    if "/" in batch_id or not batch.is_dir():
        return False, ["no such batch directory"]
    if (batch / "recovery.json").exists():
        return False, ["batch already has a recovery record; it is never overwritten"]
    status = json.loads(status_path.read_text()) if status_path.exists() else {"status": "missing"}
    if status.get("status") in TERMINAL:
        return False, [f"batch is terminal ({status.get('status')}); nothing to recover"]
    for key in ("supervisor_pid", "child_pid"):
        pid = status.get(key)
        line = _cmdline(pid) if pid else None
        if line is not None and str(batch) in line:
            reasons.append(f"{key} {pid} is still running")
    id_arg = f"--id {batch_id} "
    for entry in proc.iterdir():
        if entry.name.isdigit():
            line = _cmdline(entry.name)
            if line and int(entry.name) != os.getpid() and (str(batch) in line or id_arg in line + " "):
                reasons.append(f"process {entry.name} still references the batch")
    import fcntl
    lock_path = batch / "active.lock"
    if lock_path.exists():
        with open(lock_path, "a") as active:
            try:
                fcntl.flock(active, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(active, fcntl.LOCK_UN)
            except BlockingIOError:
                reasons.append("the batch's active lock is still held by one of its processes")
    if gpu_apps is None:
        smi = run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"])
        gpu_apps = [x.strip() for x in smi.stdout.splitlines() if x.strip()] if smi.returncode == 0 else ["nvidia-smi failed"]
    if gpu_apps:
        reasons.append(f"GPU compute processes present: {gpu_apps}")
    import fcntl
    with open(node["lock"], "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
        except BlockingIOError:
            reasons.append("GPU lock is held")
    if reasons:
        return False, reasons
    files = [dict(path=str(p.relative_to(batch)), bytes=p.stat().st_size, sha256=sha(p))
             for p in sorted(batch.rglob("*")) if p.is_file()]
    status_bytes = status_path.read_bytes() if status_path.exists() else b"missing"
    record = dict(status="interrupted", batch=batch_id, job_status_seen=status.get("status"),
                  status_sha256=hashlib.sha256(status_bytes).hexdigest(),
                  classified_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  checks=["supervisor/child pids not running", "no process references the batch",
                          "batch active lock free", "no GPU compute process", "GPU lock free"],
                  partial_artifacts=files)
    with (batch / "recovery.json").open("x") as stream:
        json.dump(record, stream, indent=2)
    return True, record


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["preflight", "status", "recover"])
    p.add_argument("--plan", required=True)
    p.add_argument("--batch", help="recover: the interrupted batch id reported by status")
    a = p.parse_args(argv)
    plan = load(a.plan)
    if a.command == "recover":
        if not a.batch:
            p.error("recover needs --batch")
        ok, detail = recover(plan, a.batch)
        print(json.dumps(dict(recovered=ok, detail=detail), indent=2))
        return 0 if ok else 1
    result = preflight(plan) if a.command == "preflight" else status(plan)
    print(json.dumps(result, indent=2))
    return 0 if a.command == "status" or result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
