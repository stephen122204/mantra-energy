"""Hand-off structure x host power policy microbenchmark (private; direction-goal).

Holds the GPU work per "token" fixed and varies only how the host critical path is organised:
  spin1    one thread launches all kernels; one torch.cuda.synchronize() per token (CUDA default sync: spin/auto)
  block1   same, but waits on a blocking CUDA event per token (thread sleeps once per token)
  chainK   per layer, the main thread hands the layer to a chain of K worker threads (queue.Queue, blocking);
           the last worker launches the layer's kernels, waits on a blocking event, and hands the result back.
           This mimics a dispatcher -> route -> exec -> completion pipeline (K+1 blocking wakes per layer).
Metric per run: decode ms/token over N tokens after W warm-up tokens; per-thread CPU seconds; voluntary context
switches per token (all threads of this process, from /proc). Energy is read by an external sampler.

Usage: python handoff_bench.py --mode chain3 --layers 48 --kernels 16 --tokens 200 --warmup 20 --out run.json
"""
import argparse, json, os, queue, threading, time
import torch


def vcsw():
    tot = 0
    for t in os.listdir("/proc/self/task"):
        try:
            for line in open(f"/proc/self/task/{t}/status"):
                if line.startswith("voluntary_ctxt_switches"):
                    tot += int(line.split()[1])
        except FileNotFoundError:
            pass
    return tot


def energy():
    """CPU package RAPL (both sockets, uJ, raw counters) and NVML GPU energy (mJ). Read-only, no root needed on LIQID05."""
    rapl = []
    for z in ("intel-rapl:0", "intel-rapl:1"):
        try:
            rapl.append(int(open(f"/sys/class/powercap/{z}/energy_uj").read()))
        except OSError:
            rapl.append(None)
    try:
        import pynvml
        pynvml.nvmlInit()
        gpu = pynvml.nvmlDeviceGetTotalEnergyConsumption(pynvml.nvmlDeviceGetHandleByIndex(0))
    except Exception:
        gpu = None
    return dict(rapl_uj=rapl, gpu_mj=gpu, t=time.perf_counter_ns())


def rapl_max():
    out = []
    for z in ("intel-rapl:0", "intel-rapl:1"):
        try:
            out.append(int(open(f"/sys/class/powercap/{z}/max_energy_range_uj").read()))
        except OSError:
            out.append(None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True)  # spin1 | block1 | chainK
    ap.add_argument("--layers", type=int, default=48)
    ap.add_argument("--kernels", type=int, default=16)
    ap.add_argument("--dim", type=int, default=1024)
    ap.add_argument("--tokens", type=int, default=200)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    dev = torch.device("cuda")
    x0 = torch.randn(1, a.dim, device=dev, dtype=torch.bfloat16)
    ws = [torch.randn(a.dim, a.dim, device=dev, dtype=torch.bfloat16) / a.dim ** 0.5 for _ in range(a.kernels)]

    def layer(x):
        for w in ws:
            x = torch.tanh(x @ w)
        return x

    stamps = []
    if a.mode in ("spin1", "block1"):
        def token(x):
            for _ in range(a.layers):
                x = layer(x)
            if a.mode == "spin1":
                torch.cuda.synchronize()
            else:
                e = torch.cuda.Event(blocking=True); e.record(); e.synchronize()
            return x
        run = token
        stop = lambda: None
    elif a.mode.startswith("chain"):
        k = int(a.mode[5:])
        qs = [queue.Queue() for _ in range(k + 1)]  # qs[0]: main -> w1, ..., qs[k]: wk -> main

        def worker(i):
            try:
                torch.cuda.set_device(0)
                while True:
                    item = qs[i].get()
                    if item is None:
                        if i + 1 < k: qs[i + 1].put(None)
                        return
                    if i == k - 1:
                        y = layer(item)
                        e = torch.cuda.Event(blocking=True); e.record(); e.synchronize()
                        qs[k].put(y)
                    else:
                        qs[i + 1].put(item)
            except BaseException as ex:  # never leave the main thread waiting on a dead worker
                qs[k].put(ex)
                raise
        th = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(k)]
        for t in th: t.start()

        def run(x):
            for _ in range(a.layers):
                qs[0].put(x); x = qs[k].get(timeout=60)
                if isinstance(x, BaseException):
                    raise RuntimeError("chain worker failed") from x
            return x

        def stop():
            qs[0].put(None)
            for t in th: t.join(timeout=5)
    else:
        raise SystemExit("unknown mode")

    x = x0
    for _ in range(a.warmup):
        x = run(x)
    torch.cuda.synchronize()
    e0 = energy()
    c0, t0, w0, m0 = vcsw(), time.perf_counter_ns(), time.time_ns(), time.monotonic_ns()
    cpu0 = time.process_time()
    for _ in range(a.tokens):
        x = run(x)
        stamps.append(time.perf_counter_ns())
    torch.cuda.synchronize()
    t1, c1, cpu1 = time.perf_counter_ns(), vcsw(), time.process_time()
    w1, m1 = time.time_ns(), time.monotonic_ns()
    e1 = energy()
    stop()
    mx = rapl_max()
    cpu_j = None
    if None not in e0["rapl_uj"] + e1["rapl_uj"] + mx:
        cpu_j = sum(((b - a) if b >= a else b - a + m + 1) for a, b, m in zip(e0["rapl_uj"], e1["rapl_uj"], mx)) / 1e6
    gpu_j = (e1["gpu_mj"] - e0["gpu_mj"]) / 1e3 if e0["gpu_mj"] is not None and e1["gpu_mj"] is not None else None
    res = dict(mode=a.mode, layers=a.layers, kernels=a.kernels, dim=a.dim, tokens=a.tokens,
               ms_per_token=(t1 - t0) / 1e6 / a.tokens, first_ns=t0, last_ns=t1, stamps=stamps,
               wall_first_ns=w0, wall_last_ns=w1, mono_first_ns=m0, mono_last_ns=m1,
               vcsw_per_token=(c1 - c0) / a.tokens, cpu_pkg_j=cpu_j, gpu_j=gpu_j,
               j_per_token=(cpu_j + gpu_j) / a.tokens if cpu_j is not None and gpu_j is not None else None, process_cpu_s=cpu1 - cpu0,
               cpu_util_of_wall=(cpu1 - cpu0) / ((t1 - t0) / 1e9),
               affinity=sorted(os.sched_getaffinity(0)), checksum=float(x.float().sum()),
               torch=torch.__version__, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name())
    json.dump(res, open(a.out, "w"))
    print(json.dumps({k: v for k, v in res.items() if k != "stamps"}))


if __name__ == "__main__":
    main()
