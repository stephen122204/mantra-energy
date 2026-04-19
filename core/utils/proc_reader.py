"""
Read CPU ticks from /proc/stat and /proc/[pid]/stat.
Used by Chunk 3 CPU fraction attribution: isolates workload energy
from background system processes using kernel tick counters.
Formula:
    cpu_fraction = workload_delta_ticks / total_delta_ticks
    attributed_energy_uj = cpu_fraction × dynamic_energy_uj
"""
import os
def read_total_cpu_ticks() -> int:
    """
    Read aggregate CPU ticks from /proc/stat (first 'cpu' line).
    Sums user + nice + system ticks only — excludes idle/iowait/irq
    so the denominator reflects active CPU time, not wall-clock time.
    Returns:
        int: total active CPU ticks since boot
    """
    with open("/proc/stat", "r") as f:
        line = f.readline()          # always 'cpu  user nice system idle ...'
    parts = line.split()
    user   = int(parts[1])
    nice   = int(parts[2])
    system = int(parts[3])
    return user + nice + system      # active ticks only
def read_process_cpu_ticks(pid: int) -> int:
    """
    Read CPU ticks consumed by a single process from /proc/[pid]/stat.
    Fields 14 (utime) and 15 (stime) are 0-indexed as parts[13] and parts[14].
    Both are in clock ticks (USER_HZ, typically 100/s on Linux).
    Args:
        pid: process ID to read
    Returns:
        int: utime + stime ticks for the process
    """
    with open(f"/proc/{pid}/stat", "r") as f:
        parts = f.read().split()
    utime = int(parts[13])
    stime = int(parts[14])
    return utime + stime             # total process ticks (user + kernel)
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
