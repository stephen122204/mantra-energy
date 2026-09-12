"""Bounded measurement sessions for the energy-diagnosis study.

This module adapts an existing A-LEMS energy reader to the ED-01 study
contracts.  Goal endpoints are captured before collector teardown so cleanup
latency cannot silently enlarge the measured workload window.
"""

from __future__ import annotations

import time
import math
import uuid
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from core.readers.measurement_schema import ENERGY_COUNTER, DomainDescriptor
from studies.energy_diagnosis.contracts import MeasurementRecord, SensorSample


class _JsonRecord:
    def to_dict(self):
        return dataclasses.asdict(self)

    def write_json(self, path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


@dataclass(frozen=True)
class EnvironmentIdentity:
    source_revision: str
    hostname: str
    boot_id: str
    allocation_id: str
    cpu_allocation: str
    devices: tuple[str, ...]
    isolation: str


@dataclass(frozen=True)
class DomainCapability:
    domain_id: str
    native_key: str
    domain_type: str
    parent_domain: Optional[str]
    unit: str
    access: str
    reason: str = ""


@dataclass(frozen=True)
class CapabilityReport(_JsonRecord):
    environment: EnvironmentIdentity
    reader_name: str
    source: str
    sampling_hz: int
    counter_width_bits: int
    probed_start_ns: int
    probed_end_ns: int
    wall_clock_ns: int
    domains: tuple[DomainCapability, ...]


@dataclass(frozen=True)
class CounterTransition:
    domain_id: str
    raw_start: Optional[float]
    raw_end: Optional[float]
    delta: Optional[float]
    status: str
    counter_generation: int
    reason: str = ""


@dataclass(frozen=True)
class SessionArtifacts(_JsonRecord):
    session_id: str
    environment: EnvironmentIdentity
    clock_domain: str
    wall_clock_start_ns: int
    wall_clock_end_ns: int
    session_start_ns: int
    goal_start_ns: int
    goal_end_ns: int
    session_end_ns: int
    samples: tuple[SensorSample, ...]
    transitions: tuple[CounterTransition, ...]
    measurements: tuple[MeasurementRecord, ...]


class MeasurementSession:
    """Capture one goal's raw counter endpoints and derived measurements."""

    def __init__(
        self,
        reader,
        *,
        environment: EnvironmentIdentity,
        session_id: Optional[str] = None,
        clock_domain: str = "host-monotonic",
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_time_ns: Callable[[], int] = time.time_ns,
        teardown: Optional[Callable[[], None]] = None,
    ) -> None:
        self.reader = reader
        self.environment = environment
        self.schema = reader.get_measurement_schema()
        self.session_id = session_id or str(uuid.uuid4())
        self.clock_domain = clock_domain
        self._monotonic_ns = monotonic_ns
        self._wall_time_ns = wall_time_ns
        self._teardown = teardown or (lambda: None)
        self._samples: list[SensorSample] = []
        self._raw: dict[str, Mapping[str, Optional[float]]] = {}
        self._brackets: dict[str, tuple[int, int]] = {}
        self._state = "created"
        self._sample_number = 0

    def start_session(self) -> None:
        if self._state != "created":
            raise RuntimeError("measurement session has already started")
        self.wall_clock_start_ns = self._wall_time_ns()
        self.session_start_ns = self._monotonic_ns()
        self._read_endpoint("session_start")
        self._state = "session_started"

    def start_goal(self) -> int:
        if self._state != "session_started":
            raise RuntimeError("goal can only start in an active session")
        self._read_endpoint("goal_start")
        self.goal_start_ns = self._brackets["goal_start"][0]
        self._state = "goal_started"
        return self.goal_start_ns

    def sample_goal(self) -> None:
        if self._state != "goal_started":
            raise RuntimeError("goal is not active")
        self._read_endpoint(f"goal_sample_{len(self._raw)}")

    def end_goal(self) -> int:
        if self._state != "goal_started":
            raise RuntimeError("goal is not active")
        self._read_endpoint("goal_end")
        self.goal_end_ns = self._brackets["goal_end"][1]
        self._state = "goal_ended"
        return self.goal_end_ns

    def finish_session(self) -> SessionArtifacts:
        if self._state != "goal_ended":
            raise RuntimeError("finish_session requires a captured goal endpoint")
        # The goal endpoint is already immutable. Teardown belongs to the wider
        # session span and must never redefine goal_end_ns.
        self._teardown()
        self.session_end_ns = self._monotonic_ns()
        self.wall_clock_end_ns = self._wall_time_ns()
        transitions, measurements = self._derive_measurements()
        self._state = "finished"
        return SessionArtifacts(
            session_id=self.session_id,
            environment=self.environment,
            clock_domain=self.clock_domain,
            wall_clock_start_ns=self.wall_clock_start_ns,
            wall_clock_end_ns=self.wall_clock_end_ns,
            session_start_ns=self.session_start_ns,
            goal_start_ns=self.goal_start_ns,
            goal_end_ns=self.goal_end_ns,
            session_end_ns=self.session_end_ns,
            samples=tuple(self._samples),
            transitions=tuple(transitions),
            measurements=tuple(measurements),
        )

    def _read_endpoint(self, label: str) -> None:
        acquired_start = self._monotonic_ns()
        error = ""
        try:
            values = self.reader.read_energy()
            if not isinstance(values, Mapping):
                raise TypeError("reader returned a non-mapping value")
        except PermissionError as exc:
            values = {}
            error = f"access denied: {exc}"
        except Exception as exc:  # readers must leave a durable failed sample
            values = {}
            error = f"read failed: {type(exc).__name__}: {exc}"
        acquired_end = self._monotonic_ns()
        invalid_values = {k: repr(v) for k, v in values.items() if v is not None and
                          (not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0)}
        values = {k: None if k in invalid_values else v for k, v in values.items()}
        self._raw[label] = dict(values)
        self._brackets[label] = (acquired_start, acquired_end)

        for domain in self.schema.domains:
            self._sample_number += 1
            value = values.get(domain.native_key)
            status = "ok" if value is not None and not error else "missing"
            reason = "" if status == "ok" else (error or "reader returned no value")
            if domain.native_key in invalid_values:
                status = "invalid"
                reason = f"invalid raw reading: {invalid_values[domain.native_key]}"
            self._samples.append(
                SensorSample(
                    sample_id=f"{self.session_id}:{label}:{self._sample_number}",
                    session_id=self.session_id,
                    domain_id=domain.canonical_name,
                    acquired_start_ns=acquired_start,
                    acquired_end_ns=acquired_end,
                    unit=self.schema.unit,
                    status=status,
                    value=float(value) if status == "ok" else None,
                    reason=reason,
                )
            )

    def _derive_measurements(self):
        start = self._raw["goal_start"]
        end = self._raw["goal_end"]
        transitions: list[CounterTransition] = []
        measurements: list[MeasurementRecord] = []
        for domain in self.schema.domains:
            raw_start = start.get(domain.native_key)
            raw_end = end.get(domain.native_key)
            labels = [label for label in self._raw if label == "goal_start" or label.startswith("goal_sample_") or label == "goal_end"]
            intervals = [self._counter_delta(domain, self._raw[a].get(domain.native_key), self._raw[b].get(domain.native_key))
                         for a, b in zip(labels, labels[1:])]
            invalid = next((item for item in intervals if item[1] is None), None)
            if invalid:
                status, delta, reason = invalid
            else:
                delta = sum(item[1] for item in intervals)
                status = "wrapped" if any(item[0] == "wrapped" for item in intervals) else "ok"
                reason = ""

            transitions.append(CounterTransition(
                domain_id=domain.canonical_name,
                raw_start=raw_start,
                raw_end=raw_end,
                delta=delta,
                status=status,
                counter_generation=1 if status == "reset" else 0,
                reason=reason,
            ))
            if delta is None:
                measurements.append(MeasurementRecord(
                    session_id=self.session_id,
                    domain_id=domain.canonical_name,
                    start_ns=self.goal_start_ns,
                    end_ns=self.goal_end_ns,
                    status="unavailable",
                    method="counter-difference",
                    reason=reason,
                ))
            else:
                measurements.append(MeasurementRecord(
                    session_id=self.session_id,
                    domain_id=domain.canonical_name,
                    start_ns=self.goal_start_ns,
                    end_ns=self.goal_end_ns,
                    status="valid",
                    method="counter-difference-with-wrap" if status == "wrapped" else "counter-difference",
                    energy_j=float(delta) / 1_000_000,
                    coverage=1.0,
                ))
        return transitions, measurements

    def _counter_delta(self, domain: DomainDescriptor, start, end):
        if domain.domain_type != ENERGY_COUNTER:
            return "unsupported", None, "endpoint snapshots cannot integrate a power rail"
        if start is None or end is None:
            return "missing", None, "goal endpoint reading is missing"
        if end >= start:
            return "ok", end - start, ""
        counter_max = domain.max_energy_range_uj or (1 << self.schema.counter_width_bits)
        # A high-to-low crossing is consistent with a single wrap. Other
        # backwards jumps are conservatively treated as a reset.
        if start >= counter_max * 0.75 and end <= counter_max * 0.25:
            return "wrapped", end - start + counter_max, "counter wrapped once"
        return "reset", None, "counter decreased outside the wrap boundary"


def probe_capabilities(
    reader,
    *,
    environment: EnvironmentIdentity,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    wall_time_ns: Callable[[], int] = time.time_ns,
) -> CapabilityReport:
    """Probe declared domains once, preserving unsupported and denied states."""
    schema = reader.get_measurement_schema()
    start = monotonic_ns()
    error = ""
    try:
        if not reader.is_available():
            values = {}
            error = "reader reports unavailable on this host"
            default_access = "unsupported"
        else:
            values = reader.read_energy()
            if not isinstance(values, Mapping):
                raise TypeError("reader returned a non-mapping value")
            default_access = "readable"
    except PermissionError as exc:
        values = {}
        error = f"access denied: {exc}"
        default_access = "denied"
    except Exception as exc:
        values = {}
        error = f"probe failed: {type(exc).__name__}: {exc}"
        default_access = "unavailable"
    end = monotonic_ns()
    domains = tuple(
        DomainCapability(
            domain_id=d.canonical_name,
            native_key=d.native_key,
            domain_type=d.domain_type,
            parent_domain=d.parent_domain,
            unit=schema.unit,
            access=(
                default_access
                if values.get(d.native_key) is not None or error
                else "unavailable"
            ),
            reason=(error or "probe returned no value")
            if values.get(d.native_key) is None else "",
        )
        for d in schema.domains
    )
    return CapabilityReport(
        environment=environment,
        reader_name=reader.get_name(),
        source=schema.source,
        sampling_hz=schema.sampling_hz,
        counter_width_bits=schema.counter_width_bits,
        probed_start_ns=start,
        probed_end_ns=end,
        wall_clock_ns=wall_time_ns(),
        domains=domains,
    )
