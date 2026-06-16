"""
core/readers/power_rail_sampler.py

PowerRailSampler — reads all POWER rails from SPBM hwmon at configurable Hz.
Reads power limits once at start (run_power_limits).
Decoupled from SPBMSampler and energy_samples_v2 — independent timestamp stream.

PAC-2 compliant: init failure falls back gracefully, never crashes energy_engine.
All paths sourced from hw_config.json power_paths — no hardcoded hwmon numbers.

Rail mapping matches power_rails registry (v57 migration):
    rail_id 1-10: POWER rails sampled at frequency
    limit_id 1-4: LIMIT rails read once at start

Data flow:
    PowerRailSampler.start()
        -> reads power limits once -> stored in self.limits_snapshot
        -> starts background thread at self.hz
    PowerRailSampler.stop()
        -> returns PowerRailResult(samples, limits_snapshot)
    experiment_runner inserts:
        db.insert_power_rail_samples(run_id, result.samples)
        db.insert_run_power_limits(run_id, result.limits_snapshot)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Rail name -> rail_id mapping (matches v57 seed)
RAIL_IDS: Dict[str, int] = {
    "dc_input":  1,
    "sys_total": 2,
    "soc_pkg":   3,
    "cpu_gpu":   4,
    "cpu_p":     5,
    "cpu_e":     6,
    "vcore":     7,
    "gpu":       8,
    "prereg":    9,
    "dla":       10,
}

# Limit name -> limit_id mapping (matches v59 seed)
LIMIT_IDS: Dict[str, int] = {
    "pl1":    1,
    "pl2":    2,
    "syspl1": 3,
    "syspl2": 4,
}

# All rails to sample (POWER kind only — no limits)
POWER_RAIL_KEYS = list(RAIL_IDS.keys())

# Limit keys read once per run
LIMIT_KEYS = list(LIMIT_IDS.keys())


@dataclass
class PowerRailSample:
    """One instantaneous power reading for one rail at one timestamp."""
    timestamp_ns: int
    interval_ns:  Optional[int]   # None for first sample
    rail_id:      int
    power_mw:     float


@dataclass
class PowerRailResult:
    """Returned by PowerRailSampler.stop()."""
    samples:         List[PowerRailSample] = field(default_factory=list)
    limits_snapshot: Dict[int, float] = field(default_factory=dict)
    # limits_snapshot: {limit_id -> value_mw}


def _read_uw(path: str) -> Optional[float]:
    """Read µW value from sysfs path, return mW. Returns None on error."""
    try:
        raw = Path(path).read_text().strip()
        return float(raw) / 1000.0  # µW -> mW
    except Exception as e:
        logger.debug("PowerRailSampler: failed to read %s: %s", path, e)
        return None


class PowerRailSampler:
    """
    Samples all POWER rails from SPBM hwmon at hz frequency.
    Reads power limits once at start.

    Args:
        power_paths: dict from hw_config.json spbm.power_paths
                     e.g. {"dc_input": "/sys/class/hwmon/hwmon7/power7_input", ...}
        hz:          sampling frequency (default 10)
    """

    def __init__(self, power_paths: Dict[str, str], hz: int = 10):
        self.hz = hz
        self._interval_s = 1.0 / hz

        # Resolve paths for POWER rails
        self._rail_paths: Dict[int, str] = {}
        for key, rail_id in RAIL_IDS.items():
            if key in power_paths:
                self._rail_paths[rail_id] = power_paths[key]
            else:
                logger.warning("PowerRailSampler: no path for rail '%s' in hw_config", key)

        # Resolve paths for LIMIT rails
        self._limit_paths: Dict[int, str] = {}
        for key, limit_id in LIMIT_IDS.items():
            if key in power_paths:
                self._limit_paths[limit_id] = power_paths[key]
            else:
                logger.warning("PowerRailSampler: no path for limit '%s' in hw_config", key)

        self._samples: List[PowerRailSample] = []
        self._limits_snapshot: Dict[int, float] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        """True if at least dc_input rail path exists and is readable."""
        dc_path = self._rail_paths.get(RAIL_IDS["dc_input"])
        if not dc_path:
            return False
        return Path(dc_path).exists()

    def _read_limits_once(self) -> None:
        """Read all limit rails once. Called at start() before sampling begins."""
        for limit_id, path in self._limit_paths.items():
            val = _read_uw(path)
            if val is not None:
                self._limits_snapshot[limit_id] = val
        logger.debug("PowerRailSampler: limits snapshot: %s", self._limits_snapshot)

    def _sample_loop(self) -> None:
        prev_ts: Optional[int] = None
        while not self._stop_event.is_set():
            tick_start = time.monotonic()
            now_ns = time.time_ns()
            interval_ns = (now_ns - prev_ts) if prev_ts is not None else None
            prev_ts = now_ns

            batch: List[PowerRailSample] = []
            for rail_id, path in self._rail_paths.items():
                val = _read_uw(path)
                if val is not None:
                    batch.append(PowerRailSample(
                        timestamp_ns=now_ns,
                        interval_ns=interval_ns,
                        rail_id=rail_id,
                        power_mw=val,
                    ))

            with self._lock:
                self._samples.extend(batch)

            elapsed = time.monotonic() - tick_start
            sleep_s = self._interval_s - elapsed
            if sleep_s > 0:
                self._stop_event.wait(sleep_s)

    def start(self) -> None:
        """Read limits once, then start background sampling thread."""
        self._read_limits_once()
        self._stop_event.clear()
        self._samples.clear()
        self._thread = threading.Thread(
            target=self._sample_loop,
            name="PowerRailSampler",
            daemon=True,
        )
        self._thread.start()
        logger.debug("PowerRailSampler: started at %d Hz", self.hz)

    def stop(self) -> PowerRailResult:
        """Stop sampling, return all samples + limits snapshot."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        with self._lock:
            result = PowerRailResult(
                samples=list(self._samples),
                limits_snapshot=dict(self._limits_snapshot),
            )
        logger.debug(
            "PowerRailSampler: stopped. %d samples, %d limits",
            len(result.samples), len(result.limits_snapshot),
        )
        return result
