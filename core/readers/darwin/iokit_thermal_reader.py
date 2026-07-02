#!/usr/bin/env python3
"""
================================================================================
IOKIT THERMAL READER — macOS Thermal Measurement
================================================================================

Two real data sources on Apple Silicon, confirmed against live hardware:

1. Battery temperature via `ioreg -rc AppleSmartBattery`, "Temperature" key,
   reported in deciKelvin, converted to Celsius. Real, numeric, no extra
   tooling required.
2. Thermal pressure level via `powermetrics --samplers thermal`, categorical
   only (Nominal/Fair/Serious/Critical), no numeric CPU/package temperature
   exists in this data source on macOS 26.3.1.

ThermalReaderABC requires Dict[str, float], real numbers only. The
categorical pressure level does not fit that contract and is NOT returned
from read_all_thermal(). It is exposed separately via get_pressure_level(),
for logging/provenance only, not part of the ABC.

No CPU/package Celsius key is returned. Confirmed no numeric source exists
for it on this platform (checked: no smctemp/istats Homebrew formula
available). Absence here is correct per MIC-3, not a placeholder.

Author: Deepak Panigrahy
================================================================================
"""

import logging
import re
import subprocess
import threading
from typing import Dict, Optional

from core.readers.interfaces import ThermalReaderABC

logger = logging.getLogger(__name__)

PRESSURE_LEVEL_RANK = {
    "Nominal": 0,
    "Fair": 1,
    "Serious": 2,
    "Critical": 3,
}


class IOKitThermalReader(ThermalReaderABC):
    """
    macOS thermal reader. Real numeric data: battery Celsius via ioreg.
    Real categorical data: thermal pressure level via powermetrics,
    exposed outside the ABC contract since it is not a Celsius value.
    """

    METHOD_ID          = "iokit_thermal_reader"
    METHOD_NAME        = "IOKit Thermal Reader (macOS)"
    METHOD_LAYER       = "silicon"
    METHOD_CONFIDENCE  = 0.60   # battery temp is real and numeric, but not
                                 # CPU/package temperature, confidence
                                 # reflects sensor relevance, not accuracy
    METHOD_PROVENANCE  = "MEASURED"
    METHOD_PARAMS      = {
        "battery_source": "ioreg AppleSmartBattery Temperature key",
        "pressure_source": "powermetrics thermal sampler, categorical only",
    }
    FALLBACK_METHOD_ID = "ml_thermal_estimator"

    def __init__(self, config: dict = None):
        self._config = config or {}
        self._lock = threading.Lock()
        self._latest_level: Optional[str] = None
        self._proc = None
        self._available = self._check_available()
        if self._available:
            self._start_pressure_sampling()

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
        # Same -n -1 fix already required for IOKitPowerReader, -n 0 means
        # zero samples and exits immediately, not continuous.
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

    def read_all_thermal(self) -> Dict[str, float]:
        """
        Required by ThermalReaderABC. Real numeric sensors only.
        Returns {'battery_celsius': X.XX} if battery temp is readable,
        empty dict otherwise. No CPU/package key, no numeric source
        confirmed available for it on this platform.
        """
        temps: Dict[str, float] = {}
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
            logger.warning("IOKitThermalReader.read_all_thermal failed: %s", e)
        return temps

    def get_pressure_level(self) -> Optional[str]:
        """
        Not part of ThermalReaderABC. Categorical thermal pressure,
        Nominal/Fair/Serious/Critical, for logging and provenance only.
        """
        with self._lock:
            return self._latest_level

    def is_throttling(self) -> bool:
        """Not part of ThermalReaderABC. Derived from pressure level."""
        level = self.get_pressure_level()
        return PRESSURE_LEVEL_RANK.get(level, 0) >= 2 if level else False

    def is_available(self) -> bool:
        return self._available

    def get_name(self) -> str:
        return "IOKitThermalReader"
