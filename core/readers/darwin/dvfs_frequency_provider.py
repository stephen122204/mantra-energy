"""
core/readers/darwin/dvfs_frequency_provider.py

Discovers the P-cluster DVFS frequency table from the IORegistry pmgr
node on Apple Silicon. Isolates all Apple-specific ioreg/plist/binary
parsing so IOReportCPUFreqReader never touches it directly.

No A-LEMS dependencies — only stdlib (subprocess, plistlib, struct).
Can be tested standalone before wiring into the full reader.

PAC-4 compliant: every failure path returns None, never raises.
DC-1: 30% inline comment coverage throughout.
"""

import logging
import plistlib
import struct
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)


class DVFSFrequencyProvider:
    """Discovers the P-cluster DVFS frequency table from IORegistry.

    Apple Silicon SoCs store the available CPU frequency states as
    binary voltage-state blobs in the IORegistry pmgr device node.
    Each blob is a sequence of 8-byte records: (freq_hz u32le, voltage_mv u32le).

    Discovery runs once at construction time and caches the result.
    Subsequent calls to get_frequency_table() return the cached list.

    Key naming convention observed on M1 through M4:
      voltage-states1-sram  -> E-cluster
      voltage-states5-sram  -> P-cluster  (primary target)
      voltage-states9-sram  -> GPU
      voltage-states11-sram -> Second P-cluster (Max/Ultra)

    On unknown future chips the heuristic scan (step 2) selects the
    blob with the highest maximum frequency, which is the P-cluster.
    """

    # Known P-cluster key for M1 through M4. First in discovery chain.
    _KNOWN_P_CLUSTER_KEY = "voltage-states5-sram"

    def __init__(self):
        # Run discovery once at init; cache result for lifetime of object
        self._pmgr_props = self._load_pmgr_properties()
        self._freq_table: Optional[List[int]] = None
        self._key_used: Optional[str] = None
        self._freq_table = self._discover()

    @property
    def key_used(self) -> Optional[str]:
        """The voltage-states key that produced the frequency table, or None."""
        return self._key_used

    def get_frequency_table(self) -> Optional[List[int]]:
        """Return P-cluster DVFS frequencies as List[int] in MHz, sorted ascending.

        Returns None if discovery failed entirely. Caller must handle None
        and degrade gracefully (PAC-4).

        Returns:
            List of integer frequencies in MHz sorted ascending,
            e.g. [600, 828, 1056, ..., 3036] for M1 Pro P-cluster.
            None if ioreg is unavailable or no valid blob was found.
        """
        return self._freq_table

    def _discover(self) -> Optional[List[int]]:
        """Three-step discovery chain for the P-cluster frequency table.

        Step 1: Try the known key (voltage-states5-sram), M1-M4.
        Step 2: Heuristic scan — enumerate all voltage-states*-sram keys
                and select the one with the highest max frequency.
        Step 3: Optional sysctl cross-check for validation/logging.
                Silently skipped if sysctl key is unavailable (M1 Pro).

        Returns the discovered frequency table or None.
        """
        if self._pmgr_props is None:
            logger.warning(
                "DVFSFrequencyProvider: pmgr properties unavailable, "
                "IOReport frequency reader will fall back"
            )
            return None

        # Step 1: try the known P-cluster key for M1-M4
        blob = self._pmgr_props.get(self._KNOWN_P_CLUSTER_KEY)
        if blob:
            freqs = self._parse_voltage_states_blob(blob)
            if freqs:
                self._key_used = self._KNOWN_P_CLUSTER_KEY
                logger.debug(
                    "DVFSFrequencyProvider: found P-cluster table via known key "
                    "'%s': %s MHz",
                    self._KNOWN_P_CLUSTER_KEY, freqs,
                )
                return freqs

        # Step 2: heuristic scan — select blob with highest max frequency
        # (P-cluster always has higher max than E-cluster or GPU on M-series)
        candidates = {}
        for key, val in self._pmgr_props.items():
            if (key.startswith("voltage-states")
                    and "sram" in key
                    and isinstance(val, bytes)):
                freqs = self._parse_voltage_states_blob(val)
                if freqs:
                    candidates[key] = freqs

        if not candidates:
            logger.warning(
                "DVFSFrequencyProvider: no voltage-states*-sram blobs found "
                "in pmgr properties. New chip variant? Keys present: %s",
                [k for k in self._pmgr_props if k.startswith("voltage-states")]
            )
            return None

        # Highest max freq = P-cluster on all known M-series chips
        best_key = max(candidates, key=lambda k: max(candidates[k]))
        best_freqs = candidates[best_key]
        self._key_used = best_key
        logger.info(
            "DVFSFrequencyProvider: heuristic selected key '%s' "
            "(max %d MHz) from %d candidates",
            best_key, max(best_freqs), len(candidates),
        )

        # Step 3: optional sysctl cross-validation
        # Confirms selection is correct; silently skipped if key absent
        sysctl_max = self._get_sysctl_p_freq_max()
        if sysctl_max is not None:
            discovered_max = max(best_freqs)
            # Allow 5% tolerance for rounding / MHz vs Hz conversion
            tolerance = sysctl_max * 0.05
            if abs(discovered_max - sysctl_max) > tolerance:
                logger.warning(
                    "DVFSFrequencyProvider: sysctl max (%d MHz) differs from "
                    "discovered max (%d MHz) by more than 5%%. "
                    "Key '%s' may not be P-cluster. Verify on this chip.",
                    sysctl_max, discovered_max, best_key,
                )
            else:
                logger.debug(
                    "DVFSFrequencyProvider: sysctl cross-check passed "
                    "(%d MHz vs %d MHz discovered)",
                    sysctl_max, discovered_max,
                )

        return best_freqs

    def _load_pmgr_properties(self):
        """Load the pmgr IORegistry node properties as a Python dict.

        Uses ioreg -a (plist output) to get the power manager device node.
        This is the same node that powermetrics reads for DVFS tables.

        Returns:
            dict of pmgr properties, or None if ioreg fails.
        """
        try:
            result = subprocess.run(
                ["ioreg", "-a", "-r", "-d", "1", "-n", "pmgr"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.warning(
                    "DVFSFrequencyProvider: ioreg returned %d",
                    result.returncode,
                )
                return None

            plist = plistlib.loads(result.stdout)
            # ioreg -a returns a list; pmgr node is the first entry
            if isinstance(plist, list) and len(plist) > 0:
                return plist[0]

            logger.warning(
                "DVFSFrequencyProvider: ioreg output was not a list "
                "or was empty"
            )
            return None

        except Exception as e:
            logger.warning(
                "DVFSFrequencyProvider: ioreg/plist failed: %s", e
            )
            return None

    @staticmethod
    def _parse_voltage_states_blob(blob: bytes) -> Optional[List[int]]:
        """Parse a voltage-states binary blob into a frequency list.

        Each record is 8 bytes: (freq_hz: u32le, voltage_mv: u32le).
        Skips zero-frequency entries (padding/sentinel values).
        Deduplicates and sorts result ascending.

        Args:
            blob: raw bytes from IORegistry property value.

        Returns:
            Sorted deduplicated list of frequencies in MHz,
            or None if blob is malformed or empty.
        """
        if not blob or len(blob) < 8:
            return None

        freqs = []
        num_records = len(blob) // 8
        for i in range(num_records):
            offset = i * 8
            freq_hz, _voltage_mv = struct.unpack_from("<II", blob, offset)
            if freq_hz > 0:
                freq_mhz = freq_hz // 1_000_000
                if freq_mhz > 0:
                    freqs.append(freq_mhz)

        if not freqs:
            return None

        return sorted(set(freqs))

    @staticmethod
    def _get_sysctl_p_freq_max() -> Optional[int]:
        """Get P-cluster max frequency from sysctl for optional validation.

        NOTE: hw.perflevel0.freq_max does NOT exist on all Apple Silicon
        Macs. On M1 Pro (macOS Sequoia 15.x) it is absent. The fallback
        key hw.cpufrequency_max reports the overall CPU max frequency,
        which on Apple Silicon equals the P-cluster max.

        If neither key exists, returns None and the caller skips
        sysctl cross-validation silently. Discovery still works without it.

        Key priority:
          1. hw.perflevel0.freq_max  (per-performance-level, newer macOS)
          2. hw.cpufrequency_max    (legacy key, broadly available)

        Returns:
            P-cluster max frequency in MHz, or None if unavailable.
        """
        keys_to_try = [
            "hw.perflevel0.freq_max",
            "hw.cpufrequency_max",
        ]
        for key in keys_to_try:
            try:
                result = subprocess.run(
                    ["sysctl", "-n", key],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    val = int(result.stdout.strip())
                    # sysctl returns Hz on most versions; convert if needed
                    if val > 100_000:
                        return val // 1_000_000
                    return val
            except Exception:
                # Key absent or parse error; try next key
                continue

        return None
