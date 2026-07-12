#!/usr/bin/env python3
"""
scripts/tests/test_ioreport_standalone.py

Standalone IOReport DVFS verification for Apple Silicon.
Run this on any Mac WITHOUT the full A-LEMS harness to verify:
  - IOReport and CoreFoundation load via ctypes
  - DVFS frequency table is discovered from IORegistry pmgr
  - IOReport subscription and sampling work end-to-end
  - Weighted frequency is non-zero and varies with CPU load

Usage (no sudo required):
    python3 scripts/tests/test_ioreport_standalone.py

Expected output: all checks PASS, frequency differs between idle and load.
"""

import ctypes
import sys
import time
import os

# Add project root to path so we can import A-LEMS modules
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_script_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def check(label: str, condition: bool, detail: str = "") -> bool:
    """Print a PASS/FAIL line. Returns True if passed."""
    status = "[PASS]" if condition else "[FAIL]"
    line = f"{status} {label}"
    if detail:
        line += f"\n       {detail}"
    print(line)
    return condition


def main() -> int:
    passed = 0
    total = 0

    print("=" * 60)
    print("IOReport CPU Frequency Reader — Standalone Verification")
    print("=" * 60)
    print()

    # Check 1: Platform
    total += 1
    import platform
    is_darwin = platform.system() == "Darwin"
    if check("Platform is Darwin (macOS)", is_darwin,
             f"platform.system()={platform.system()}"):
        passed += 1
    else:
        print("\nThis test only runs on macOS. Exiting.")
        return 1

    # Check 2: Load libIOReport.dylib
    total += 1
    try:
        ior = ctypes.cdll.LoadLibrary("/usr/lib/libIOReport.dylib")
        if check("libIOReport.dylib loaded", True, str(ior)):
            passed += 1
    except OSError as e:
        check("libIOReport.dylib loaded", False, str(e))
        print("\nlibIOReport.dylib unavailable. Exiting.")
        return 1

    # Check 3: Load CoreFoundation
    total += 1
    try:
        cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/"
            "CoreFoundation.framework/CoreFoundation"
        )
        if check("CoreFoundation.framework loaded", True, str(cf)):
            passed += 1
    except OSError as e:
        check("CoreFoundation.framework loaded", False, str(e))
        print("\nCoreFoundation unavailable. Exiting.")
        return 1

    # Check 4: DVFS table discovery
    total += 1
    try:
        from core.readers.darwin.dvfs_frequency_provider import DVFSFrequencyProvider
        provider = DVFSFrequencyProvider()
        freq_table = provider.get_frequency_table()
        ok = bool(freq_table and len(freq_table) > 0)
        detail = (
            f"key='{provider.key_used}', table={freq_table} MHz"
            if ok else "get_frequency_table() returned None"
        )
        if check("DVFS frequency table discovered", ok, detail):
            passed += 1
        else:
            print("\nDVFS table unavailable. Cannot compute weighted frequency.")
            return 1
    except Exception as e:
        check("DVFS frequency table discovered", False, str(e))
        return 1

    # Check 5: IOReportCPUFreqReader.is_available()
    total += 1
    try:
        from core.readers.darwin.ioreport_cpufreq_reader import IOReportCPUFreqReader
        reader = IOReportCPUFreqReader({})
        ok = reader.is_available()
        detail = reader.get_name() if ok else "is_available() returned False"
        if check("IOReportCPUFreqReader.is_available()", ok, detail):
            passed += 1
        else:
            print("\nReader unavailable. Cannot proceed.")
            return 1
    except Exception as e:
        check("IOReportCPUFreqReader.is_available()", False, str(e))
        return 1

    # Check 6: Idle measurement (2 seconds, minimal load)
    total += 1
    print("\nValidation Test 1: idle frequency (2s window, minimal load)")
    try:
        reader.start_monitoring()
        time.sleep(2)
        result_idle = reader.stop_monitoring()
        freq_idle = result_idle["summary"].get("frequency_mean", 0)
        ok = freq_idle > 0
        detail = (
            f"frequency_mean={freq_idle:.1f} MHz "
            f"min={result_idle['summary'].get('frequency_min', 0):.1f} "
            f"max={result_idle['summary'].get('frequency_max', 0):.1f}"
        )
        if check("Idle frequency is non-zero", ok, detail):
            passed += 1
    except Exception as e:
        check("Idle frequency is non-zero", False, str(e))

    # Check 7: Loaded measurement (2 seconds, CPU stress)
    total += 1
    print("\nValidation Test 2: loaded frequency (2s window, CPU stress)")
    try:
        import threading

        stop_flag = threading.Event()

        def cpu_stress():
            """Burn CPU cycles to force P-cluster activity."""
            x = 0
            while not stop_flag.is_set():
                x += 1

        # Start stress threads (one per P-core)
        stress_threads = []
        for _ in range(4):
            t = threading.Thread(target=cpu_stress, daemon=True)
            t.start()
            stress_threads.append(t)

        reader.start_monitoring()
        time.sleep(2)
        result_load = reader.stop_monitoring()

        stop_flag.set()

        freq_load = result_load["summary"].get("frequency_mean", 0)
        ok = freq_load > 0
        detail = (
            f"frequency_mean={freq_load:.1f} MHz "
            f"min={result_load['summary'].get('frequency_min', 0):.1f} "
            f"max={result_load['summary'].get('frequency_max', 0):.1f}"
        )
        if check("Loaded frequency is non-zero", ok, detail):
            passed += 1
    except Exception as e:
        check("Loaded frequency is non-zero", False, str(e))
        freq_load = 0

    # Check 8: Load > idle (wall-clock-weighted avg should be higher under load)
    total += 1
    ok = freq_load > freq_idle
    detail = f"idle={freq_idle:.1f} MHz < loaded={freq_load:.1f} MHz"
    if check("Loaded frequency > idle frequency", ok, detail):
        passed += 1
    else:
        print("       (May pass if machine was already under load during idle test)")

    # Check 9: No CF leak over 100 cycles
    total += 1
    print("\nMemory Leak Test: 100 measurement cycles")
    try:
        leak_ok = True
        for _ in range(100):
            reader.start_monitoring()
            time.sleep(0.01)
            r = reader.stop_monitoring()
            if r["num_samples"] == 0:
                leak_ok = False
                break
        if check("100 measurement cycles without crash", leak_ok,
                 "No CFRelease errors or NULL returns"):
            passed += 1
    except Exception as e:
        check("100 measurement cycles without crash", False, str(e))

    print()
    print("=" * 60)
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)

    if passed == total:
        print("\nAll checks passed. IOReport reader is ready for harness integration.")
        return 0
    else:
        print(f"\n{total - passed} check(s) failed. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
