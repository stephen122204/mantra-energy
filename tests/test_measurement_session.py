import json
import tempfile
import unittest
from pathlib import Path

from core.readers.measurement_schema import SCHEMA_DUMMY, SCHEMA_RAPL_X86, SCHEMA_SPBM_ARM
from studies.energy_diagnosis.runtime.measurement import (
    MeasurementSession,
    EnvironmentIdentity,
    probe_capabilities,
)


ENVIRONMENT = EnvironmentIdentity(
    source_revision="fixture-commit",
    hostname="fixture-host",
    boot_id="fixture-boot",
    allocation_id="fixture-allocation",
    cpu_allocation="2 fixture CPUs",
    devices=("fixture-device",),
    isolation="simulated fixture; no physical isolation claim",
)


class Clock:
    def __init__(self):
        self.now = 100

    def __call__(self):
        self.now += 10
        return self.now


class Reader:
    def __init__(self, readings, *, available=True, error=None, schema=SCHEMA_RAPL_X86):
        self.readings = list(readings)
        self.available = available
        self.error = error
        self.schema = schema

    def get_measurement_schema(self):
        return self.schema

    def get_name(self):
        return "fixture-reader"

    def is_available(self):
        return self.available

    def read_energy(self):
        if self.error:
            raise self.error
        return self.readings.pop(0)


def reading(package, core=0, uncore=0, dram=0):
    return {"package-0": package, "core": core, "uncore": uncore, "dram": dram}


class MeasurementSessionTests(unittest.TestCase):
    def run_session(self, readings, *, teardown=lambda: None, clock=None):
        clock = clock or Clock()
        session = MeasurementSession(
            Reader(readings), environment=ENVIRONMENT,
            session_id="session-1", monotonic_ns=clock,
            wall_time_ns=lambda: 1_700_000_000, teardown=teardown,
        )
        session.start_session()
        session.start_goal()
        session.end_goal()
        return session.finish_session()

    def test_constant_counter_is_valid_zero_not_missing(self):
        artifacts = self.run_session([reading(5), reading(10), reading(10)])
        package = artifacts.measurements[0]
        self.assertEqual(package.status, "valid")
        self.assertEqual(package.energy_j, 0.0)

    def test_single_counter_wrap_is_corrected(self):
        top = 1 << 32
        artifacts = self.run_session([reading(1), reading(top - 100), reading(200)])
        package = artifacts.measurements[0]
        self.assertEqual(package.energy_j, 300 / 1_000_000)
        self.assertEqual(artifacts.transitions[0].status, "wrapped")

    def test_counter_reset_is_unavailable_not_zero(self):
        artifacts = self.run_session([reading(1), reading(1000), reading(20)])
        package = artifacts.measurements[0]
        self.assertEqual(package.status, "unavailable")
        self.assertIsNone(package.energy_j)
        self.assertEqual(artifacts.transitions[0].status, "reset")

    def test_dropped_endpoint_is_explicitly_missing(self):
        artifacts = self.run_session([reading(1), reading(100), reading(None)])
        package = artifacts.measurements[0]
        self.assertEqual(package.status, "unavailable")
        self.assertIsNone(package.energy_j)
        missing = [s for s in artifacts.samples if s.domain_id == "PACKAGE" and s.status == "missing"]
        self.assertEqual(len(missing), 1)

    def test_delayed_teardown_does_not_extend_goal_boundary(self):
        fast_clock = Clock()
        fast = self.run_session([reading(1), reading(10), reading(20)], clock=fast_clock)

        slow_clock = Clock()
        def delayed_teardown():
            slow_clock.now += 10_000
        slow = self.run_session(
            [reading(1), reading(10), reading(20)], teardown=delayed_teardown,
            clock=slow_clock,
        )
        self.assertEqual(fast.goal_end_ns, slow.goal_end_ns)
        self.assertEqual(fast.measurements[0].end_ns, slow.measurements[0].end_ns)
        self.assertGreater(slow.session_end_ns, fast.session_end_ns)

    def test_acquisition_brackets_are_monotonic_and_wall_anchor_is_separate(self):
        artifacts = self.run_session([reading(1), reading(10), reading(20)])
        self.assertEqual(artifacts.clock_domain, "host-monotonic")
        self.assertEqual(artifacts.wall_clock_start_ns, 1_700_000_000)
        self.assertEqual(artifacts.wall_clock_end_ns, 1_700_000_000)
        self.assertTrue(all(s.acquired_end_ns >= s.acquired_start_ns for s in artifacts.samples))

    def test_power_rail_endpoint_is_not_misreported_as_energy(self):
        values = {
            "pkg": 100, "cpu_p": 50, "cpu_e": 20, "gpu": 30,
            "soc_pkg": 1000, "cpu_gpu": 900, "vcore": 800,
            "dc_input": 1100, "prereg": 1050, "dla": 10,
        }
        reader = Reader([values, values, values], schema=SCHEMA_SPBM_ARM)
        clock = Clock()
        session = MeasurementSession(reader, environment=ENVIRONMENT, monotonic_ns=clock)
        session.start_session(); session.start_goal(); session.end_goal()
        artifacts = session.finish_session()
        by_domain = {m.domain_id: m for m in artifacts.measurements}
        self.assertEqual(by_domain["SOC_PKG"].status, "unavailable")
        self.assertIsNone(by_domain["SOC_PKG"].energy_j)
        self.assertIn("cannot integrate", by_domain["SOC_PKG"].reason)

    def test_lifecycle_rejects_finish_before_goal_end(self):
        session = MeasurementSession(
            Reader([reading(1)]), environment=ENVIRONMENT, monotonic_ns=Clock()
        )
        session.start_session()
        with self.assertRaisesRegex(RuntimeError, "captured goal endpoint"):
            session.finish_session()


class CapabilityTests(unittest.TestCase):
    def test_probe_distinguishes_denied_access(self):
        report = probe_capabilities(
            Reader([], error=PermissionError("fixture")),
            environment=ENVIRONMENT,
            monotonic_ns=Clock(), wall_time_ns=lambda: 9,
        )
        self.assertTrue(all(d.access == "denied" for d in report.domains))
        self.assertTrue(all("access denied" in d.reason for d in report.domains))

    def test_probe_distinguishes_unsupported_reader(self):
        report = probe_capabilities(
            Reader([], available=False, schema=SCHEMA_DUMMY),
            environment=ENVIRONMENT,
            monotonic_ns=Clock(), wall_time_ns=lambda: 9,
        )
        self.assertEqual(report.domains, ())
        self.assertEqual(report.source, "DUMMY")

    def test_probe_marks_individually_missing_domains(self):
        report = probe_capabilities(
            Reader([reading(10, core=None)]),
            environment=ENVIRONMENT,
            monotonic_ns=Clock(), wall_time_ns=lambda: 9,
        )
        access = {d.domain_id: d.access for d in report.domains}
        self.assertEqual(access["PACKAGE"], "readable")
        self.assertEqual(access["CORE"], "unavailable")

    def test_capability_report_has_durable_environment_json(self):
        report = probe_capabilities(
            Reader([reading(10)]), environment=ENVIRONMENT,
            monotonic_ns=Clock(), wall_time_ns=lambda: 9,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capability.json"
            report.write_json(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["environment"]["source_revision"], "fixture-commit")
        self.assertEqual(payload["environment"]["devices"], ["fixture-device"])
        self.assertEqual(payload["domains"][0]["access"], "readable")


if __name__ == "__main__":
    unittest.main()


def test_domain_specific_wrap_range_and_nonfinite_endpoint():
    from dataclasses import replace
    schema = replace(SCHEMA_RAPL_X86, domains=(replace(SCHEMA_RAPL_X86.domains[0], max_energy_range_uj=1000),))
    session = MeasurementSession(Reader([reading(1), reading(950), reading(50)], schema=schema), environment=ENVIRONMENT, monotonic_ns=Clock())
    session.start_session(); session.start_goal(); session.end_goal()
    artifacts = session.finish_session()
    assert artifacts.measurements[0].energy_j == 100 / 1_000_000
    payload = json.loads(json.dumps(artifacts.to_dict()))
    assert payload["measurement_schema"]["domains"][0]["max_energy_range_uj"] == 1000
    report = probe_capabilities(Reader([reading(1)], schema=schema), environment=ENVIRONMENT)
    assert report.to_dict()["measurement_schema"]["domains"][0]["max_energy_range_uj"] == 1000
    session = MeasurementSession(Reader([reading(1), reading(2), reading(float('nan'))]), environment=ENVIRONMENT, monotonic_ns=Clock())
    session.start_session(); session.start_goal(); session.end_goal()
    assert session.finish_session().measurements[0].energy_j is None


def test_checkpoints_separate_costs_without_losing_outer_energy():
    # Session, goal, initialized model, task+verification done, released model.
    session = MeasurementSession(
        Reader([reading(v) for v in (0, 100, 1000, 1500, 3000)]),
        environment=ENVIRONMENT, monotonic_ns=Clock(),
    )
    session.start_session(); session.start_goal()
    session.checkpoint("initialized_model_start")
    session.checkpoint("initialized_model_end")
    inner = session.measure_between("initialized_model_start", "initialized_model_end")
    session.end_goal(); outer = session.finish_session()
    assert inner[0].energy_j == 500 / 1e6
    assert outer.measurements[0].energy_j == (900 + 500 + 1500) / 1e6
    assert session.measure_between("goal_start", "initialized_model_start")[0].energy_j == 900 / 1e6
    assert session.measure_between("initialized_model_end", "goal_end")[0].energy_j == 1500 / 1e6
    assert outer.goal_start_ns < inner[0].start_ns < inner[0].end_ns < outer.goal_end_ns
    assert outer.to_dict()["checkpoints"] == {
        "initialized_model_start": "checkpoint_initialized_model_start",
        "initialized_model_end": "checkpoint_initialized_model_end",
    }


def test_checkpoint_windows_keep_intermediate_wraps_and_missing_data():
    import pytest
    from dataclasses import replace
    schema = replace(SCHEMA_RAPL_X86, domains=(replace(
        SCHEMA_RAPL_X86.domains[0], max_energy_range_uj=1000,
    ),))
    for middle, expected in [(50, 250 / 1e6), (None, None)]:
        session = MeasurementSession(
            Reader([reading(v) for v in (0, 800, 900, middle, 150, 200)], schema=schema),
            environment=ENVIRONMENT, monotonic_ns=Clock(),
        )
        session.start_session(); session.start_goal(); session.checkpoint("begin")
        session.sample_goal(); session.checkpoint("end")
        assert session.measure_between("begin", "end")[0].energy_j == expected
        with pytest.raises(ValueError, match="ordered"):
            session.measure_between("end", "begin")
        with pytest.raises(ValueError, match="immutable"):
            session.checkpoint("begin")
        with pytest.raises(ValueError, match="reserved"):
            session.checkpoint("goal_start")
        with pytest.raises(ValueError, match="captured"):
            session.measure_between("begin", "missing")
        session.end_goal(); artifacts = session.finish_session()
        with pytest.raises(RuntimeError, match="active goal"):
            session.checkpoint("late")
        assert len(artifacts.samples) == 6


def test_periodic_and_checkpoint_reads_are_serialized():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    first_entered, second_entered, release = (threading.Event() for _ in range(3))

    class ContendedReader(Reader):
        def __init__(self):
            super().__init__([])
            self.calls = 0

        def read_energy(self):
            self.calls += 1
            ordinal = self.calls
            if ordinal == 3:
                first_entered.set()
                assert release.wait(3)
            if ordinal == 4:
                second_entered.set()
            return reading(ordinal * 100)

    session = MeasurementSession(ContendedReader(), environment=ENVIRONMENT)
    session.start_session(); session.start_goal()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(session.sample_goal)
        assert first_entered.wait(3)
        second = pool.submit(session.checkpoint, "concurrent")
        try:
            assert not second_entered.wait(0.05), "reader entered concurrently"
        finally:
            release.set()
        first.result(); second.result()
    session.end_goal(); artifacts = session.finish_session()
    package = [s for s in artifacts.samples if s.domain_id == "PACKAGE"]
    assert all(a.acquired_end_ns <= b.acquired_start_ns for a, b in zip(package, package[1:]))
    assert artifacts.measurements[0].energy_j == 300 / 1e6


def test_teardown_does_not_hold_lock_needed_by_sampling_thread():
    import threading
    stopped = threading.Event()

    def final_sample():
        try:
            session.sample_goal()
        except RuntimeError:
            stopped.set()

    def teardown():
        worker = threading.Thread(target=final_sample, daemon=True)
        worker.start()
        assert stopped.wait(2), "sampling shutdown blocked behind teardown lock"
        worker.join()

    session = MeasurementSession(
        Reader([reading(v) for v in (0, 100, 200)]),
        environment=ENVIRONMENT, teardown=teardown,
    )
    session.start_session(); session.start_goal(); session.end_goal()
    assert session.finish_session().measurements[0].energy_j == 100 / 1e6
