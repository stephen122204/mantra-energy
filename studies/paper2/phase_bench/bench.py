#!/usr/bin/env python3
"""Pilot P0: does 4-bit's per-token energy saving over 8-bit change with concurrency?

Stock llama-server, one V100, Qwen3-8B Q4_K_M vs Q8_0, P concurrent slots each sending
fixed-length requests (same prompt length, same generated length, greedy, no prompt cache).
GPU board energy from the NVML cumulative counter; CPU energy is NOT included (pilot only).
Writes one CSV row per (precision, concurrency, rep).
"""
import argparse, csv, json, os, subprocess, sys, threading, time
from pathlib import Path

import pynvml, requests

W = Path.home() / "claude-pilot"
SERVER = W / "llama.cpp/build/bin/llama-server"
MODELS = {"q4": W / "models/Qwen3-8B-Q4_K_M.gguf", "q8": W / "models/Qwen3-8B-Q8_0.gguf"}

# Agent-like prompt: a code file plus a task, ~1.2k tokens. The id makes each request distinct.
CODE = "\n".join(f"def f{i}(rows):\n    return [r for r in rows if r['k{i}'] > {i}]" for i in range(60))
SHORT = False
def prompt(i):
    if SHORT:
        return f"Request {i}. Write a long, detailed Python tutorial about list comprehensions.\n"
    return (f"Request {i}. You are a coding agent. Read the module and write a new function "
            f"`summarize` that calls every filter and returns counts.\n\n{CODE}\n\nAnswer with code only.\n")

def gpu_energy_j(h):
    return pynvml.nvmlDeviceGetTotalEnergyConsumption(h) / 1000.0  # mJ -> J

def wait_ready(port, proc, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            sys.exit(f"server exited with {proc.returncode}")
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    sys.exit("server not ready")

def run_cell(port, conc, per_worker, n_predict, h):
    results, lock = [], threading.Lock()
    def worker(wid):
        for j in range(per_worker):
            body = {"prompt": prompt(wid * 1000 + j), "n_predict": n_predict, "temperature": 0,
                    "ignore_eos": True, "cache_prompt": False}
            r = requests.post(f"http://127.0.0.1:{port}/completion", json=body, timeout=1800).json()
            with lock:
                results.append((r["tokens_predicted"], r["tokens_evaluated"]))
    threads = [threading.Thread(target=worker, args=(w,)) for w in range(conc)]
    e0, t0 = gpu_energy_j(h), time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    e1, t1 = gpu_energy_j(h), time.time()
    gen = sum(r[0] for r in results); pre = sum(r[1] for r in results)
    return {"energy_j": e1 - e0, "wall_s": t1 - t0, "gen_tokens": gen, "prompt_tokens": pre,
            "requests": len(results)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", type=int, default=3)
    ap.add_argument("--conc", default="1,4,16")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--n-predict", type=int, default=256)
    ap.add_argument("--requests-per-cell", type=int, default=32)
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--order", default="q4,q8")
    ap.add_argument("--short-prompt", action="store_true", help="decode-heavy: ~20-token prompt")
    ap.add_argument("--tag", default="p0")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    global SHORT
    SHORT = a.short_prompt
    out = a.out or str(W / f"logs/{a.tag}_results.csv")

    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    pynvml.nvmlInit()
    h = pynvml.nvmlDeviceGetHandleByIndex(a.gpu)
    if pynvml.nvmlDeviceGetComputeRunningProcesses(h):
        sys.exit(f"GPU {a.gpu} is busy; refusing to measure")
    concs = [int(c) for c in a.conc.split(",")]
    port = a.port
    rows = []
    for prec in a.order.split(","):
        for conc in concs:
            env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(a.gpu))
            ctx = conc * 2048
            log = open(W / f"logs/{a.tag}_server_{prec}_p{conc}.log", "w")
            proc = subprocess.Popen([str(SERVER), "-m", str(MODELS[prec]), "-ngl", "99", "-c", str(ctx),
                                     "-np", str(conc), "--host", "127.0.0.1", "--port", str(port)],
                                    env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                wait_ready(port, proc)
                run_cell(port, conc, 1, a.n_predict, h)  # warm-up, discarded
                time.sleep(5)
                idle0 = gpu_energy_j(h); time.sleep(10); idle_w = (gpu_energy_j(h) - idle0) / 10
                per_worker = max(1, a.requests_per_cell // conc)
                for rep in range(a.reps):
                    r = run_cell(port, conc, per_worker, a.n_predict, h)
                    r.update(precision=prec, conc=conc, rep=rep, idle_w=idle_w,
                             j_per_gen_token=r["energy_j"] / r["gen_tokens"],
                             j_per_request=r["energy_j"] / r["requests"])
                    rows.append(r); print(json.dumps(r), flush=True)
            finally:
                proc.terminate(); proc.wait(timeout=60); log.close()
            time.sleep(10)
    with open(out, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys())); wr.writeheader(); wr.writerows(rows)
    # Summary: 4-bit/8-bit ratio of J per generated token at each concurrency (median over reps)
    import statistics as st
    for conc in concs:
        m = {p: st.median(r["j_per_gen_token"] for r in rows if r["precision"] == p and r["conc"] == conc)
             for p in ["q4", "q8"]}
        print(f"conc={conc:3d}  J/tok q4={m['q4']:.4f} q8={m['q8']:.4f}  ratio q4/q8={m['q4']/m['q8']:.3f}")
    (W / f"logs/{a.tag.upper()}_DONE").write_text("done\n")

if __name__ == "__main__":
    main()
