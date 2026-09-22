"""Operating-state observations keep units, acquisition bounds and missing data."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from studies.energy_diagnosis.runtime.operating_state import OperatingStateReader
from studies.energy_diagnosis.runtime.node_measurement import (
    FixtureCounterReader,
    NodeMeasurement,
)
from tests.test_node_measurement import ENVIRONMENT


def file(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return path


def gpu(**overrides):
    methods = dict(
        NVML_TEMPERATURE_GPU=0,
        NVML_CLOCK_SM=1,
        NVML_CLOCK_MEM=2,
        nvmlClocksThrottleReasonGpuIdle=1,
        nvmlClocksEventReasonHwThermalSlowdown=64,
        nvmlDeviceGetTemperature=lambda handle, sensor: 52,
        nvmlDeviceGetClockInfo=lambda handle, clock: {1: 1410, 2: 1215}[clock],
        nvmlDeviceGetCurrentClocksEventReasons=lambda handle: 64,
    )
    methods.update(overrides)
    return SimpleNamespace(_handle=object(), _pynvml=SimpleNamespace(**methods))


def test_units_source_inventory_and_read_brackets(tmp_path):
    file(tmp_path, "devices/system/cpu/cpufreq/policy0/scaling_cur_freq", "2400000")
    file(tmp_path, "devices/system/cpu/cpu0/thermal_throttle/core_throttle_count", "7")
    file(tmp_path, "class/hwmon/hwmon2/name", "k10temp")
    file(tmp_path, "class/hwmon/hwmon2/temp1_input", "63500")
    clock = iter([10, 40])
    reader = OperatingStateReader(
        gpu(), sysfs=tmp_path, clock_ns=lambda: next(clock), wall_ns=lambda: 999
    )
    sample = reader.sample()
    assert (sample["read_start_ns"], sample["read_end_ns"], sample["wall_time_ns"]) == (
        10,
        40,
        999,
    )
    fields = sample["fields"]
    assert fields["cpu_temperature/hwmon2/k10temp/temp1_input"]["value"] == 63.5
    assert fields["cpu_frequency/policy0"] == dict(
        status="available", value=2400000, unit="kHz"
    )
    assert fields["cpu_throttle/cpu0/core_throttle_count"]["value"] == 7
    assert fields["gpu_sm_clock"]["value"] == 1410
    assert fields["gpu_memory_clock"]["value"] == 1215
    assert fields["gpu_clock_reasons"]["value"] == 64
    assert (
        reader.inventory()["gpu_reason_mask_legend"][
            "nvmlClocksEventReasonHwThermalSlowdown"
        ]
        == 64
    )
    assert reader.inventory()["sources"]["cpu_frequency/policy0"]["path"].endswith(
        "scaling_cur_freq"
    )
    json.dumps(sample, allow_nan=False)


def test_one_missing_sensor_does_not_hide_other_readings(tmp_path):
    path = file(
        tmp_path, "devices/system/cpu/cpufreq/policy0/scaling_cur_freq", "2400000"
    )
    reader = OperatingStateReader(
        gpu(nvmlDeviceGetTemperature=lambda *_: float("nan")), sysfs=tmp_path
    )
    path.unlink()  # It was discovered but became unreadable.
    fields = reader.sample()["fields"]
    for name in (
        "cpu_frequency/policy0",
        "gpu_temperature",
        "cpu_throttle",
        "cpu_temperature",
    ):
        assert fields[name]["status"] == "unavailable"
        assert fields[name]["value"] is None
        assert fields[name]["reason"]
    assert fields["gpu_memory_clock"]["value"] == 1215
    json.dumps(fields, allow_nan=False)


def test_missing_gpu_and_legacy_reason_api(tmp_path):
    fields = OperatingStateReader(None, sysfs=tmp_path).sample()["fields"]
    assert all(row["status"] == "unavailable" for row in fields.values())
    device = gpu()
    del device._pynvml.nvmlDeviceGetCurrentClocksEventReasons
    device._pynvml.nvmlDeviceGetCurrentClocksThrottleReasons = lambda _: 1
    assert (
        OperatingStateReader(device, sysfs=tmp_path).sample()["fields"][
            "gpu_clock_reasons"
        ]["value"]
        == 1
    )


def test_operating_samples_stay_inside_energy_goal_and_failures_are_saved():
    events = []

    class Reader(FixtureCounterReader):
        def read_operating_state(self):
            events.append("operating")
            if len(events) > 2:
                raise PermissionError("fixture permission denied")
            return dict(
                fields={"gpu_temperature": dict(status="available", value=50, unit="C")}
            )

    measured = NodeMeasurement(Reader(), ENVIRONMENT)
    start = measured.session.start_goal
    end = measured.session.end_goal

    def begin():
        events.append("goal_start")
        return start()

    def finish():
        events.append("goal_end")
        return end()

    with patch.object(measured.session, "start_goal", side_effect=begin), patch.object(
        measured.session, "end_goal", side_effect=finish
    ), patch("studies.energy_diagnosis.runtime.node_measurement.threading.Thread"):
        measured.start_goal()
        measured.finish_goal()
    assert events == ["goal_start", "operating", "operating", "goal_end"]
    artifact = measured.operating_state_artifact()
    assert len(artifact["samples"]) == 2
    assert artifact["samples"][-1]["status"] == "unavailable"
    assert "permission denied" in artifact["samples"][-1]["reason"]
    assert measured.artifacts is not None


def test_fixture_does_not_invent_operating_state():
    measured = NodeMeasurement(FixtureCounterReader(), ENVIRONMENT)
    artifact = measured.operating_state_artifact()
    assert artifact["status"] == "unavailable"
    assert artifact["samples"] == []
