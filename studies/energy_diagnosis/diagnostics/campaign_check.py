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
    exp, node, host = plan["expected"], plan["node"], plan["host_condition"]
    checks, info = {}, {}
    repo = Path(node["remote_repository"])
    head = run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()
    checks["repository_revision"] = head == exp["repository_revision"]
    checks["repository_clean"] = run(["git", "-C", str(repo), "status", "--porcelain"]).stdout.strip() == ""
    checks["build_manifest"] = sha(exp["build_manifest"]) == exp["build_manifest_sha256"]
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
    declared = {k: cpus(host[k]) for k in ("cpu_affinity", "keep_awake_cpus", "tool_cpus", "supervisor_cpus")}
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
    timer = run(["systemctl", "show", "cache-vendordata.timer", "--property=ActiveState"]).stdout.strip()
    info["vendor_timer"] = timer
    checks["vendor_cache_timer_inactive"] = timer in ("ActiveState=inactive", "")
    free = shutil.disk_usage(node["remote_directory"] if Path(node["remote_directory"]).exists() else Path(node["remote_directory"]).parent).free
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
                         protocol_valid=acc.get("protocol_valid"), outcome=acc.get("outcome")))
    from .campaign_plan import node_spec
    total = len(node_spec(plan)["batches"])
    return dict(node_state=state, batches_total=total, batches_finished=len(rows),
                protocol_invalid=[r["id"] for r in rows if r["protocol_valid"] is False], batches=rows)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["preflight", "status"])
    p.add_argument("--plan", required=True)
    a = p.parse_args(argv)
    plan = load(a.plan)
    result = preflight(plan) if a.command == "preflight" else status(plan)
    print(json.dumps(result, indent=2))
    return 0 if a.command == "status" or result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
