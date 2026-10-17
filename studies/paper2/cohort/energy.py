"""One CPU-package + GPU-board energy interval per cohort, on the existing ALEMS counters.

Reuses ``NodeCounterReader`` / ``NodeMeasurement`` (10 Hz sampling, RAPL package domains plus
NVML total energy of the serving GPU). ``integrate_samples`` re-derives each domain from the
recorded samples so a short sensor gap is bridged and reported instead of voiding the cohort,
while a gap longer than ``max_gap_s`` (or a backwards jump that is not a single wrap) marks
the domain invalid. The ALEMS endpoint-difference result is kept alongside for comparison.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Optional


@dataclass
class DomainEnergy:
    domain_id: str
    status: str            # valid | invalid | unavailable
    energy_j: Optional[float]
    samples_ok: int
    samples_missing: int
    max_gap_s: float
    wraps: int
    reason: str = ""

    def to_dict(self):
        return asdict(self)


def integrate_samples(samples: Iterable, start_ns: int, end_ns: int, *, max_gap_s: float = 30.0,
                      counter_max: Optional[float] = None, unit_scale: float = 1e-6) -> dict[str, DomainEnergy]:
    """Integrate cumulative-counter samples per domain over [start_ns, end_ns].

    ``samples`` are ALEMS ``SensorSample``-like objects (domain_id, acquired_start_ns,
    acquired_end_ns, status, value). Values are cumulative microjoules by default.
    """
    by_domain: dict[str, list] = {}
    for s in samples:
        t = (s.acquired_start_ns + s.acquired_end_ns) // 2
        if t < start_ns - 1 or t > end_ns + 1:
            continue
        by_domain.setdefault(s.domain_id, []).append((t, s.status, s.value))
    out: dict[str, DomainEnergy] = {}
    for domain, rows in by_domain.items():
        rows.sort()
        ok = [(t, v) for t, st, v in rows if st == "ok" and v is not None]
        missing = len(rows) - len(ok)
        if len(ok) < 2:
            out[domain] = DomainEnergy(domain, "unavailable", None, len(ok), missing, 0.0, 0,
                                       "fewer than two valid samples")
            continue
        total, wraps, max_gap, reason, status = 0.0, 0, 0.0, "", "valid"
        # Edges: the first/last valid sample must sit close to the interval boundary.
        edge_gap = max(ok[0][0] - start_ns, end_ns - ok[-1][0]) / 1e9
        max_gap = max(max_gap, edge_gap)
        for (t0, v0), (t1, v1) in zip(ok, ok[1:]):
            gap = (t1 - t0) / 1e9
            max_gap = max(max_gap, gap)
            if v1 >= v0:
                total += v1 - v0
            elif counter_max and v0 >= 0.75 * counter_max and v1 <= 0.25 * counter_max:
                total += v1 - v0 + counter_max
                wraps += 1
            else:
                status, reason = "invalid", "counter decreased outside a single wrap"
                break
        if status == "valid" and max_gap > max_gap_s:
            status, reason = "invalid", f"sensor gap {max_gap:.1f}s exceeds {max_gap_s:.0f}s"
        out[domain] = DomainEnergy(domain, status, total * unit_scale if status == "valid" else None,
                                   len(ok), missing, round(max_gap, 3), wraps, reason)
    return out


def cohort_energy_summary(artifacts, *, max_gap_s: float = 30.0) -> dict:
    """Summarise a finished NodeMeasurement session: per-domain integrated energy + totals."""
    schema = {d.canonical_name: d for d in artifacts.measurement_schema.domains}
    per_domain = {}
    for name, d in schema.items():
        rows = [s for s in artifacts.samples if s.domain_id == name]
        res = integrate_samples(rows, artifacts.goal_start_ns, artifacts.goal_end_ns, max_gap_s=max_gap_s,
                                counter_max=d.max_energy_range_uj).get(name)
        per_domain[name] = (res or DomainEnergy(name, "unavailable", None, 0, 0, 0.0, 0, "no samples")).to_dict()
    endpoint = {m.domain_id: {"status": m.status, "energy_j": m.energy_j, "method": m.method, "reason": m.reason}
                for m in artifacts.measurements}
    cpu = [v for k, v in per_domain.items() if k.startswith("PACKAGE")]
    gpu = [v for k, v in per_domain.items() if k.startswith("GPU_BOARD")]

    def total(parts):
        if not parts or any(p["status"] != "valid" for p in parts):
            return None
        return sum(p["energy_j"] for p in parts)

    cpu_j, gpu_j = total(cpu), total(gpu)
    return {
        "interval_s": (artifacts.goal_end_ns - artifacts.goal_start_ns) / 1e9,
        "cpu_package_j": cpu_j,
        "gpu_board_j": gpu_j,
        "cpu_plus_gpu_j": None if cpu_j is None or gpu_j is None else cpu_j + gpu_j,
        "domains": per_domain,
        "endpoint_difference": endpoint,
        "max_gap_s_allowed": max_gap_s,
        "scope": "CPU package (all sockets read) + NVML board energy of the serving GPU only",
    }
