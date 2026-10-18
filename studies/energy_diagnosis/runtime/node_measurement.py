"""Node-side reader bridge using existing ALEMS RAPL and NVML backends.

Only cumulative counter domains are totaled here. Unsupported GPU counters
remain unavailable; sampled-power experiments use the separate GPUCollector
path and require its coverage validation before claiming a total.
"""

import os
from pathlib import Path
import socket
import threading
import time
import uuid

from core.readers.measurement_schema import (
    DomainDescriptor,
    MeasurementSchema,
    ENERGY_COUNTER,
)
from .measurement import EnvironmentIdentity, MeasurementSession


class NodeCounterReader:
    def __init__(self, gpu_index=0):
        from core.readers.rapl_reader import RAPLReader
        from core.readers.gpu_collector import NVMLBackend

        # Discover actual sysfs identities; keep each socket/domain separate.
        root = Path("/sys/class/powercap")
        paths = {
            str(p.parent.resolve()): str(p) for p in root.glob("intel-rapl*/energy_uj")
        }
        paths.update(
            {
                str(p.parent.resolve()): str(p)
                for p in root.glob("intel-rapl*/intel-rapl*/energy_uj")
            }
        )
        paths.update(
            {
                str(p.parent.resolve()): str(p)
                for p in root.glob("intel-rapl/intel-rapl*/energy_uj")
            }
        )
        paths.update(
            {
                str(p.parent.resolve()): str(p)
                for p in root.glob("intel-rapl/intel-rapl*/intel-rapl*/energy_uj")
            }
        )
        # Limit to CPU-package and separately identified DRAM counters.
        selected = {}
        for path in paths.values():
            try:
                name = (Path(path).parent / "name").read_text().strip()
                if name.startswith("package") or name == "dram":
                    selected[str(Path(path).parent.name)] = path
            except OSError:
                continue
        self.rapl = RAPLReader({"paths": selected})
        self.gpu = NVMLBackend(gpu_index=gpu_index)
        self.gpu_index = gpu_index
        from .operating_state import OperatingStateReader
        self.operating_state = OperatingStateReader(self.gpu)
        domains = list(self.rapl.get_measurement_schema().domains)
        if not any(d.canonical_name.startswith("PACKAGE") for d in domains):
            domains.append(
                DomainDescriptor(
                    "cpu_unavailable", "CPU_PACKAGE_UNAVAILABLE", ENERGY_COUNTER, None
                )
            )
        self.gpu_key = f"gpu_{gpu_index}"
        domains.append(
            DomainDescriptor(
                self.gpu_key, f"GPU_BOARD_{gpu_index}", ENERGY_COUNTER, None
            )
        )
        self.schema = MeasurementSchema("RAPL+NVML", tuple(domains), 10, 64)

    def get_measurement_schema(self):
        return self.schema

    def get_name(self):
        return "ALEMS RAPL/NVML node counters"

    def is_available(self):
        return self.rapl.is_available() or self.gpu.is_available()

    def read_energy(self):
        values = {}
        # Preserve readable domains even if another counter becomes inaccessible.
        for key, path in self.rapl.available_paths.items():
            try:
                values[key] = int(Path(path).read_text().strip())
            except (OSError, ValueError):
                values[key] = None
        try:
            values[self.gpu_key] = self.gpu.read_energy_uj(self.gpu_index)
        except Exception:
            values[self.gpu_key] = None
        return values

    def device_identity(self):
        if not self.gpu.is_available():
            return {"gpu_index": self.gpu_index, "status": "unavailable"}
        try:
            value = self.gpu._pynvml.nvmlDeviceGetUUID(self.gpu._handle)
            if isinstance(value, bytes):
                value = value.decode()
            return {
                "gpu_index": self.gpu_index,
                "uuid": value,
                "measurement_kind": self.gpu.measurement_kind,
                "inventory": self.gpu.get_gpu_info(),
            }
        except Exception as exc:
            return {
                "gpu_index": self.gpu_index,
                "status": "identity unavailable",
                "reason": str(exc),
            }

    def read_operating_state(self):
        return self.operating_state.sample()

    def operating_state_inventory(self):
        return self.operating_state.inventory()

    def close(self):
        self.gpu.shutdown()


class FixtureCounterReader:
    """Explicit simulated counters; never used by --mode live."""

    def __init__(self, missing_gpu=False):
        self.value = 0
        self.missing_gpu = missing_gpu

    def get_measurement_schema(self):
        return MeasurementSchema(
            "SIMULATED",
            tuple(
                DomainDescriptor(k, k, ENERGY_COUNTER, None)
                for k in ("CPU_FIXTURE", "GPU_FIXTURE")
            ),
            10,
            64,
        )

    def get_name(self):
        return "SIMULATED counter fixture"

    def is_available(self):
        return True

    def read_energy(self):
        self.value += 1000
        return {
            "CPU_FIXTURE": self.value,
            "GPU_FIXTURE": None if self.missing_gpu else self.value * 2,
        }

    def close(self):
        pass


class NodeMeasurement:
    def __init__(self, reader, environment, *, session_id=None):
        self.session_id = session_id or str(uuid.uuid4())
        self.clock_domain = f"{environment.hostname}:{environment.boot_id}:monotonic"
        self.session = MeasurementSession(
            reader,
            environment=environment,
            session_id=self.session_id,
            clock_domain=self.clock_domain,
        )
        self.stop = threading.Event()
        self._sampling_lock = threading.Lock()
        self.thread = None
        self.artifacts = None
        self.sample_error = None
        self.operating_samples = []
        self._operating_reader = getattr(reader, "read_operating_state", None)
        self.operating_inventory = reader.operating_state_inventory() if hasattr(reader, "operating_state_inventory") else {}
        self._next_operating_ns = 0

    def _sample_operating_state(self):
        if not callable(self._operating_reader):
            return
        start = time.monotonic_ns()
        try:
            self.operating_samples.append(self._operating_reader())
        except Exception as error:
            self.operating_samples.append(dict(read_start_ns=start, read_end_ns=time.monotonic_ns(),
                                               status="unavailable", reason=str(error), fields={}))
        self._next_operating_ns = time.monotonic_ns() + 1_000_000_000

    def operating_state_artifact(self):
        return dict(protocol="operating-state-v1", session_id=self.session_id,
                    clock_domain=self.clock_domain, interval_target_seconds=1,
                    status="recorded" if self.operating_samples else "unavailable",
                    reason="" if self.operating_samples else "reader does not expose operating state",
                    inventory=self.operating_inventory, samples=list(self.operating_samples))

    def start_goal(self):
        self.session.start_session()
        start = self.session.start_goal()
        self._sample_operating_state()

        def sample():
            while not self.stop.wait(0.1):
                try:
                    with self._sampling_lock:
                        # The wait may have completed just before finish_goal.
                        if self.stop.is_set():
                            break
                        self.session.sample_goal()
                        if time.monotonic_ns() >= self._next_operating_ns:
                            self._sample_operating_state()
                except Exception as exc:
                    self.sample_error = str(exc)
                    break

        self.thread = threading.Thread(target=sample, name="study-counter-sampling")
        self.thread.start()
        return start

    def finish_goal(self):
        self.stop.set()
        try:
            with self._sampling_lock:
                # Seal the counters before sampler teardown can add goal cost.
                self._sample_operating_state()
                self.session.end_goal()
        finally:
            # Never join while holding a lock the sampler may still need.
            self.thread.join()
        self.artifacts = self.session.finish_session()
        if self.sample_error:
            raise RuntimeError(f"counter sampling failed: {self.sample_error}")
        return self.artifacts

    def checkpoint(self, name):
        return self.session.checkpoint(name)

    def measure_between(self, start, end):
        return self.session.measure_between(start, end)


def environment_identity(source_revision, allocation_id, isolation, devices=()):
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        boot = f"process-{os.getpid()}-{time.time_ns()}"
    try:
        cpus = ",".join(map(str, sorted(os.sched_getaffinity(0))))
    except AttributeError:
        cpus = f"{os.cpu_count()} logical CPUs; affinity unavailable"
    return EnvironmentIdentity(
        source_revision,
        socket.gethostname(),
        boot,
        allocation_id,
        cpus,
        tuple(devices),
        isolation,
    )
