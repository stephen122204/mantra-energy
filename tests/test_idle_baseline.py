from core.readers.measurement_schema import DomainDescriptor, MeasurementSchema
from studies.energy_diagnosis.diagnostics import idle_baseline


class Fake:
    def __init__(self):
        self.t = 0
        self.domains = (DomainDescriptor("pkg0", "PACKAGE_SOCKET_0", "ENERGY_COUNTER", None, max_energy_range_uj=1000),
                        DomainDescriptor("gpu_0", "GPU_BOARD_0", "ENERGY_COUNTER", None))

    def get_measurement_schema(self):
        return MeasurementSchema("fake", self.domains, 10, 64)

    def read_energy(self):
        self.t += 1
        # package counter wraps at 1000 uJ; GPU monotonic
        return {"pkg0": (self.t * 700) % 1001, "gpu_0": self.t * 10_000_000}


def test_measure_handles_wrap_and_names(monkeypatch):
    monkeypatch.setattr(idle_baseline.time, "sleep", lambda s: None)
    r = idle_baseline.measure(Fake(), windows=4, seconds=1.0)
    assert set(r["baseline_w"]) == {"PACKAGE_SOCKET_0", "GPU_BOARD_0"}
    assert r["kept"] >= 3 and all(v["mean_w"] is not None for v in r["baseline_w"].values())
