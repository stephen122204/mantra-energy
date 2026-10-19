"""Diagnostic-only CUDA/CPU timeline for selected generation calls.

Enabled by a `diagnostic` block in the backend config; never part of campaign
evidence (the profiler perturbs timing and the manifest is labelled). The
PyTorch profiler records process-wide CUPTI activity, so kernels and copies
issued by the native expert engine are included. Each profiled call is split
at the first generated token into resumption (prefill up to the first token)
and subsequent decode, and summarised per segment.
"""
import gzip
import json
from pathlib import Path
import tempfile

FIRST_TOKEN = "alems_first_token"


def _union(intervals):
    total, end = 0.0, None
    for start, stop in sorted(intervals):
        if end is None or start > end:
            total += stop - start
            end = stop
        elif stop > end:
            total += stop - end
            end = stop
    return total


def summarize(trace):
    events = [e for e in trace.get("traceEvents", []) if e.get("ph") == "X" and "dur" in e]
    if not events:
        raise ValueError("empty profiler trace")
    marks = [e["ts"] for e in events if e.get("name") == FIRST_TOKEN]
    begin = min(e["ts"] for e in events)
    end = max(e["ts"] + e["dur"] for e in events)
    split = min(marks) if marks else None
    segments = {"whole": (begin, end)}
    if split is not None:
        segments.update(resume=(begin, split), decode=(split, end))
    out = {}
    for name, (lo, hi) in segments.items():
        def clip(e):
            s, t = max(e["ts"], lo), min(e["ts"] + e["dur"], hi)
            return (s, t) if t > s else None
        kernels = [c for e in events if e.get("cat") == "kernel" for c in [clip(e)] if c]
        copies = [e for e in events if e.get("cat") == "gpu_memcpy" and clip(e)]
        h2d = [e for e in copies if "HtoD" in e.get("name", "")]
        gpu_any = [c for e in events if e.get("cat") in ("kernel", "gpu_memcpy", "gpu_memset") for c in [clip(e)] if c]
        runtime, cpu = {}, {}
        for e in events:
            c = clip(e)
            if not c:
                continue
            if e.get("cat") == "cuda_runtime":
                runtime[e["name"]] = runtime.get(e["name"], 0) + (c[1] - c[0])
            elif e.get("cat") == "cpu_op":
                cpu[e["name"]] = cpu.get(e["name"], 0) + (c[1] - c[0])
        wall = hi - lo
        out[name] = dict(
            wall_ms=round(wall / 1e3, 2),
            gpu_active_ms=round(_union(gpu_any) / 1e3, 2),
            gpu_idle_fraction=round(1 - _union(gpu_any) / wall, 4) if wall > 0 else None,
            kernel_busy_ms=round(_union(kernels) / 1e3, 2),
            kernel_count=len(kernels),
            h2d_copy_busy_ms=round(_union([clip(e) for e in h2d]) / 1e3, 2),
            h2d_copy_count=len(h2d),
            h2d_bytes=sum(int(e.get("args", {}).get("bytes", 0)) for e in h2d),
            other_copy_count=len(copies) - len(h2d),
            cuda_runtime_top_ms={k: round(v / 1e3, 2) for k, v in sorted(runtime.items(), key=lambda kv: -kv[1])[:12]},
            cpu_op_inclusive_top_ms={k: round(v / 1e3, 2) for k, v in sorted(cpu.items(), key=lambda kv: -kv[1])[:15]},
        )
    return dict(version="alems-call-profile-v1", first_token_marked=split is not None, segments=out,
                scope="Diagnostic profiler run; timings are perturbed by tracing. Intervals are GPU activity unions "
                      "within each segment; CPU op times are inclusive and may overlap.")


class CallProfiler:
    """Profile one generation call and write summary (+ optional compressed trace)."""

    def __init__(self, torch, directory, index, keep_trace=False):
        self.torch, self.directory, self.index, self.keep_trace = torch, Path(directory), index, keep_trace
        self.directory.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        from torch.profiler import profile, ProfilerActivity
        self.profile = profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA])
        self.profile.__enter__()
        return self

    def mark_first_token(self):
        from torch.profiler import record_function
        with record_function(FIRST_TOKEN):
            pass

    def __exit__(self, *exc):
        self.torch.cuda.synchronize()
        self.profile.__exit__(*exc)
        if exc[0] is not None:
            return False
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "trace.json"
            self.profile.export_chrome_trace(str(raw))
            trace = json.loads(raw.read_text())
            summary = summarize(trace)
            summary["call_index"] = self.index
            (self.directory / f"call-{self.index}-profile.json").write_text(json.dumps(summary, indent=1))
            if self.keep_trace:
                with gzip.open(self.directory / f"call-{self.index}-trace.json.gz", "wt") as f:
                    json.dump(trace, f)
        return False
