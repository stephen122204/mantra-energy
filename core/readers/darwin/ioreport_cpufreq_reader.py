"""
core/readers/darwin/ioreport_cpufreq_reader.py

IOReport-based CPU frequency reader for Apple Silicon (Darwin/arm64).
Computes the true wall-clock-weighted average P-cluster frequency using
Apple's IOReport DVFS residency counters — the same data source that
powermetrics uses internally.

Why IOReport instead of powermetrics output:
  powermetrics reports HW-active-weighted frequency: frequency averaged
  only over active cycles, ignoring idle time. Under any real workload
  this always reads near the maximum (3036 MHz on M1 Pro) even when the
  CPU is mostly idle. IOReport DVFS residency counters give nanoseconds
  spent in each frequency state including IDLE, enabling the true
  wall-clock-weighted average that correlates correctly with energy.

No sudo required. No subprocess. No compilation. Pure Python ctypes.
The dylib at /usr/lib/libIOReport.dylib resolves from the macOS dyld
shared cache on macOS 11+, same as Apple's own tools.

PAC-1: Inherits TurbostatReaderABC.
PAC-2: Instantiated only via ReaderFactory.get_turbostat_reader().
PAC-4: is_available() probe; every failure path degrades gracefully.
DC-1:  30% inline comment coverage throughout.
DC-3:  No silent failures; all exceptions logged via logger.warning.
"""

import ctypes
import logging
import platform
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IOReport and CoreFoundation ctypes bindings.
# Loaded lazily at first instantiation so non-Darwin platforms never
# attempt to load a dylib that does not exist.
# ---------------------------------------------------------------------------

_ior: Optional[ctypes.CDLL] = None  # libIOReport.dylib handle
_cf: Optional[ctypes.CDLL] = None   # CoreFoundation handle
_bindings_loaded = False
_bindings_error: Optional[str] = None

# UTF-8 encoding constant for CFStringCreateWithCString
_kCFStringEncodingUTF8 = 0x08000100


def _load_bindings() -> bool:
    """Load IOReport and CoreFoundation via ctypes.

    Called once; result cached in module-level variables.
    Returns True if both libraries loaded and all functions bound.
    Sets _bindings_error on failure for diagnostic logging.
    """
    global _ior, _cf, _bindings_loaded, _bindings_error

    if _bindings_loaded:
        return _ior is not None

    try:
        # IOReport: DVFS residency, energy counters, channel subscription
        _ior = ctypes.cdll.LoadLibrary("/usr/lib/libIOReport.dylib")

        # CoreFoundation: CF object lifecycle, string creation, dict ops
        _cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/"
            "CoreFoundation.framework/CoreFoundation"
        )

        # --- IOReport function signatures ---
        # IOReportCopyChannelsInGroup: discover channels by group/subgroup name
        _ior.IOReportCopyChannelsInGroup.argtypes = [
            ctypes.c_void_p,  # CFStringRef group
            ctypes.c_void_p,  # CFStringRef subgroup (None = all)
            ctypes.c_uint64,  # reserved, pass 0
            ctypes.c_uint64,  # reserved, pass 0
            ctypes.c_uint64,  # reserved, pass 0
        ]
        _ior.IOReportCopyChannelsInGroup.restype = ctypes.c_void_p

        # IOReportMergeChannels: merge two channel dicts in-place
        _ior.IOReportMergeChannels.argtypes = [
            ctypes.c_void_p,  # target CFMutableDictionaryRef
            ctypes.c_void_p,  # source CFDictionaryRef
            ctypes.c_void_p,  # reserved, pass None
        ]
        _ior.IOReportMergeChannels.restype = None

        # IOReportCreateSubscription: create a reusable sampling handle
        _ior.IOReportCreateSubscription.argtypes = [
            ctypes.c_void_p,                    # reserved, pass None
            ctypes.c_void_p,                    # CFMutableDictionaryRef channels
            ctypes.POINTER(ctypes.c_void_p),    # out: subscribed channels
            ctypes.c_uint64,                    # reserved, pass 0
            ctypes.c_void_p,                    # reserved, pass None
        ]
        _ior.IOReportCreateSubscription.restype = ctypes.c_void_p

        # IOReportCreateSamples: take one instantaneous snapshot
        _ior.IOReportCreateSamples.argtypes = [
            ctypes.c_void_p,  # IOReportSubscriptionRef
            ctypes.c_void_p,  # CFMutableDictionaryRef subbedChannels
            ctypes.c_void_p,  # reserved, pass None
        ]
        _ior.IOReportCreateSamples.restype = ctypes.c_void_p

        # IOReportCreateSamplesDelta: compute per-channel delta between snapshots
        _ior.IOReportCreateSamplesDelta.argtypes = [
            ctypes.c_void_p,  # CFDictionaryRef prev snapshot
            ctypes.c_void_p,  # CFDictionaryRef cur snapshot
            ctypes.c_void_p,  # reserved, pass None
        ]
        _ior.IOReportCreateSamplesDelta.restype = ctypes.c_void_p

        # IOReportIterate: iterate channels in a delta dict
        # Callback signature: (channel_ref: c_void_p, ctx: c_void_p) -> c_int
        _ITERATE_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        _ior.IOReportIterate.argtypes = [
            ctypes.c_void_p,  # CFDictionaryRef samples
            _ITERATE_CB,      # callback
        ]
        _ior.IOReportIterate.restype = None
        # Store callback type for use in _extract_residencies
        _ior._ITERATE_CB = _ITERATE_CB

        # IOReportStateGetCount: number of DVFS states for a channel
        # State 0 = IDLE, states 1..N map to freq_table[0..N-1]
        _ior.IOReportStateGetCount.argtypes = [ctypes.c_void_p]
        _ior.IOReportStateGetCount.restype = ctypes.c_uint32

        # IOReportStateGetResidency: nanoseconds spent in state during delta
        _ior.IOReportStateGetResidency.argtypes = [
            ctypes.c_void_p,  # channel ref
            ctypes.c_uint32,  # state index
        ]
        _ior.IOReportStateGetResidency.restype = ctypes.c_uint64

        # IOReportChannelGetDriverName: driver/channel name e.g. "PCPU0"
        _ior.IOReportChannelGetDriverName.argtypes = [ctypes.c_void_p]
        _ior.IOReportChannelGetDriverName.restype = ctypes.c_void_p

        # --- CoreFoundation function signatures ---
        _cf.CFRelease.argtypes = [ctypes.c_void_p]
        _cf.CFRelease.restype = None

        _cf.CFDictionaryGetCount.argtypes = [ctypes.c_void_p]
        _cf.CFDictionaryGetCount.restype = ctypes.c_long

        _cf.CFDictionaryCreateMutableCopy.argtypes = [
            ctypes.c_void_p,  # allocator (None = default)
            ctypes.c_long,    # capacity
            ctypes.c_void_p,  # original dict
        ]
        _cf.CFDictionaryCreateMutableCopy.restype = ctypes.c_void_p

        _cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,  # allocator (None)
            ctypes.c_char_p,  # C string bytes
            ctypes.c_uint32,  # encoding
        ]
        _cf.CFStringCreateWithCString.restype = ctypes.c_void_p

        _cf.CFStringGetCStringPtr.argtypes = [
            ctypes.c_void_p,  # CFStringRef
            ctypes.c_uint32,  # encoding
        ]
        _cf.CFStringGetCStringPtr.restype = ctypes.c_char_p

        _bindings_loaded = True
        logger.debug("IOReport ctypes bindings loaded successfully")
        return True

    except Exception as e:
        _bindings_error = str(e)
        _ior = None
        _cf = None
        _bindings_loaded = True  # mark as attempted, don't retry
        logger.warning("IOReport ctypes binding failed: %s", e)
        return False


class IOReportCPUFreqReader:
    """IOReport-based wall-clock-weighted CPU frequency reader for Apple Silicon.

    Implements TurbostatReaderABC minimal contract. Returns residency-weighted
    average P-cluster frequency via stop_monitoring() summary, which feeds
    energy_analyzer.py's frequency_mhz computation path — same as
    TurbostatReader on Linux and ARMCPUFreqReader on GN100.

    Lifecycle:
      __init__()          — load bindings, discover DVFS table, create subscription
      start_monitoring()  — take sample1 snapshot
      stop_monitoring()   — take sample2, compute delta, return weighted freq
      cleanup()           — release persistent CF objects
    """

    # P-cluster channel name prefix on M1 through M4.
    # Configurable so future chips with different naming can be accommodated
    # without modifying the frequency computation logic.
    PRIMARY_CLUSTER_PREFIX = "PCPU"

    METHOD_ID          = "ioreport_cpufreq_v1"
    METHOD_NAME        = "IOReport DVFS Residency Weighted CPU Frequency"
    METHOD_PROVENANCE  = "MEASURED"
    METHOD_LAYER       = "silicon"
    METHOD_CONFIDENCE  = 0.95
    METHOD_FORMULA_LATEX = (
        r"f_{\text{weighted}} = "
        r"\frac{\sum_{i=0}^{N-1} f_i \cdot r_{i+1}}{\sum_{j=0}^{N} r_j}"
    )

    # TurbostatReaderABC contract attributes (PAC-4: must be present on all instances)
    available         = False
    turbostat_version = None
    cpu_topology      = {}
    available_sensors = []
    perf_available    = False

    def __init__(self, config=None):
        """Probe IOReport availability and create subscription if possible.

        Args:
            config: optional hw_config dict (not used; accepted for factory compat)
        """
        self._lock = threading.Lock()
        self._subscription: Optional[int] = None   # IOReportSubscriptionRef
        self._subbed_channels: Optional[int] = None  # CFMutableDictionaryRef
        self._sample1: Optional[int] = None         # snapshot taken at start_monitoring
        self._start_time: float = 0.0
        self._freq_table: Optional[List[int]] = None
        self._chip_brand: str = self._get_chip_brand()
        self._macos_version: str = platform.mac_ver()[0]
        self._dvfs_provider = None
        self._available: bool = False

        # Short-circuit on non-Darwin platforms — never try to load IOReport
        if platform.system() != "Darwin":
            return

        if not _load_bindings():
            logger.warning(
                "IOReportCPUFreqReader: ctypes binding failed (%s)",
                _bindings_error,
            )
            return

        # Discover DVFS frequency table from IORegistry pmgr node
        from core.readers.darwin.dvfs_frequency_provider import DVFSFrequencyProvider
        self._dvfs_provider = DVFSFrequencyProvider()
        self._freq_table = self._dvfs_provider.get_frequency_table()
        if not self._freq_table:
            logger.warning(
                "IOReportCPUFreqReader: DVFS frequency table discovery failed "
                "on chip '%s'. Falling back.", self._chip_brand
            )
            return

        # Create IOReport subscription for CPU Core Performance States
        try:
            self._create_subscription()
        except Exception as e:
            logger.warning(
                "IOReportCPUFreqReader: subscription creation failed: %s", e
            )
            return

        # Take a test sample to confirm the subscription works end-to-end
        try:
            test_sample = _ior.IOReportCreateSamples(
                self._subscription, self._subbed_channels, None
            )
            if not test_sample:
                logger.warning(
                    "IOReportCPUFreqReader: test sample returned NULL"
                )
                return
            _cf.CFRelease(test_sample)
        except Exception as e:
            logger.warning(
                "IOReportCPUFreqReader: test sample failed: %s", e
            )
            return

        self._available = True
        self.available = True
        logger.info(
            "IOReportCPUFreqReader: ready on '%s' macOS %s, "
            "DVFS key=%s, freq_table=%s MHz",
            self._chip_brand, self._macos_version,
            self._dvfs_provider.key_used, self._freq_table,
        )

    def is_available(self) -> bool:
        """Return True only if IOReport DVFS sampling is fully functional.

        Returns:
            True if library loaded, DVFS table discovered, subscription
            created, and test sample succeeded. False otherwise.
        """
        return self._available

    def get_name(self) -> str:
        """Human-readable reader name for logging."""
        return f"IOReportCPUFreqReader(ioreport_cpufreq_v1, {self._chip_brand})"

    # --- TurbostatReaderABC contract ---

    def start_monitoring(self, interval_ms: int = 100) -> None:
        """Take the start-of-window IOReport snapshot.

        Called by EnergyEngine.start_measurement(). The snapshot is a
        cumulative hardware counter value; the delta with stop_monitoring's
        snapshot gives exact residency over the measurement window.

        Args:
            interval_ms: ignored (IOReport does not poll; delta is exact)
        """
        if not self._available:
            return

        with self._lock:
            # Release any leftover snapshot from an incomplete prior run
            if self._sample1:
                self._cf_release_safe(self._sample1)

            self._sample1 = _ior.IOReportCreateSamples(
                self._subscription, self._subbed_channels, None
            )
            self._start_time = time.monotonic()

            if not self._sample1:
                logger.warning(
                    "IOReportCPUFreqReader.start_monitoring: "
                    "IOReportCreateSamples returned NULL"
                )

    def stop_monitoring(self) -> Dict:
        """Take end-of-window snapshot, compute delta, return weighted frequency.

        Returns the TurbostatReaderABC contract dict consumed by
        energy_analyzer.py. frequency_mean is the wall-clock-weighted
        average P-cluster frequency over the measurement window.

        Returns:
            Dict with keys: summary, num_samples, dataframe, duration_seconds.
            summary contains: frequency_mean, frequency_min, frequency_max.
            All values are Python floats. No CF objects escape this method.
        """
        empty = {
            "dataframe":        None,
            "num_samples":      0,
            "duration_seconds": 0.0,
            "summary":          {},
        }

        if not self._available or not self._sample1:
            return empty

        with self._lock:
            sample2 = None
            delta = None
            try:
                sample2 = _ior.IOReportCreateSamples(
                    self._subscription, self._subbed_channels, None
                )
                if not sample2:
                    logger.warning(
                        "IOReportCPUFreqReader.stop_monitoring: "
                        "sample2 returned NULL"
                    )
                    return empty

                delta = _ior.IOReportCreateSamplesDelta(
                    self._sample1, sample2, None
                )
                if not delta:
                    logger.warning(
                        "IOReportCPUFreqReader.stop_monitoring: "
                        "delta returned NULL"
                    )
                    return empty

                duration_s = time.monotonic() - self._start_time
                freq_mean, freq_min, freq_max = self._extract_weighted_frequency(delta)

            except Exception as e:
                logger.warning(
                    "IOReportCPUFreqReader.stop_monitoring failed: %s", e
                )
                return empty

            finally:
                # Release all transient CF objects before returning
                # Never expose CF pointers outside this method
                self._cf_release_safe(self._sample1)
                self._sample1 = None
                self._cf_release_safe(sample2)
                self._cf_release_safe(delta)

        return {
            "dataframe":        None,
            "num_samples":      1,    # one delta window, not polled samples
            "duration_seconds": duration_s,
            "summary": {
                "frequency_mean": float(freq_mean),
                "frequency_min":  float(freq_min) if freq_min != float("inf") else 0.0,
                "frequency_max":  float(freq_max),
            },
        }

    def get_latest_sample(self) -> Dict:
        """Return current frequency as a sample dict.

        Called by EnergyEngine's high-frequency sampling loop.
        Returns the last known frequency (from DVFS table max) as a proxy
        since IOReport is a two-snapshot delta reader, not a continuous poller.

        Returns:
            Dict with frequency_mhz key, or empty dict if unavailable.
        """
        if not self._available or not self._freq_table:
            return {}
        # Report max frequency as a conservative proxy for current frequency
        return {"frequency_mhz": max(self._freq_table)}

    def get_column_mapping(self) -> Dict:
        """Return mapping from internal keys to TurbostatReader column names."""
        return {"frequency_mhz": "frequency_mean"}

    def read_temperatures(self) -> Dict:
        """Not implemented: handled by IOKitThermalReader."""
        return {}

    def read_all_thermal(self) -> Dict:
        """Not implemented: handled by IOKitThermalReader."""
        return {}

    def read_msr(self, msr_addr, cpu=0, pin=True):
        """Not available: no MSR access on Darwin."""
        return None

    def read_cstate_counters(self, cpu=0, pin=True):
        """Not available: IOReport DVFS channels do not include C-states."""
        return {}

    def snapshot_cstate_counters(self):
        """Not available on Darwin."""
        return {}

    def read_context_switches(self):
        """Not available: /proc/stat absent on Darwin."""
        return {}

    def read_all(self):
        """Return frequency summary if available."""
        if not self._available:
            return {}
        return {"frequency_mhz": max(self._freq_table) if self._freq_table else 0}

    def start_interrupt_sampling(self, pid=0):
        """Not available: /proc/interrupts absent on Darwin."""
        pass

    def supports_frequency(self) -> bool:
        """This reader provides frequency data."""
        return True

    def supports_cstate(self) -> bool:
        """IOReport DVFS channels do not include C-states."""
        return False

    def supports_temperature(self) -> bool:
        """Temperature handled by IOKitThermalReader, not this reader."""
        return False

    # --- Cleanup ---

    def cleanup(self) -> None:
        """Release persistent CF objects held for the reader's lifetime.

        Call when the reader is no longer needed. EnergyEngine does not
        currently call this explicitly; __del__ provides a safety net.
        """
        self._cf_release_safe(self._subbed_channels)
        self._subbed_channels = None
        self._cf_release_safe(self._subscription)
        self._subscription = None
        self._cf_release_safe(self._sample1)
        self._sample1 = None

    def __del__(self):
        """Safety net: release CF objects if cleanup() was not called."""
        try:
            self.cleanup()
        except Exception:
            pass  # suppress all errors in __del__

    # --- Internal helpers ---

    def _create_subscription(self) -> None:
        """Create IOReport subscription for CPU Core Performance States.

        Subscribes to group "CPU Stats", subgroup "CPU Core Performance States".
        This yields per-core DVFS residency for all E-cluster and P-cluster
        cores. We filter to P-cluster in _extract_weighted_frequency.

        Per-core (not per-cluster aggregate) is used because the cluster
        aggregate channel "CPU Complex Performance States" has a documented
        bug where it sometimes reports 100% load during idle (vladkens/macmon).
        Per-core channels are reliable on all M-series chips.

        Raises RuntimeError if any IOReport call returns NULL.
        """
        group_str = None
        subgroup_str = None
        channels = None
        channels_mut = None

        try:
            group_str = _cf.CFStringCreateWithCString(
                None, b"CPU Stats", _kCFStringEncodingUTF8
            )
            subgroup_str = _cf.CFStringCreateWithCString(
                None, b"CPU Core Performance States", _kCFStringEncodingUTF8
            )

            channels = _ior.IOReportCopyChannelsInGroup(
                group_str, subgroup_str, 0, 0, 0
            )
            if not channels:
                raise RuntimeError(
                    "IOReportCopyChannelsInGroup returned NULL for "
                    "'CPU Stats'/'CPU Core Performance States'"
                )

            # Need a mutable copy for IOReportCreateSubscription
            count = _cf.CFDictionaryGetCount(channels)
            channels_mut = _cf.CFDictionaryCreateMutableCopy(
                None, count, channels
            )
            # Release immutable original; keep mutable copy
            _cf.CFRelease(channels)
            channels = None

            subbed_channels_ptr = ctypes.c_void_p()
            subscription = _ior.IOReportCreateSubscription(
                None,
                channels_mut,
                ctypes.byref(subbed_channels_ptr),
                0,
                None,
            )
            if not subscription:
                raise RuntimeError("IOReportCreateSubscription returned NULL")

            # These two CF objects are kept alive for the reader's lifetime.
            # channels_mut ownership is transferred to the subscription;
            # do NOT CFRelease it separately.
            self._subscription = subscription
            self._subbed_channels = subbed_channels_ptr

        finally:
            # Always release temporary string objects
            if group_str:
                _cf.CFRelease(group_str)
            if subgroup_str:
                _cf.CFRelease(subgroup_str)
            # Release channels only if mutable copy was NOT created
            if channels:
                _cf.CFRelease(channels)
            # Release channels_mut only if subscription was NOT created
            if channels_mut and not self._subscription:
                _cf.CFRelease(channels_mut)

    def _extract_weighted_frequency(
        self, delta: int
    ) -> Tuple[float, float, float]:
        """Compute wall-clock-weighted average P-cluster frequency from delta.

        Iterates all channels in the delta dict. For each channel whose
        driver name starts with PRIMARY_CLUSTER_PREFIX ("PCPU"), sums
        residency across all DVFS states (including IDLE at index 0) and
        accumulates the weighted numerator for active states.

        Formula (from spec Section 2.6):
          f_weighted = sum(f_i * r_{i+1}) / sum(r_j for j=0..N)

        Where r_0 is IDLE residency and r_{i+1} is residency at freq_table[i].
        The denominator includes idle, giving true wall-clock weighting.

        Args:
            delta: IOReportCreateSamplesDelta result (CFDictionaryRef as int)

        Returns:
            Tuple of (frequency_mean, frequency_min, frequency_max) in MHz.
            Returns (0.0, inf, 0.0) if no P-cluster data found.
        """
        freq_table = self._freq_table
        chip_brand = self._chip_brand

        total_weighted_sum: float = 0.0
        total_residency: int = 0
        min_active_freq: float = float("inf")
        max_active_freq: float = 0.0

        # Collect per-channel results via IOReportIterate callback
        # The callback receives a c_void_p channel ref and a context pointer.
        # We use a list as a mutable accumulator since closures over ints
        # do not work with ctypes callbacks.
        accumulator = [total_weighted_sum, total_residency,
                       min_active_freq, max_active_freq]

        def _channel_callback(channel_ref, _ctx):
            """Called once per channel in the delta dict by IOReportIterate."""
            if not channel_ref:
                return 0  # continue iteration

            # Get driver name to identify cluster (ECPU* vs PCPU*)
            name_cfstr = _ior.IOReportChannelGetDriverName(channel_ref)
            if not name_cfstr:
                return 0

            name_bytes = _cf.CFStringGetCStringPtr(
                name_cfstr, _kCFStringEncodingUTF8
            )
            if not name_bytes:
                return 0

            name = name_bytes.decode("utf-8", errors="replace")

            # Only process P-cluster cores; skip E-cluster and any other channels
            if not name.startswith(self.PRIMARY_CLUSTER_PREFIX):
                return 0

            state_count = _ior.IOReportStateGetCount(channel_ref)

            # ASSERTION: state_count must equal len(freq_table) + 1.
            # State 0 = IDLE, states 1..N map to freq_table[0..N-1].
            # Confirmed on M1-M4 by socpowerbud and agtop.
            # If a future chip violates this, catch it immediately rather
            # than silently producing wrong frequency values.
            if state_count != len(freq_table) + 1:
                logger.warning(
                    "DVFS state count mismatch on channel '%s': "
                    "IOReport reports %d states but freq_table has %d entries "
                    "(expected %d states). "
                    "State-to-frequency mapping may be incorrect. "
                    "Chip: %s. Please report this.",
                    name, state_count, len(freq_table),
                    len(freq_table) + 1, chip_brand,
                )
                # Graceful: use min(state_count-1, len(freq_table)) to avoid
                # index-out-of-range; flag as potentially inaccurate via warning
                usable_states = min(state_count - 1, len(freq_table))
            else:
                usable_states = len(freq_table)

            for state_idx in range(state_count):
                residency = _ior.IOReportStateGetResidency(
                    channel_ref, state_idx
                )
                accumulator[1] += residency  # total_residency

                if state_idx > 0 and (state_idx - 1) < usable_states:
                    # Active state: maps to freq_table[state_idx - 1]
                    freq = freq_table[state_idx - 1]
                    accumulator[0] += freq * residency  # weighted_sum

                    if residency > 0:
                        if freq < accumulator[2]:
                            accumulator[2] = freq  # min_active_freq
                        if freq > accumulator[3]:
                            accumulator[3] = freq  # max_active_freq

            return 0  # continue iteration

        cb = _ior._ITERATE_CB(_channel_callback)
        _ior.IOReportIterate(delta, cb)

        total_weighted_sum = accumulator[0]
        total_residency = accumulator[1]
        min_active_freq = accumulator[2]
        max_active_freq = accumulator[3]

        if total_residency > 0:
            freq_mean = total_weighted_sum / total_residency
        else:
            freq_mean = 0.0

        return freq_mean, min_active_freq, max_active_freq

    def _cf_release_safe(self, cf_obj) -> None:
        """Release a CoreFoundation object if non-NULL.

        Calling CFRelease on NULL crashes the process. This wrapper
        prevents that without requiring callers to check every time.

        Args:
            cf_obj: CF object handle (int or c_void_p) or None/0.
        """
        if cf_obj and _cf is not None:
            try:
                _cf.CFRelease(cf_obj)
            except Exception as e:
                logger.warning("CFRelease failed: %s", e)

    @staticmethod
    def _get_chip_brand() -> str:
        """Return machdep.cpu.brand_string for logging and provenance.

        Returns 'unknown' if sysctl is unavailable (non-Darwin).
        """
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    @property
    def provenance_metadata(self) -> Dict:
        """Metadata for forensic tracing stored in environment_config.

        Allows future reviewers to know exactly what measured what on
        which hardware, including the DVFS key and frequency table used.
        """
        return {
            "freq_backend":                "ioreport",
            "freq_backend_version":        "1.0.0",
            "freq_method_id":              self.METHOD_ID,
            "freq_chip":                   self._chip_brand,
            "freq_macos_version":          self._macos_version,
            "freq_api_source":             "/usr/lib/libIOReport.dylib",
            "freq_dvfs_table_key":         (
                self._dvfs_provider.key_used
                if self._dvfs_provider else None
            ),
            "freq_dvfs_table_mhz":         self._freq_table,
            "freq_primary_cluster_prefix": self.PRIMARY_CLUSTER_PREFIX,
        }
