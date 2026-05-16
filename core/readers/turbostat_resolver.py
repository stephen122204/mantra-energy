"""
core/readers/turbostat_resolver.py

Dynamic turbostat binary resolution — never reads a hardcoded path.
Resolves at runtime via platform.release() — self-healing on kernel upgrade.

Motivation: kernel upgrade from 6.17.0-22 to 6.17.0-23 (env_id 39->40,
2026-05-08) silently broke package_temp measurement because real_binary
was pinned to old kernel path in hw_config.json. This module ensures
that never happens again on any machine or kernel version.

Resolution order:
  1. /usr/lib/linux-tools/<uname -r>/turbostat  MEASURED
  2. dpkg -L linux-tools-common search           MEASURED
  3. realpath of wrapper symlink                 MEASURED
  4. which turbostat (PATH)                      MEASURED
  5. None                                        LIMITED

TURBOSTAT_COLUMNS: single source of truth for all column mappings.
Replaces hw_config.json turbostat.columns and turbostat_override.yaml.
One place, one truth, versioned in git. Never hand-edited.

Python 3.9+ compatible — no X|Y union hints, no tuple[...] lowercase hints.
"""

import logging
import os
import platform
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column contract — single source of truth, versioned in code not yaml/json.
# Changing a mapping = bump version suffix in downstream method_id.
# Internal name -> turbostat column name
# ---------------------------------------------------------------------------
TURBOSTAT_COLUMNS = {
    # Internal name          turbostat col   paper / ALEOE use
    "cpu_util_percent":     "Busy%",        # orchestration activity detection
    "cpu_busy_mhz":         "Bzy_MHz",      # frequency when CPU active
    "cpu_avg_mhz":          "Avg_MHz",      # average load including idle
    "c1_residency":         "C1ACPI%",      # shallow sleep — short orch waits
    "c2_residency":         "C2ACPI%",      # deeper sleep
    "c3_residency":         "C3ACPI%",      # deep sleep — idle orch gaps
    "c6_residency":         "CPU%c6",       # deepest core C-state — KEY ALEOE signal
    "c7_residency":         "CPU%c7",       # package C-state entry point
    "pkg_c8_residency":     "Pkg%pc8",      # package deep sleep
    "pkg_c9_residency":     "Pkg%pc9",      # package deeper sleep
    "pkg_c10_residency":    "Pk%pc10",      # package deepest C-state
    "gpu_rc6":              "GFX%rc6",      # GPU idle fraction
    "gfx_freq":             "GFXMHz",       # GPU frequency
    "package_temp":         "PkgTmp",       # package temperature — thermal
    "package_power":        "PkgWatt",      # package power draw
    "core_power":           "CorWatt",      # core power draw
    "gpu_power":            "GFXWatt",      # GPU power draw
    "ram_power":            "RAMWatt",      # DRAM power draw
    "ipc":                  "IPC",          # instructions per cycle
    "irq":                  "IRQ",          # interrupt rate
    "busy_percent":         "Busy%",        # alias — same turbostat col as cpu_util_percent
}

# Deduplicated --select string — built once, deterministic across all platforms
_SELECT_COLS = ",".join(sorted(set(TURBOSTAT_COLUMNS.values())))


def resolve_turbostat_binary():
    # type: () -> Tuple[Optional[str], str]
    """
    Resolve turbostat binary path at runtime.
    Never reads hw_config.json — always resolves fresh via kernel version.
    Self-healing: works correctly after every kernel upgrade without any
    config file change or script re-run.

    Returns:
        Tuple of (binary_path, measurement_type).
        binary_path is None when turbostat unavailable -> LIMITED mode.
    """
    for path, source in _build_candidates():
        if _binary_works(path):
            logger.info("turbostat resolved: %s (via %s)", path, source)
            return path, "MEASURED"

    # No working binary found — LIMITED mode, zeros recorded
    logger.warning(
        "turbostat unavailable — C-states and PkgTmp will be 0. "
        "Install linux-tools-$(uname -r) to restore measurement."
    )
    return None, "LIMITED"


def _build_candidates():
    # type: () -> List[Tuple[str, str]]
    """
    Build ordered list of (path, source_description) candidates.
    Most specific (kernel-versioned) first.
    """
    candidates = []

    # Layer 1 — kernel-versioned path (most accurate, matches running MSR layout)
    kernel = platform.release()
    if kernel:
        versioned = "/usr/lib/linux-tools/{}/turbostat".format(kernel)
        candidates.append((versioned, "kernel-versioned ({})".format(kernel)))

    # Layer 2 — dpkg search (Debian/Ubuntu only)
    dpkg_path = _find_via_dpkg()
    if dpkg_path:
        candidates.append((dpkg_path, "dpkg"))

    # Layer 3 — follow wrapper symlink to real binary
    wrapper = shutil.which("turbostat")
    if wrapper and os.path.islink(wrapper):
        real = os.path.realpath(wrapper)
        if real and os.path.exists(real):
            candidates.append((real, "symlink realpath"))

    # Layer 4 — PATH fallback (wrapper or direct)
    if wrapper:
        candidates.append((wrapper, "PATH"))

    return candidates


def _find_via_dpkg():
    # type: () -> Optional[str]
    """Find turbostat real binary via dpkg package listing."""
    try:
        result = subprocess.run(
            ["dpkg", "-L", "linux-tools-common"],
            capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.split("\n"):
            line = line.strip()
            if "turbostat" in line and not line.endswith(".gz"):
                if os.path.exists(line) and not os.path.islink(line):
                    return line
    except Exception:
        pass
    return None


def _binary_works(path):
    # type: (str) -> bool
    """Return True if binary exists and produces output on --help."""
    if not path or not os.path.exists(path):
        return False
    try:
        result = subprocess.run(
            [path, "--help"],
            capture_output=True, text=True, timeout=3
        )
        # turbostat --help exits non-zero but always writes to stderr
        return len(result.stderr) > 0 or len(result.stdout) > 0
    except Exception as exc:
        logger.debug("turbostat binary check failed %s: %s", path, exc)
        return False


def validate_turbostat_columns(binary):
    # type: (Optional[str]) -> List[str]
    """
    Run turbostat once, check which TURBOSTAT_COLUMNS are present in output.
    Returns list of missing turbostat column names.
    Missing columns logged as WARNING — stored in hw_profile per experiment.
    Never raises — missing columns degrade gracefully to 0.
    """
    if not binary:
        return list(set(TURBOSTAT_COLUMNS.values()))

    try:
        result = subprocess.run(
            [binary, "--Summary", "--quiet", "--interval", "1",
             "--num_iterations", "1"],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout + result.stderr
        output_tokens = set(output.split())

        missing = [
            col for col in set(TURBOSTAT_COLUMNS.values())
            if col not in output_tokens
        ]
        if missing:
            logger.warning(
                "turbostat missing columns %s — those metrics will be 0.", missing
            )
        return missing

    except Exception as exc:
        logger.warning("turbostat column validation failed: %s", exc)
        return []


def get_select_string():
    # type: () -> str
    """
    Return the --select column string for turbostat invocation.
    Deterministic — identical string on every kernel version and machine.
    Using --select (not --show) ensures only requested columns appear,
    making output format stable regardless of turbostat version.
    """
    return _SELECT_COLS
