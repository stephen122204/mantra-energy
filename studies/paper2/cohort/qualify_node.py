#!/usr/bin/env python3
"""Record what the node actually is and which measurement paths work. Read-only.

Usage: python3 qualify_node.py --out node_report.json [--cutoff-utc 2026-10-24T17:05:00Z]

Checks: host/kernel/boot id, CPU model + governor + idle driver, memory, disk free under the
work dir, every GPU (name, UUID, VRAM, driver, NVML total-energy counter advancing), RAPL
package domains (readable, advancing, max range), docker, python and CUDA toolkit versions,
time left before the reservation cutoff. Nothing is installed or changed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path


def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"rc": p.returncode, "out": p.stdout.strip()[-4000:], "err": p.stderr.strip()[-1000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"rc": None, "error": f"{type(exc).__name__}: {exc}"}


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError as exc:
        return f"unreadable: {exc.__class__.__name__}"


def rapl_domains(wait_s=1.0):
    root = Path("/sys/class/powercap")
    found = {}
    for p in sorted(root.glob("intel-rapl:*")) + sorted(root.glob("intel-rapl:*:*")):
        name = read(p / "name")
        e0 = read(p / "energy_uj")
        found[p.name] = {"name": name, "readable": e0.isdigit(), "max_energy_range_uj": read(p / "max_energy_range_uj")}
        found[p.name]["_e0"] = e0
    time.sleep(wait_s)
    for k, v in found.items():
        e1 = read(root / k / "energy_uj")
        e0 = v.pop("_e0")
        v["advancing"] = e0.isdigit() and e1.isdigit() and int(e1) != int(e0)
        if e0.isdigit() and e1.isdigit():
            v["approx_power_w"] = round((int(e1) - int(e0)) / 1e6 / wait_s, 1)
    return found


def gpus(wait_s=1.0):
    try:
        import pynvml
    except ImportError:
        return {"status": "pynvml not installed"}
    out = []
    pynvml.nvmlInit()
    try:
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            dec = lambda x: x.decode() if isinstance(x, bytes) else x
            rec = {"index": i, "name": dec(pynvml.nvmlDeviceGetName(h)), "uuid": dec(pynvml.nvmlDeviceGetUUID(h)),
                   "vram_gib": round(pynvml.nvmlDeviceGetMemoryInfo(h).total / 2**30, 2),
                   "pci": dec(pynvml.nvmlDeviceGetPciInfo(h).busId),
                   "compute_procs": len(pynvml.nvmlDeviceGetComputeRunningProcesses(h))}
            try:
                e0 = pynvml.nvmlDeviceGetTotalEnergyConsumption(h)
                time.sleep(wait_s)
                e1 = pynvml.nvmlDeviceGetTotalEnergyConsumption(h)
                rec["energy_counter"] = {"advancing": e1 > e0, "approx_power_w": round((e1 - e0) / 1e3 / wait_s, 1)}
            except pynvml.NVMLError as exc:
                rec["energy_counter"] = {"error": str(exc)}
            try:
                rec["power_limit_w"] = pynvml.nvmlDeviceGetPowerManagementLimit(h) / 1000
            except pynvml.NVMLError:
                pass
            out.append(rec)
        return {"driver": pynvml.nvmlSystemGetDriverVersion(), "devices": out}
    finally:
        pynvml.nvmlShutdown()


def landlock_abi():
    """Landlock ABI version (landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)); task sandbox needs >= 4."""
    import ctypes
    try:
        return int(ctypes.CDLL(None, use_errno=True).syscall(444, None, 0, 1))
    except Exception:
        return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--work-dir", default=str(Path.home()))
    ap.add_argument("--cutoff-utc", default=None, help="reservation end, ISO 8601 UTC")
    a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    report = {
        "checked_utc": now.isoformat(timespec="seconds"),
        "host": platform.node(), "kernel": platform.release(), "boot_id": read("/proc/sys/kernel/random/boot_id"),
        "os_release": read("/etc/os-release").splitlines()[:4],
        "cpu": {"lscpu": run(["lscpu"])["out"] if shutil.which("lscpu") else None,
                "governor": read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
                "idle_driver": read("/sys/devices/system/cpu/cpuidle/current_driver")},
        "memory_gib": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1),
        "disk": {p: {"free_gib": round(shutil.disk_usage(p).free / 2**30, 1), "total_gib": round(shutil.disk_usage(p).total / 2**30, 1)}
                 for p in {a.work_dir, "/"} if os.path.exists(p)},
        "gpus": gpus(),
        "rapl": rapl_domains(),
        "software": {"python": platform.python_version(), "nvidia_smi": run(["nvidia-smi", "--version"]).get("out"),
                     "nvcc": run(["nvcc", "--version"]).get("out", "")[-200:] if shutil.which("nvcc") else None,
                     "docker": run(["docker", "version", "--format", "{{.Server.Version}}"]) if shutil.which("docker") else None,
                     "git": run(["git", "--version"]).get("out")},
        "landlock_abi": landlock_abi(),
        "other_users_procs": run(["bash", "-c", "ps -eo user= | sort | uniq -c"])["out"],
    }
    if a.cutoff_utc:
        cutoff = dt.datetime.fromisoformat(a.cutoff_utc.replace("Z", "+00:00"))
        report["hours_to_cutoff"] = round((cutoff - now).total_seconds() / 3600, 2)
    pkg = [v for v in report["rapl"].values() if str(v.get("name", "")).startswith("package")]
    lscpu = report["cpu"].get("lscpu") or ""
    field = lambda k: next((l.split(":", 1)[1].strip() for l in lscpu.splitlines() if l.startswith(k + ":")), None)
    sockets = field("Socket(s)")
    report["cpu"].update(sockets=int(sockets) if sockets and sockets.isdigit() else None, model=field("Model name"),
                         package_domains=len(pkg))
    gpu_ok = isinstance(report["gpus"], dict) and any(d.get("energy_counter", {}).get("advancing") for d in report["gpus"].get("devices", []))
    # every physical package must be covered, not merely one readable domain
    report["verdict"] = {"cpu_package_counters": bool(pkg) and all(v["readable"] and v["advancing"] for v in pkg)
                         and report["cpu"]["sockets"] is not None and len(pkg) == report["cpu"]["sockets"],
                         "gpu_energy_counter": gpu_ok,
                         "task_sandbox_landlock_abi4": report["landlock_abi"] >= 4}
    Path(a.out).write_text(json.dumps(report, indent=1))
    print(json.dumps(report["verdict"]))


if __name__ == "__main__":
    main()
