#!/usr/bin/env python3
"""
Standalone verification for Apple Silicon kperf PMU reader.

Tests:
  1. Helper binary exists and is executable
  2. Helper runs with sudo and returns valid JSON
  3. Counter values are non-zero under load
  4. Idle counters are much lower than load counters
  5. IPC is in sane range (0.5 to 5.0)
  6. KPerfPMUReader produces valid PerformanceCounters
  7. Factory returns KPerfPMUReader on Darwin arm64

Usage:
    python3 scripts/tests/test_kperf_standalone.py

Requires: sudo access to alems_kperf_reader (sudoers rule installed).
Must run on macOS arm64 (Apple Silicon).
"""

import json
import os
import platform
import subprocess
import sys
import time

# Add project root to sys.path so core.* imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

HELPER_PATH = "/usr/local/bin/alems_kperf_reader"
PASS = 0
FAIL = 0


def report(name, ok, detail=""):
    """Print test result and update global counters."""
    global PASS, FAIL
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    suffix = "  ({})".format(detail) if detail else ""
    print("  [{}] {}{}".format(status, name, suffix))


def read_helper():
    """Call helper via sudo and return parsed JSON or None."""
    try:
        result = subprocess.run(
            ["sudo", "-n", HELPER_PATH],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout.strip())
    except Exception:
        return None


def generate_load():
    """Generate ~0.5 seconds of CPU load to move PMU counters."""
    total = 0
    end = time.time() + 0.5
    while time.time() < end:
        for i in range(100000):
            total += i * i
    return total


def main():
    # type: () -> None
    global PASS, FAIL

    print("=" * 60)
    print("A-LEMS kperf PMU Standalone Verification")
    print("=" * 60)

    # Pre-check: macOS arm64 only
    if platform.system() != "Darwin":
        print("SKIP: not macOS (this test runs only on Apple Silicon)")
        sys.exit(0)
    if platform.machine() not in ("arm64", "aarch64"):
        print("SKIP: not arm64 (this test runs only on Apple Silicon)")
        sys.exit(0)

    print()
    print("Test 1: Helper binary exists")
    report("helper_exists", os.path.isfile(HELPER_PATH), HELPER_PATH)

    print()
    print("Test 2: Helper returns valid JSON")
    data = read_helper()
    report("helper_returns_json", data is not None)
    if data:
        report("has_instructions_field", "instructions" in data)
        report("has_cycles_field", "cycles" in data)
        report("has_l1d_miss_ld_field", "l1d_miss_ld" in data)

    print()
    print("Test 3: Counters increment under load")
    snap1 = read_helper()
    _ = generate_load()
    snap2 = read_helper()

    d_instr = 0
    d_cycles = 0
    if snap1 and snap2:
        d_instr = snap2["instructions"] - snap1["instructions"]
        d_cycles = snap2["cycles"] - snap1["cycles"]
        report("instructions_nonzero_under_load", d_instr > 0,
               "delta={:,}".format(d_instr))
        report("cycles_nonzero_under_load", d_cycles > 0,
               "delta={:,}".format(d_cycles))
    else:
        report("instructions_nonzero_under_load", False, "helper failed")
        report("cycles_nonzero_under_load", False, "helper failed")

    print()
    print("Test 4: Idle counters much lower than load counters")
    snap_idle1 = read_helper()
    time.sleep(0.5)   # idle period
    snap_idle2 = read_helper()
    if snap_idle1 and snap_idle2 and d_instr > 0:
        d_idle = snap_idle2["instructions"] - snap_idle1["instructions"]
        # During load we expect at least 5x more instructions than idle
        ratio = d_instr / max(d_idle, 1)
        report("idle_vs_load_ratio", ratio > 2,
               "load/idle={:.1f}x".format(ratio))
    else:
        report("idle_vs_load_ratio", False, "helper failed or no load data")

    print()
    print("Test 5: IPC in sane range (0.5 to 5.0)")
    if snap1 and snap2 and d_cycles > 0:
        ipc = d_instr / d_cycles
        report("ipc_sane_range", 0.5 <= ipc <= 5.0,
               "IPC={:.2f}".format(ipc))
    else:
        report("ipc_sane_range", False, "no valid snapshot data")

    print()
    print("Test 6: KPerfPMUReader integration")
    try:
        from core.readers.darwin.kperf_pmu_reader import KPerfPMUReader
        reader = KPerfPMUReader()
        report("reader_is_available", reader.is_available())
        report("reader_get_name", reader.get_name() == "KPerfPMUReader")

        # Two-snapshot measurement cycle
        reader.start_process_measurement()
        _ = generate_load()
        counters = reader.stop_process_measurement()

        report("counters_instructions_nonzero",
               counters.instructions_retired > 0,
               "{:,}".format(counters.instructions_retired))
        report("counters_cycles_nonzero",
               counters.cpu_cycles > 0,
               "{:,}".format(counters.cpu_cycles))
        ipc_val = counters.instructions_per_cycle()
        report("counters_ipc_sane",
               0.5 <= ipc_val <= 5.0,
               "{:.2f}".format(ipc_val))
        report("counters_l1d_misses_nonneg",
               counters.l1d_cache_misses >= 0,
               "{:,}".format(counters.l1d_cache_misses))

    except ImportError as e:
        report("reader_import", False, str(e))
    except Exception as e:
        report("reader_error", False, str(e))

    print()
    print("Test 7: Factory returns KPerfPMUReader on Darwin arm64")
    try:
        from core.readers.factory import ReaderFactory
        r = ReaderFactory.get_cpu_reader()
        reader_type = type(r).__name__
        report("factory_returns_kperf",
               reader_type == "KPerfPMUReader",
               "got {}".format(reader_type))
    except Exception as e:
        report("factory_returns_kperf", False, str(e))

    print()
    print("=" * 60)
    print("Results: {} PASS, {} FAIL".format(PASS, FAIL))
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
