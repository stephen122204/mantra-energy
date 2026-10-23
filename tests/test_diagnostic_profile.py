"""Diagnostic call profile summary and first-token marker (no GPU required)."""
from studies.energy_diagnosis.moe.diagnostic_profile import FIRST_TOKEN, summarize
from studies.energy_diagnosis.moe.token_timing import TokenTiming


class T:
    def __init__(self, *shape):
        self.shape = shape


def test_segments_split_at_first_token_and_union_overlaps():
    trace = {"traceEvents": [
        {"ph": "X", "cat": "cpu_op", "name": "aten::mm", "ts": 0, "dur": 100},
        {"ph": "X", "cat": "kernel", "name": "gemm", "ts": 10, "dur": 20},
        {"ph": "X", "cat": "kernel", "name": "gemm", "ts": 20, "dur": 20},          # overlaps: union 30
        {"ph": "X", "cat": "gpu_memcpy", "name": "Memcpy HtoD (Pinned -> Device)", "ts": 50, "dur": 10, "args": {"bytes": 4096}},
        {"ph": "X", "cat": "cuda_runtime", "name": "cudaStreamSynchronize", "ts": 40, "dur": 30},
        {"ph": "X", "cat": "user_annotation", "name": FIRST_TOKEN, "ts": 60, "dur": 0},
        {"ph": "X", "cat": "kernel", "name": "gemm", "ts": 70, "dur": 10},
    ]}
    s = summarize(trace)
    assert s["first_token_marked"]
    resume, decode = s["segments"]["resume"], s["segments"]["decode"]
    assert resume["kernel_busy_ms"] == 0.03 and resume["h2d_bytes"] == 4096 and resume["h2d_copy_count"] == 1
    assert resume["cuda_runtime_top_ms"]["cudaStreamSynchronize"] == 0.02   # clipped at the split
    assert decode["kernel_busy_ms"] == 0.01 and decode["h2d_bytes"] == 0
    assert 0 < decode["gpu_idle_fraction"] < 1


def test_first_token_callback_runs_once():
    calls = []
    timing = TokenTiming(on_first_token=lambda: calls.append(1))
    timing.put(T(1, 5))
    timing.put(T(1)); timing.put(T(1))
    timing.end()
    assert calls == [1] and timing.result(2)["generated_tokens"] == 2
