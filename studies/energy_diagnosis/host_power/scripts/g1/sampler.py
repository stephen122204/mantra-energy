"""Energy/utilisation sampler (pinned by the caller to a CPU away from 64-79; no subprocesses, so it is safe
under the ALEMS process guard when started before a guarded stage).

    taskset -c 30 python sampler.py OUT.jsonl [--period 0.2] [--cpus 64-79,192-207]

Every period: CLOCK_MONOTONIC ns, RAPL package energy_uj for intel-rapl:0 and :1, NVML total energy (mJ),
NVML GPU utilisation and power. Every 5th sample also: scaling_cur_freq of --cpus. Wraparound is handled in the
analysis (cumulative, using max_energy_range_uj recorded in the header). Stops on SIGTERM.
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

try:
    import pynvml
except ImportError:
    pynvml = None

out = Path(sys.argv[1])
period = float(sys.argv[sys.argv.index("--period") + 1]) if "--period" in sys.argv else 0.2
cpus = []
if "--cpus" in sys.argv:
    for part in sys.argv[sys.argv.index("--cpus") + 1].split(","):
        a, _, b = part.partition("-")
        cpus += list(range(int(a), int(b or a) + 1))

ZONES = [Path(f"/sys/class/powercap/intel-rapl:{i}") for i in (0, 1)]
h = None
if pynvml is not None:
    pynvml.nvmlInit()
    h = pynvml.nvmlDeviceGetHandleByIndex(0)
stop = False


def _stop(*_):
    global stop
    stop = True


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)
header = dict(kind="header", zones=[dict(path=str(z), name=(z / "name").read_text().strip(),
                                        max_energy_range_uj=int((z / "max_energy_range_uj").read_text()))
                                   for z in ZONES],
              gpu=(pynvml.nvmlDeviceGetName(h) if h else None), period=period, cpus=cpus)
ME = os.getpid()


def ctx_totals():
    """Sum voluntary/nonvoluntary ctxt switches over all tasks of measured process trees (Amendment 1)."""
    parent, roots = {}, []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == ME:
            continue
        try:
            with open(f"/proc/{d}/stat") as f:
                parent[int(d)] = int(f.read().rsplit(")", 1)[1].split()[1])
            with open(f"/proc/{d}/cmdline", "rb") as f:
                cl = f.read()
                if b"stock-stacks/" in cl or b"llama-server" in cl or b"energy_diagnosis" in cl or b"hp-venv" in cl:
                    roots.append(int(d))
        except (OSError, IndexError, ValueError):
            pass
    tree, frontier = set(roots), list(roots)
    kids = {}
    for c, pp in parent.items():
        kids.setdefault(pp, []).append(c)
    while frontier:
        for c in kids.get(frontier.pop(), []):
            if c not in tree and c != ME:
                tree.add(c)
                frontier.append(c)
    vol = nonvol = 0
    for pid in tree:
        try:
            for t in os.listdir(f"/proc/{pid}/task"):
                with open(f"/proc/{pid}/task/{t}/status") as f:
                    for line in f:
                        if line.startswith("voluntary_ctxt_switches"):
                            vol += int(line.split()[1])
                        elif line.startswith("nonvoluntary_ctxt_switches"):
                            nonvol += int(line.split()[1])
        except OSError:
            pass
    return dict(pids=len(tree), vol=vol, nonvol=nonvol)


freq_files = [Path(f"/sys/devices/system/cpu/cpu{c}/cpufreq/scaling_cur_freq") for c in cpus]
with out.open("w") as f:
    f.write(json.dumps(header) + "\n")
    i = 0
    nxt = time.monotonic()
    while not stop:
        row = dict(t=time.monotonic_ns(), rapl=[int((z / "energy_uj").read_text()) for z in ZONES],
                   gpu_mj=(pynvml.nvmlDeviceGetTotalEnergyConsumption(h) if h else None),
                   util=(pynvml.nvmlDeviceGetUtilizationRates(h).gpu if h else None),
                   power_mw=(pynvml.nvmlDeviceGetPowerUsage(h) if h else None))
        if i % 5 == 0:
            if freq_files:
                row["khz"] = [int(p.read_text()) for p in freq_files]
            row["ctx"] = ctx_totals()
        f.write(json.dumps(row) + "\n")
        i += 1
        if i % 25 == 0:
            f.flush()
        nxt += period
        time.sleep(max(0.0, nxt - time.monotonic()))
