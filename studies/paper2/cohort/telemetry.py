"""Engine telemetry: poll the server's Prometheus /metrics endpoint into a JSONL time series.

Request counts per poll are occupancy, not batch size. The series keeps the cumulative token,
prefix-cache and preemption counters so analysis can compute computed vs reused prompt
tokens and preemptions over any interval; per-request usage (cached tokens) comes from the
client records.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# Families kept from vLLM V1 (0.10.x). Unknown names are ignored; missing ones are recorded
# as absent in the poll so a renamed metric shows up as a gap instead of a silent zero.
VLLM_FAMILIES = (
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
    "vllm:gpu_cache_usage_perc",
    "vllm:kv_cache_usage_perc",
    "vllm:prefix_cache_queries_total",
    "vllm:prefix_cache_hits_total",
    "vllm:num_preemptions_total",
    "vllm:prompt_tokens_total",
    "vllm:generation_tokens_total",
    "vllm:request_success_total",
)
_LINE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eEinfNa]+)")


def parse_prometheus(text: str, families=VLLM_FAMILIES) -> dict[str, float]:
    """Sum samples per family over label sets (one model per server)."""
    out: dict[str, float] = {}
    wanted = set(families)
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m or m.group(1) not in wanted:
            continue
        try:
            value = float(m.group(3))
        except ValueError:
            continue
        out[m.group(1)] = out.get(m.group(1), 0.0) + value
    return out


def fetch_metrics(base_url: str, timeout: float = 2.0) -> str:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/metrics", timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


class MetricsPoller:
    """Background poller writing one JSON line per poll: wall/monotonic time + metrics or error."""

    def __init__(self, base_url: str, out_path: Path, interval_s: float = 1.0,
                 fetch: Callable[[str], str] = fetch_metrics, clock=time.monotonic):
        self.base_url, self.out_path, self.interval_s = base_url, Path(out_path), interval_s
        self._fetch, self._clock = fetch, clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.polls = 0
        self.errors = 0

    def poll_once(self, fh) -> None:
        rec = {"t_wall": time.time(), "t_mono": self._clock()}
        try:
            values = parse_prometheus(self._fetch(self.base_url))
            rec["metrics"] = values
            rec["missing"] = sorted(set(VLLM_FAMILIES) - set(values))
        except Exception as exc:  # recorded as a gap, never as zeros
            rec["error"] = f"{type(exc).__name__}: {exc}"
            self.errors += 1
        self.polls += 1
        fh.write(json.dumps(rec) + "\n")
        fh.flush()

    def _run(self) -> None:
        with open(self.out_path, "a") as fh:
            nxt = self._clock()
            while not self._stop.is_set():
                self.poll_once(fh)
                nxt += self.interval_s
                self._stop.wait(max(0.0, nxt - self._clock()))

    def start(self) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="metrics-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
