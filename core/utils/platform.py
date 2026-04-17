#!/usr/bin/env python3
"""
================================================================================
PLATFORM DETECTOR — OS, Architecture & Measurement Mode Detection
================================================================================

Purpose:
    Single source of truth for what hardware this machine can measure.
    Reads BOTH config files written by the detection scripts:
        config/hw_config.json     (written by detect_hardware.py)
        config/environment.json   (written by detect_environment.py)

    Combines hardware capabilities with environment context to determine
    the correct measurement mode for the ReaderFactory.

Measurement Modes:
    MEASURED  — Direct hardware counters (RAPL on x86_64, IOKit on macOS)
    INFERRED  — No hardware access; ML model estimation (ARM VM / aarch64)
    LIMITED   — Unknown platform; returns zeros with logged warning

Run Order (must be respected):
    1. python scripts/detect_environment.py  → config/environment.json
    2. python scripts/detect_hardware.py     → config/hw_config.json
    3. (automatic) PlatformDetector reads both → config/platform.json

Container Impact on Mode:
    Docker/containerd can block RAPL sysfs reads even on x86_64.
    If container_runtime is set in environment.json AND RAPL paths exist
    in hw_config.json, PlatformDetector logs a warning — RAPLReader will
    confirm accessibility at init time via _validate_path().

Author: Deepak Panigrahy
================================================================================
"""

import json
import logging
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Mode constants — import these throughout the codebase (not strings)
# ------------------------------------------------------------------
MEASURED = "MEASURED"   # Real hardware counters available
INFERRED = "INFERRED"   # No hardware access; use ML estimation
LIMITED  = "LIMITED"    # Unknown / unsupported platform; return zeros


# ============================================================================
# DATA CLASS — PlatformCapabilities
# ============================================================================

@dataclass
class PlatformCapabilities:
    """
    Immutable snapshot of what this machine can measure.

    Populated once at startup by PlatformDetector.detect() and consumed
    by ReaderFactory to select the correct reader implementations.

    Hardware flags (from hw_config.json):
        has_rapl, has_msr, has_thermal, has_turbostat, rapl_domains

    Environment flags (from environment.json):
        torch_available, in_container, python_version, env_hash

    Attributes:
        os:               OS string ('Linux', 'Darwin', 'Windows')
        arch:             CPU architecture ('x86_64', 'aarch64', 'arm64')
        measurement_mode: One of MEASURED / INFERRED / LIMITED
        has_rapl:         True if hw_config.rapl.paths is non-empty
        has_msr:          True if hw_config.msr.devices is non-empty
        has_perf:         True if perf --version succeeds at startup
        has_turbostat:    True if hw_config.turbostat.available is True
        has_thermal:      True if hw_config.thermal.paths is non-empty
        has_iokit:        True on macOS (IOKit always present)
        rapl_domains:     Domain names e.g. ['package-0', 'core', 'uncore']
        virtualization:   'kvm', 'vmware', None (bare metal), etc.
        hostname:         Hostname from hw_config metadata
        torch_available:  True if torch installed (needed by EnergyEstimator ML)
        in_container:     True if running inside Docker/containerd/podman/k8s
        container_runtime: Runtime name or None
        python_version:   Python version string from environment.json
        env_hash:         Environment fingerprint for provenance tracking
        kernel_version:   Kernel release string
    """
    # --- Hardware (from hw_config.json) ---
    os:               str           = "Unknown"
    arch:             str           = "Unknown"
    measurement_mode: str           = LIMITED
    has_rapl:         bool          = False
    has_msr:          bool          = False
    has_perf:         bool          = False
    has_turbostat:    bool          = False
    has_thermal:      bool          = False
    has_iokit:        bool          = False
    rapl_domains:     List[str]     = field(default_factory=list)
    virtualization:   Optional[str] = None
    hostname:         str           = "unknown"

    # --- Environment (from environment.json) ---
    torch_available:   bool          = False   # EnergyEstimator needs torch for ML
    in_container:      bool          = False   # containers can block RAPL access
    container_runtime: Optional[str] = None    # 'docker', 'containerd', 'podman', etc.
    python_version:    str           = "unknown"
    env_hash:          str           = "unknown"  # provenance fingerprint
    kernel_version:    str           = "unknown"

    def to_dict(self) -> dict:
        """
        Serialise to plain dict for JSON output (platform.json).

        Returns:
            dict: All fields as JSON-serialisable types.
        """
        return asdict(self)

    def summary(self) -> str:
        """
        Return a compact one-line summary for logging and CLI output.

        Returns:
            str: e.g. 'Linux x86_64 | MEASURED | RAPL:3 MSR:True container:False'
        """
        rapl_count = len(self.rapl_domains)
        return (
            f"{self.os} {self.arch} | {self.measurement_mode} | "
            f"RAPL:{rapl_count} MSR:{self.has_msr} "
            f"perf:{self.has_perf} container:{self.in_container} "
            f"torch:{self.torch_available}"
        )


# ============================================================================
# PLATFORM DETECTOR
# ============================================================================

class PlatformDetector:
    """
    Reads hw_config.json + environment.json to produce PlatformCapabilities.

    Responsibilities:
        - Load and parse both config files (hw_config + environment)
        - Derive boolean feature flags from each
        - Apply decision tree to assign measurement_mode
        - Warn when container may block RAPL access
        - Persist result to config/platform.json for ReaderFactory

    Usage:
        detector = PlatformDetector()
        caps     = detector.detect()   # returns PlatformCapabilities
        detector.save(caps)            # writes config/platform.json
    """

    # Default paths relative to project root (where the process is started)
    HW_CONFIG_PATH    = Path("config/hw_config.json")
    ENV_CONFIG_PATH   = Path("config/environment.json")
    PLATFORM_OUT_PATH = Path("config/platform.json")

    def __init__(
        self,
        hw_config_path:    Optional[str] = None,
        env_config_path:   Optional[str] = None,
        platform_out_path: Optional[str] = None,
    ):
        """
        Initialise with optional path overrides (useful in tests).

        Args:
            hw_config_path:    Override path to hw_config.json.
            env_config_path:   Override path to environment.json.
            platform_out_path: Override output path for platform.json.
        """
        # Allow test overrides; fall back to class-level defaults
        self.hw_config_path    = Path(hw_config_path)    if hw_config_path    else self.HW_CONFIG_PATH
        self.env_config_path   = Path(env_config_path)   if env_config_path   else self.ENV_CONFIG_PATH
        self.platform_out_path = Path(platform_out_path) if platform_out_path else self.PLATFORM_OUT_PATH

        # Raw config dicts — populated lazily inside detect()
        self._hw_config:  dict = {}
        self._env_config: dict = {}

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def detect(self) -> PlatformCapabilities:
        """
        Run full platform detection and return PlatformCapabilities.

        Detection steps:
            1. Load hw_config.json  (hardware truth from detect_hardware.py)
            2. Load environment.json (software/container from detect_environment.py)
            3. Read live OS from platform module
            4. Derive hardware feature flags from hw_config
            5. Derive environment flags from environment.json
            6. Apply decision tree → measurement_mode
            7. Warn on container + RAPL combination
            8. Assemble and return PlatformCapabilities

        Returns:
            PlatformCapabilities: Fully populated. Falls back to LIMITED on error.
        """
        # Steps 1 & 2 — load both config files safely
        self._hw_config  = self._load_json(self.hw_config_path,  "hw_config.json")
        self._env_config = self._load_json(self.env_config_path, "environment.json")

        # Step 3 — OS from live env; arch from hw_config (more reliable in VMs)
        current_os   = platform.system()
        current_arch = self._hw_config.get("metadata", {}).get(
            "machine", platform.machine()   # fallback to live if json missing
        )

        # Step 4 — hardware flags from hw_config sections
        has_rapl      = self._check_rapl()
        has_msr       = self._check_msr()
        has_thermal   = self._check_thermal()
        has_turbostat = self._check_turbostat()
        has_perf      = self._check_perf()          # live probe — not in hw_config
        has_iokit     = (current_os == "Darwin")    # IOKit always present on macOS

        rapl_domains   = list(self._hw_config.get("rapl", {}).get("paths", {}).keys())
        virtualization = self._hw_config.get("system", {}).get("virtualization")
        hostname       = self._hw_config.get("metadata", {}).get("hostname", "unknown")

        # Step 5 — environment flags from environment.json
        torch_available   = self._env_config.get("torch_version") is not None
        container_runtime = self._env_config.get("container_runtime")  # None = bare metal
        in_container      = container_runtime is not None
        python_version    = self._env_config.get("python_version", "unknown")
        env_hash          = self._env_config.get("env_hash", "unknown")
        kernel_version    = self._env_config.get("kernel_version", "unknown")

        # Step 6 — apply decision tree
        mode = self._decide_mode(
            os_name      = current_os,
            arch         = current_arch,
            has_rapl     = has_rapl,
            has_iokit    = has_iokit,
            in_container = in_container,
        )

        # Step 7 — warn if container may silently block RAPL reads
        if in_container and has_rapl and mode == MEASURED:
            logger.warning(
                "Container runtime '%s' detected with RAPL paths present. "
                "RAPL sysfs reads may be blocked by container isolation. "
                "RAPLReader will verify accessibility at init time. "
                "Add --privileged flag or switch to INFERRED mode if reads fail.",
                container_runtime,
            )

        # Step 8 — assemble PlatformCapabilities
        caps = PlatformCapabilities(
            os                = current_os,
            arch              = current_arch,
            measurement_mode  = mode,
            has_rapl          = has_rapl,
            has_msr           = has_msr,
            has_perf          = has_perf,
            has_turbostat     = has_turbostat,
            has_thermal       = has_thermal,
            has_iokit         = has_iokit,
            rapl_domains      = rapl_domains,
            virtualization    = virtualization,
            hostname          = hostname,
            torch_available   = torch_available,
            in_container      = in_container,
            container_runtime = container_runtime,
            python_version    = python_version,
            env_hash          = env_hash,
            kernel_version    = kernel_version,
        )

        logger.info("Platform detected: %s", caps.summary())
        return caps

    def save(self, caps: PlatformCapabilities) -> None:
        """
        Persist PlatformCapabilities to config/platform.json.

        Args:
            caps: PlatformCapabilities returned by detect().
        """
        # Create config dir if it doesn't exist yet
        self.platform_out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.platform_out_path, "w") as f:
            json.dump(caps.to_dict(), f, indent=2)

        logger.info("Platform config written to %s", self.platform_out_path)

    # ------------------------------------------------------------------
    # DECISION LOGIC
    # ------------------------------------------------------------------

    @staticmethod
    def _decide_mode(
        os_name:      str,
        arch:         str,
        has_rapl:     bool,
        has_iokit:    bool,
        in_container: bool,
    ) -> str:
        """
        Apply measurement mode decision tree (first-match wins).

        Container note:
            We return MEASURED for containerised x86_64 + RAPL because
            RAPLReader._validate_path() catches blocked reads at init.
            Forcing INFERRED would break privileged containers that DO
            have RAPL access. The warning (step 7 above) alerts the user.

        Decision tree:
            Linux + x86_64 + RAPL  → MEASURED  (direct µJ counter)
            Linux + x86_64 no RAPL → INFERRED  (permissions/container issue)
            Linux + aarch64/arm64  → INFERRED  (ARM VM — no RAPL exists)
            Darwin (any arch)      → MEASURED  (IOKit real power sensor)
            Windows / unknown      → LIMITED   (no reliable counter)

        Args:
            os_name:      'Linux', 'Darwin', or 'Windows'
            arch:         'x86_64', 'aarch64', 'arm64', etc.
            has_rapl:     Whether RAPL sysfs paths were found
            has_iokit:    True on macOS
            in_container: True if running inside a container runtime

        Returns:
            str: One of MEASURED / INFERRED / LIMITED
        """
        is_linux = (os_name == "Linux")
        is_macos = (os_name == "Darwin")
        is_x86   = (arch == "x86_64")
        is_arm   = (arch in ("aarch64", "arm64"))

        if is_linux and is_x86 and has_rapl:
            return MEASURED     # best case: direct RAPL µJ counter

        if is_linux and is_x86 and not has_rapl:
            return INFERRED     # x86 without RAPL — permissions or container block

        if is_linux and is_arm:
            return INFERRED     # ARM VM — RAPL hardware does not exist

        if is_macos:
            return MEASURED     # IOKit real power sensor (W → µJ in reader)

        return LIMITED          # Windows, WSL, or unknown platform

    # ------------------------------------------------------------------
    # FEATURE FLAG HELPERS
    # ------------------------------------------------------------------

    def _check_rapl(self) -> bool:
        """Return True if hw_config recorded at least one accessible RAPL path."""
        paths = self._hw_config.get("rapl", {}).get("paths", {})
        return len(paths) > 0  # empty dict → RAPL not found or not accessible

    def _check_msr(self) -> bool:
        """Return True if any /dev/cpu/N/msr devices were recorded."""
        devices = self._hw_config.get("msr", {}).get("devices", [])
        return len(devices) > 0

    def _check_thermal(self) -> bool:
        """Return True if any thermal sysfs zones were discovered."""
        paths = self._hw_config.get("thermal", {}).get("paths", {})
        return len(paths) > 0

    def _check_turbostat(self) -> bool:
        """Return True if turbostat binary was found by detect_hardware."""
        return self._hw_config.get("turbostat", {}).get("available", False)

    def _check_perf(self) -> bool:
        """
        Live-probe whether perf binary is callable.

        Not stored in hw_config.json so probed directly here.
        Failure caught silently — perf is optional.
        """
        try:
            result = subprocess.run(
                ["perf", "--version"],
                capture_output=True,
                timeout=3,
            )
            return result.returncode == 0   # 0 = perf found and callable
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    # ------------------------------------------------------------------
    # JSON LOADER
    # ------------------------------------------------------------------

    def _load_json(self, path: Path, label: str) -> dict:
        """
        Load and parse a JSON config file safely.

        Returns empty dict on missing file or parse error — callers
        fall back gracefully to LIMITED mode without crashing.

        Args:
            path:  File path to load.
            label: Human-readable name for log messages.

        Returns:
            dict: Parsed JSON contents, or {} on any error.
        """
        if not path.exists():
            logger.warning(
                "%s not found at '%s'. Run the appropriate detect_*.py script first.",
                label, path,
            )
            return {}

        try:
            with open(path, "r") as f:
                data = json.load(f)
            logger.debug("Loaded %s from %s", label, path)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to parse %s: %s", label, exc)
            return {}


# ============================================================================
# MODULE-LEVEL CONVENIENCE — process-lifetime singleton
# ============================================================================

_cached_caps: Optional[PlatformCapabilities] = None


def get_platform_capabilities(
    hw_config_path:  Optional[str] = None,
    env_config_path: Optional[str] = None,
    force_refresh:   bool = False,
) -> PlatformCapabilities:
    """
    Return a cached PlatformCapabilities for this process lifetime.

    Detects once on first call; subsequent calls return cached result.
    Use force_refresh=True in tests to re-run detection.

    Args:
        hw_config_path:  Optional path override for hw_config.json.
        env_config_path: Optional path override for environment.json.
        force_refresh:   If True, ignore cache and re-run detection.

    Returns:
        PlatformCapabilities: Populated capabilities for this machine.
    """
    global _cached_caps

    # Return cache unless refresh is explicitly requested
    if _cached_caps is not None and not force_refresh:
        return _cached_caps

    detector     = PlatformDetector(
        hw_config_path  = hw_config_path,
        env_config_path = env_config_path,
    )
    _cached_caps = detector.detect()
    return _cached_caps


# ============================================================================
# CLI — python -m core.utils.platform
# ============================================================================

if __name__ == "__main__":
    """
    Quick sanity check. Run from project root:
        python -m core.utils.platform
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    detector = PlatformDetector()
    caps     = detector.detect()
    detector.save(caps)

    print("\n" + "=" * 65)
    print("PLATFORM DETECTION RESULT")
    print("=" * 65)
    print(f"  OS               : {caps.os}")
    print(f"  Architecture     : {caps.arch}")
    print(f"  Hostname         : {caps.hostname}")
    print(f"  Kernel           : {caps.kernel_version}")
    print(f"  Virtualisation   : {caps.virtualization or 'none (bare metal)'}")
    print(f"  Container        : {caps.container_runtime or 'none'}")
    print(f"  Measurement Mode : {caps.measurement_mode}")
    print(f"  RAPL             : {'yes — ' + str(caps.rapl_domains) if caps.has_rapl else 'no'}")
    print(f"  MSR              : {'yes' if caps.has_msr else 'no'}")
    print(f"  perf             : {'yes' if caps.has_perf else 'no'}")
    print(f"  turbostat        : {'yes' if caps.has_turbostat else 'no'}")
    print(f"  Thermal zones    : {'yes' if caps.has_thermal else 'no'}")
    print(f"  torch installed  : {'yes' if caps.torch_available else 'no'}")
    print(f"  env_hash         : {caps.env_hash}")
    print("=" * 65)
    print(f"\n✅ Written → config/platform.json")
