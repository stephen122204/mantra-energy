"""Read-only operating-state observations, separate from energy counters.

Reported CPU frequency is a kernel cpufreq reading, not an independently measured
clock. Missing CPU throttle counters (common on AMD) remain unavailable. NVML
reason masks include idle/power-limit reasons and are not a generic thermal flag.
"""
import math
from pathlib import Path
import time


def observation(read, unit):
    try:
        value = read()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("nonfinite or nonnumeric observation")
        return dict(status="available", value=value, unit=unit)
    except Exception as error:
        return dict(
            status="unavailable",
            value=None,
            unit=unit,
            reason=f"{type(error).__name__}: {error}",
        )


class OperatingStateReader:
    def __init__(
        self,
        gpu,
        *,
        sysfs=Path("/sys"),
        clock_ns=time.monotonic_ns,
        wall_ns=time.time_ns,
    ):
        self.gpu = gpu
        self.clock_ns = clock_ns
        self.wall_ns = wall_ns
        self.sources = {}
        for path in sorted(
            (sysfs / "devices/system/cpu/cpufreq").glob("policy*/scaling_cur_freq")
        ):
            self.sources[f"cpu_frequency/{path.parent.name}"] = (path, "kHz", 1)
        for path in sorted(
            (sysfs / "devices/system/cpu").glob(
                "cpu*/thermal_throttle/*_throttle_count"
            )
        ):
            self.sources[f"cpu_throttle/{path.parent.parent.name}/{path.name}"] = (
                path,
                "count",
                1,
            )
        for directory in sorted((sysfs / "class/hwmon").glob("hwmon*")):
            try:
                name = (directory / "name").read_text().strip()
            except OSError:
                continue
            if name not in {"k10temp", "coretemp", "zenpower"}:
                continue
            for path in sorted(directory.glob("temp*_input")):
                self.sources[f"cpu_temperature/{directory.name}/{name}/{path.stem}"] = (
                    path,
                    "C",
                    0.001,
                )
        self.legend = {}
        nvml = getattr(gpu, "_pynvml", None)
        if nvml:
            self.legend = {
                name: int(getattr(nvml, name))
                for name in dir(nvml)
                if name.startswith(
                    ("nvmlClocksThrottleReason", "nvmlClocksEventReason")
                )
                and type(getattr(nvml, name)) is int
            }

    def inventory(self):
        return dict(
            sources={
                key: dict(path=str(path), unit=unit)
                for key, (path, unit, scale) in self.sources.items()
            },
            gpu_reason_mask_legend=self.legend,
            scope="CPU hwmon temperature, kernel-reported cpufreq, exposed CPU throttle counts; NVML GPU temperature/clocks/reason mask. No missing reading is zero and no CPU throttle state is inferred from temperature.",
        )

    def sample(self):
        start = self.clock_ns()
        wall = self.wall_ns()
        fields = {}
        for name, (path, unit, scale) in self.sources.items():
            fields[name] = observation(
                lambda p=path, s=scale: int(p.read_text().strip()) * s, unit
            )
        nvml = getattr(self.gpu, "_pynvml", None)
        handle = getattr(self.gpu, "_handle", None)

        def gpu_read(method, *args):
            if nvml is None or handle is None:
                raise RuntimeError("NVML device unavailable")
            return getattr(nvml, method)(handle, *args)

        fields["gpu_temperature"] = observation(
            lambda: gpu_read(
                "nvmlDeviceGetTemperature", getattr(nvml, "NVML_TEMPERATURE_GPU", 0)
            ),
            "C",
        )
        fields["gpu_sm_clock"] = observation(
            lambda: gpu_read(
                "nvmlDeviceGetClockInfo", getattr(nvml, "NVML_CLOCK_SM", 1)
            ),
            "MHz",
        )
        fields["gpu_memory_clock"] = observation(
            lambda: gpu_read(
                "nvmlDeviceGetClockInfo", getattr(nvml, "NVML_CLOCK_MEM", 2)
            ),
            "MHz",
        )
        reason_method = (
            "nvmlDeviceGetCurrentClocksEventReasons"
            if hasattr(nvml, "nvmlDeviceGetCurrentClocksEventReasons")
            else "nvmlDeviceGetCurrentClocksThrottleReasons"
        )
        fields["gpu_clock_reasons"] = observation(
            lambda: gpu_read(reason_method), "bitmask"
        )
        for prefix in ("cpu_temperature/", "cpu_frequency/", "cpu_throttle/"):
            if not any(key.startswith(prefix) for key in fields):
                fields[prefix.rstrip("/")] = dict(
                    status="unavailable",
                    value=None,
                    unit=None,
                    reason="no supported readable interface discovered",
                )
        return dict(
            read_start_ns=start,
            read_end_ns=self.clock_ns(),
            wall_time_ns=wall,
            fields=fields,
        )
