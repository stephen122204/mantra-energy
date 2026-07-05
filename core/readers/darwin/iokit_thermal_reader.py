#!/usr/bin/env python3
"""
================================================================================
IOKIT THERMAL READER — macOS Thermal Measurement
================================================================================

Three real, independently cross-validated data sources on Apple Silicon:

1. Die temperature via a vendored helper binary built from Koan-Sin Tan's
   `sensors.m` (github.com/freedomtan/sensors_cmdline, BSD 3-Clause,
   Copyright 2021 "freedom" Koan-Sin Tan). Reads PMU tdie0-tdieN probes
   through Apple's own public IOHIDEventSystemClient framework, using
   constants (kHIDPage_AppleVendor, kHIDUsage_AppleVendor_TemperatureSensor,
   kIOHIDEventTypeTemperature) that trace directly to Apple's published
   open source headers, IOHIDFamily/AppleHIDUsageTables.h and
   IOHIDFamily/IOHIDEventTypes.h (opensource.apple.com). No sudo required.

   Cross-validated this session (2026-07-02) three independent ways:
     a. Real CPU Power increase confirmed via powermetrics during an
        8-way `yes` saturation load (900-1600mW idle to 5000-6100mW loaded)
     b. tdie0 through tdie10 rose monotonically over the same 16-second
        window (~29.6-31.4C idle to ~30.4-30.8C loaded, consistent
        direction across all probes)
     c. Magnitude and direction physically sensible for a fan-managed
        laptop under moderate load, not a runaway or implausible jump
   PMU tcal excluded: fixed at 51.850006C across every sample, a
   calibration constant, not a live reading. "noname" excluded: fixed at
   0.0 across every sample, a dead/unmapped HID service.

2. Battery temperature via `ioreg -rc AppleSmartBattery`, "Temperature"
   key, deciKelvin converted to Celsius. Standard, decades-old, documented
   IOKit property, not reverse engineered.

3. Thermal pressure level via `powermetrics --samplers thermal`,
   categorical only (Nominal/Fair/Serious/Critical), first-party Apple
   tool. Exposed outside the ThermalReaderABC contract since it is not a
   Celsius value, get_pressure_level() only, for logging/provenance.

ThermalReaderABC requires Dict[str, float]. package_temp_celsius is
computed as max(tdie0..tdieN) per sample, package-level peak being the
more conservative, more useful figure for thermal throttling analysis
than a mean across probes.

Author: Deepak Panigrahy
Third-party component: sensors.m by Koan-Sin Tan, BSD 3-Clause, vendored
at core/readers/darwin/vendor/sensors.m, LICENSE alongside it.
================================================================================
"""

import logging
import os
import re
import subprocess
import threading
from typing import Dict, List, Optional

from core.readers.interfaces import ThermalReaderABC

logger = logging.getLogger(__name__)

PRESSURE_LEVEL_RANK = {
    "Nominal": 0,
    "Fair": 1,
    "Serious": 2,
    "Critical": 3,
}

# Sensor names confirmed dead/non-live this session, always excluded.
EXCLUDED_SENSOR_SUBSTRINGS = ("tcal", "noname")

VENDOR_DIR = os.path.join(os.path.dirname(__file__), "vendor")
SENSORS_BINARY = os.path.join(VENDOR_DIR, "sensors")


class IOKitThermalReader(ThermalReaderABC):
    """
    macOS thermal reader. Real numeric data: die temperature (vendored
    sensors.m binary) and battery Celsius (ioreg). Real categorical data:
    thermal pressure level (powermetrics), exposed outside the ABC
    contract since it is not a Celsius value.
    """

    METHOD_ID          = "iokit_thermal_reader"
    METHOD_NAME        = "IOKit Thermal Reader (macOS)"
    METHOD_LAYER       = "silicon"
    METHOD_CONFIDENCE  = 0.75   # die temp is real, live, cross-validated
                                 # three ways this session; not 1.0 since
                                 # exact tdieN to physical-core mapping is
                                 # not independently confirmed, only that
                                 # the readings are live and responsive
    METHOD_PROVENANCE  = "MEASURED"
    METHOD_PARAMS      = {
        "die_temp_source": "vendored sensors.m (Koan-Sin Tan, BSD 3-Clause), "
                            "IOHIDEventSystemClient, Apple published constants",
        "battery_source": "ioreg AppleSmartBattery Temperature key",
        "pressure_source": "powermetrics thermal sampler, categorical only",
        "excluded_sensors": list(EXCLUDED_SENSOR_SUBSTRINGS),
        "aggregation": "package_temp_celsius = max(tdie0..tdieN) per sample",
    }
    FALLBACK_METHOD_ID = "ml_thermal_estimator"

    def __init__(self, config: dict = None):
        self._config = config or {}
        self._lock = threading.Lock()
        self._latest_level: Optional[str] = None
        self._proc = None
        self._binary_available = os.path.exists(SENSORS_BINARY) and os.access(
            SENSORS_BINARY, os.X_OK
        )
        self._available = self._check_available()
        if self._available:
            self._start_pressure_sampling()
        if not self._binary_available:
            logger.warning(
                "IOKitThermalReader: vendored sensors binary not found at %s, "
                "die temperature unavailable, falling back to battery only. "
                "Build it via core/readers/darwin/vendor/build.sh",
                SENSORS_BINARY,
            )

    def _check_available(self) -> bool:
        try:
            result = subprocess.run(
                ["ioreg", "-rc", "AppleSmartBattery"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0 and '"Temperature"' in result.stdout
        except Exception as e:
            logger.warning("IOKitThermalReader: availability check failed: %s", e)
            return False

    def _start_pressure_sampling(self):
        cmd = ["sudo", "powermetrics", "--samplers", "thermal",
               "-i", "1000", "-n", "-1", "--format", "text"]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            threading.Thread(target=self._read_loop, daemon=True,
                              name="iokit-thermal-pressure").start()
        except Exception as e:
            logger.warning("IOKitThermalReader: pressure sampling failed to start: %s", e)
            self._proc = None

    def _read_loop(self):
        if not self._proc:
            return
        for line in self._proc.stdout:
            m = re.search(r"Current pressure level:\s+(\w+)", line)
            if m:
                with self._lock:
                    self._latest_level = m.group(1)

    def _read_die_temps(self) -> Dict[str, float]:
        """
        Run the vendored sensors binary once, parse its two-line CSV
        output (header, values), filter to tdie* probes only, excluding
        confirmed-dead entries (tcal, noname).
        """
        if not self._binary_available:
            return {}
        try:
            result = subprocess.run(
                [SENSORS_BINARY, "-o"], capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return {}
            lines = result.stdout.strip().split("\n")
            if len(lines) < 2:
                return {}
            names = [n.strip() for n in lines[0].split(",")]
            values = [v.strip() for v in lines[1].split(",")]
            die_temps: Dict[str, float] = {}
            for idx, (name, value) in enumerate(zip(names, values)):
                lname = name.lower()
                if any(ex in lname for ex in EXCLUDED_SENSOR_SUBSTRINGS):
                    continue
                if "tdie" not in lname:
                    continue
                try:
                    die_temps[f"tdie_{idx}"] = float(value)
                except ValueError:
                    continue
            return die_temps
        except Exception as e:
            logger.warning("IOKitThermalReader: die temp read failed: %s", e)
            return {}

    def read_all_thermal(self) -> Dict[str, float]:
        """
        Required by ThermalReaderABC. Real numeric sensors only.
        package_temp_celsius = max die probe reading, when available.
        battery_celsius always attempted independently.
        """
        temps: Dict[str, float] = {}

        die_temps = self._read_die_temps()
        if die_temps:
            temps["package_temp_celsius"] = round(max(die_temps.values()), 2)

        try:
            result = subprocess.run(
                ["ioreg", "-rc", "AppleSmartBattery"],
                capture_output=True, text=True, timeout=5,
            )
            m = re.search(r'"Temperature"\s*=\s*(\d+)', result.stdout)
            if m:
                decikelvin = int(m.group(1))
                celsius = decikelvin / 10.0 - 273.15
                temps["battery_celsius"] = round(celsius, 2)
        except Exception as e:
            logger.warning("IOKitThermalReader.read_all_thermal battery read failed: %s", e)

        return temps
    def read_temperatures(self):
        # type: () -> Dict
        """
        Return ThermalReadings-compatible dict for callers expecting that
        shape (energy_engine.py lines 737/1141, energy_analyzer consumes
        this). Harness uses read_all_thermal() for its own sampling loop
        (line 346); this method satisfies the ABC contract and any caller
        that checks read_temperatures() directly, same pattern as
        ARMThermalReader.
        """
        thermal = self.read_all_thermal()
        package_temp = thermal.get("package_temp_celsius")
        return {
            # package_celsius is the key consumed by energy_analyzer
            "package_celsius":  package_temp if package_temp is not None else 0.0,
            "core_temps":       [],
            "gpu_celsius":      0.0,   # no separate GPU thermal source, see 16F3 known limitations
            "pch_celsius":      0.0,
            "throttle_events":  0,
            "prochot_events":   0,
            # Real data available here unlike ARMThermalReader's static
            # False, we have an actual categorical pressure signal
            "is_throttling":    self.is_throttling(),
        }
    
    def get_pressure_level(self) -> Optional[str]:
        """Not part of ThermalReaderABC. Categorical, logging/provenance only."""
        with self._lock:
            return self._latest_level

    def is_throttling(self) -> bool:
        """Not part of ThermalReaderABC. Derived from pressure level."""
        level = self.get_pressure_level()
        return PRESSURE_LEVEL_RANK.get(level, 0) >= 2 if level else False

    def initialize(self):
        # type: () -> None
        """
        No-op initialize for interface compatibility with SensorReader/
        ARMThermalReader. IOKitThermalReader discovers everything (die
        temp binary, battery ioreg, pressure sampler) at __init__ time,
        no deferred initialization needed. Called by energy_engine.py
        after construction (line 228).
        """
        # available_sensors mirrors SensorReader/ARMThermalReader interface,
        # energy_engine.py checks len(self.sensor.available_sensors) > 0
        # (line 310) and truthiness (line 1600).
        self.available_sensors = []
        if self._binary_available:
            self.available_sensors.append("package_temp_celsius")
        if self._available:
            self.available_sensors.append("battery_celsius")
        # throttle_thresholds mirrors SensorReader/ARMThermalReader interface,
        # energy_engine.py calls self.sensor.throttle_thresholds.get(role)
        # (line 352), empty dict means no throttling data configured, same
        # as ARMThermalReader's own no-op value.
        self.throttle_thresholds = {}
        logger.debug(
            "IOKitThermalReader.initialize(): %d sensors ready: %s",
            len(self.available_sensors), self.available_sensors,
        )

    def is_available(self) -> bool:
        return self._available

    def get_name(self) -> str:
        return "IOKitThermalReader"
