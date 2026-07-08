"""
Read CPU ticks from /proc/stat and /proc/[pid]/stat.
Used by Chunk 3 CPU fraction attribution: isolates workload energy
from background system processes using kernel tick counters.
Formula:
    cpu_fraction = workload_delta_ticks / total_delta_ticks
    attributed_energy_uj = cpu_fraction × dynamic_energy_uj
"""
import os
import platform
import time
def read_total_cpu_ticks() -> int:
    """
    Read aggregate CPU ticks from /proc/stat (Linux) or wall-clock (Darwin).
    Linux: sums user + nice + system ticks from /proc/stat first line.
    Darwin: wall_time * 100 * ncpus — total available ticks across all cores.
            Paired with read_process_cpu_ticks() which uses resource.getrusage()
            in the same USER_HZ units, giving correct cpu_fraction on Apple Silicon.
    Returns:
        int: total active CPU ticks, 0 if unavailable
    """
    if platform.system() == "Linux":
        with open("/proc/stat", "r") as f:
            line = f.readline()      # always 'cpu  user nice system idle ...'
        parts = line.split()
        user   = int(parts[1])
        nice   = int(parts[2])
        system = int(parts[3])
        return user + nice + system  # active ticks only
    if platform.system() == "Darwin":
        try:
            import psutil
            # wall-clock seconds * HZ * ncpus = total available ticks
            return int(time.monotonic() * 100 * psutil.cpu_count())
        except Exception:
            return 0
    return 0


def read_process_cpu_ticks(pid: int) -> int:
    """
    Read CPU ticks consumed by a single process.
    Linux: reads utime + stime from /proc/[pid]/stat (USER_HZ ticks).
    Darwin: uses resource.getrusage() for the process CPU time in USER_HZ units.
            resource module is stdlib on Darwin, no extra dependency.
    Args:
        pid: process ID to read
    Returns:
        int: utime + stime ticks for the process, 0 if unavailable
    """
    if platform.system() == "Linux":
        with open(f"/proc/{pid}/stat", "r") as f:
            parts = f.read().split()
        utime = int(parts[13])
        stime = int(parts[14])
        return utime + stime         # total process ticks (user + kernel)
    if platform.system() == "Darwin":
        try:
            import resource
            # getrusage only works for current process or children
            # for the LLM subprocess we use os.wait4 equivalent via psutil
            import psutil
            p = psutil.Process(pid)
            t = p.cpu_times()
            return int((t.user + t.system) * 100)
        except Exception:
            return 0
    return 0
def compute_cpu_fraction(workload_delta: int, total_delta: int) -> float:
    """
    Compute the fraction of CPU time consumed by the workload process.
    Guards against zero-division when the run is extremely short or
    the system was idle (total_delta == 0).
    Args:
        workload_delta: tick delta for the workload PID
        total_delta:    tick delta for the whole system
    Returns:
        float: value in [0.0, 1.0] — clamped so rounding never exceeds 1
    """
    if total_delta <= 0:
        return 0.0
    fraction = workload_delta / total_delta
    return min(fraction, 1.0)        # clamp: floating-point safety
