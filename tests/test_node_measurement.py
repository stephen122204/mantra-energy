"""Node lifecycle fixtures; no hardware, model, or optional packages required."""

import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch

from studies.energy_diagnosis.runtime.measurement import EnvironmentIdentity
from studies.energy_diagnosis.runtime.node_measurement import (
    FixtureCounterReader,
    NodeMeasurement,
)


ENVIRONMENT = EnvironmentIdentity(
    "fixture-commit", "fixture-host", "fixture-boot", "fixture-allocation",
    "fixture-cpus", ("fixture-gpu",), "simulated",
)


class Clock:
    def __init__(self):
        self.now = 1_000_000_000

    def __call__(self):
        return self.now


class ClockReader(FixtureCounterReader):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    def read_energy(self):
        return {
            "CPU_FIXTURE": self.clock.now // 1000,
            "GPU_FIXTURE": self.clock.now // 500,
        }


class NodeMeasurementTests(unittest.TestCase):
    def delayed_finish(self, delay_ns):
        clock = Clock()
        measured = NodeMeasurement(ClockReader(clock), ENVIRONMENT, session_id="fixture")
        measured.session._monotonic_ns = clock
        measured.session._wall_time_ns = clock
        worker = Mock()

        def join():
            clock.now += delay_ns

        worker.join.side_effect = join
        with patch(
            "studies.energy_diagnosis.runtime.node_measurement.threading.Thread",
            return_value=worker,
        ):
            measured.start_goal()
        clock.now += 100_000_000  # Identical completed work in both cases.
        artifacts = measured.finish_goal()
        worker.join.assert_called_once_with()
        self.assertTrue(measured.stop.is_set())
        self.assertIs(measured.artifacts, artifacts)
        return artifacts

    def test_delayed_join_cannot_extend_goal_or_cpu_gpu_endpoints(self):
        fast = self.delayed_finish(0)
        slow = self.delayed_finish(1_000_000_000)
        self.assertEqual(fast.goal_start_ns, slow.goal_start_ns)
        self.assertEqual(fast.goal_end_ns, slow.goal_end_ns)
        self.assertEqual(slow.goal_end_ns - slow.goal_start_ns, 100_000_000)
        self.assertEqual(fast.measurements, slow.measurements)
        self.assertEqual(fast.transitions, slow.transitions)
        self.assertEqual(fast.samples, slow.samples)
        endpoints = {
            s.domain_id: s.value for s in slow.samples if ":goal_end:" in s.sample_id
        }
        self.assertEqual(endpoints, {"CPU_FIXTURE": 1_100_000, "GPU_FIXTURE": 2_200_000})
        self.assertEqual(
            {m.domain_id: m.energy_j for m in slow.measurements},
            {"CPU_FIXTURE": 0.1, "GPU_FIXTURE": 0.2},
        )
        self.assertEqual(slow.session_end_ns - fast.session_end_ns, 1_000_000_000)

    def test_sampler_that_woke_before_stop_does_not_read_after_endpoint(self):
        measured = NodeMeasurement(FixtureCounterReader(), ENVIRONMENT)
        with patch(
            "studies.energy_diagnosis.runtime.node_measurement.threading.Thread"
        ) as thread:
            measured.start_goal()
            sample = thread.call_args.kwargs["target"]
            # Resume a sampler whose timed wait completed before stop was set.
            def join():
                with patch.object(measured.stop, "wait", side_effect=[False, True]):
                    sample()

            thread.return_value.join.side_effect = join
            artifacts = measured.finish_goal()
        self.assertIsNone(measured.sample_error)
        self.assertEqual(len(artifacts.samples), 6)  # Two domains, three endpoints.

    def test_normal_thread_lifecycle_and_checkpoint_boundaries(self):
        measured = NodeMeasurement(FixtureCounterReader(), ENVIRONMENT)
        sampled = threading.Event()
        original = measured.session.sample_goal

        def sample():
            original()
            sampled.set()

        with patch.object(measured.session, "sample_goal", side_effect=sample):
            start = measured.start_goal()
            try:
                self.assertTrue(sampled.wait(2), "sampler did not run")
                measured.checkpoint("initialized_model_start")
                measured.checkpoint("initialized_model_end")
            finally:
                artifacts = measured.finish_goal()
        self.assertFalse(measured.thread.is_alive())
        self.assertIsNone(measured.sample_error)
        self.assertEqual(start, artifacts.goal_start_ns)
        self.assertLessEqual(artifacts.goal_end_ns, artifacts.session_end_ns)
        inner = measured.measure_between("initialized_model_start", "initialized_model_end")
        self.assertTrue(all(m.status == "valid" for m in artifacts.measurements))
        self.assertTrue(all(start <= m.start_ns <= m.end_ns <= artifacts.goal_end_ns for m in inner))

    def test_inflight_sample_finishes_before_endpoint_without_deadlock(self):
        measured = NodeMeasurement(FixtureCounterReader(), ENVIRONMENT)
        entered, release = threading.Event(), threading.Event()
        original = measured.session.sample_goal

        def sample():
            entered.set()
            if not release.wait(2):
                raise RuntimeError("fixture release timed out")
            original()

        with patch.object(measured.session, "sample_goal", side_effect=sample), patch.object(
            measured.session, "end_goal", wraps=measured.session.end_goal,
        ) as endpoint, ThreadPoolExecutor(max_workers=1) as pool:
            measured.start_goal()
            try:
                self.assertTrue(entered.wait(2), "sampler did not run")
                finishing = pool.submit(measured.finish_goal)
                self.assertTrue(measured.stop.wait(2), "finish did not signal stop")
                endpoint.assert_not_called()
            finally:
                release.set()
            artifacts = finishing.result(timeout=2)
        self.assertFalse(measured.thread.is_alive())
        self.assertIsNone(measured.sample_error)
        self.assertEqual(len(artifacts.samples), 8)
        self.assertTrue(all(m.status == "valid" for m in artifacts.measurements))

    def test_endpoint_failure_still_joins_sampler(self):
        measured = NodeMeasurement(FixtureCounterReader(), ENVIRONMENT)
        with patch(
            "studies.energy_diagnosis.runtime.node_measurement.threading.Thread"
        ) as thread:
            measured.start_goal()
            with patch.object(measured.session, "end_goal", side_effect=RuntimeError("endpoint failure")):
                with self.assertRaisesRegex(RuntimeError, "endpoint failure"):
                    measured.finish_goal()
            thread.return_value.join.assert_called_once_with()
        self.assertTrue(measured.stop.is_set())
        self.assertIsNone(measured.artifacts)

    def test_sampler_failure_is_reported_after_artifacts_and_join(self):
        measured = NodeMeasurement(FixtureCounterReader(), ENVIRONMENT)
        failed = threading.Event()

        def fail():
            failed.set()
            raise ValueError("fixture sampler failure")

        with patch.object(measured.session, "sample_goal", side_effect=fail):
            measured.start_goal()
            try:
                self.assertTrue(failed.wait(2), "sampler did not run")
            finally:
                with self.assertRaisesRegex(RuntimeError, "fixture sampler failure"):
                    measured.finish_goal()
        self.assertFalse(measured.thread.is_alive())
        self.assertIsNotNone(measured.artifacts)


    def test_slow_operating_reads_charge_goal_and_delay_periodic_counters(self):
        """Diagnostic fake clock: preserves current boundaries, without sensor I/O."""
        clock = Clock()
        observed = []

        class SlowOperatingReader(ClockReader):
            def read_operating_state(self):
                begin = clock.now
                clock.now += 1_600_000_000
                observed.append((begin, clock.now, measured._sampling_lock.locked()))
                return dict(read_start_ns=begin, read_end_ns=clock.now, fields={})

        measured = NodeMeasurement(SlowOperatingReader(clock), ENVIRONMENT)
        measured.session._monotonic_ns = clock
        measured.session._wall_time_ns = clock
        with patch("studies.energy_diagnosis.runtime.node_measurement.time.monotonic_ns", clock), patch(
            "studies.energy_diagnosis.runtime.node_measurement.threading.Thread"
        ) as thread:
            start = measured.start_goal()
            self.assertEqual(clock.now - start, 1_600_000_000)  # initial read before work
            sample = thread.call_args.kwargs["target"]
            measured._next_operating_ns = 0
            with patch.object(measured.stop, "wait", side_effect=[False, False, True]):
                sample()
            work_finished = clock.now
            artifacts = measured.finish_goal()
        self.assertEqual([locked for _, _, locked in observed], [False, True, True])
        self.assertEqual(artifacts.goal_end_ns - work_finished, 1_600_000_000)
        self.assertEqual(artifacts.goal_end_ns - start, 4_800_000_000)
        # Consecutive counter readings include a periodic operating-state gap.
        cpu = [sample for sample in artifacts.samples if sample.domain_id == "CPU_FIXTURE"]
        self.assertTrue(any(b.acquired_start_ns - a.acquired_start_ns >= 1_600_000_000
                            for a, b in zip(cpu, cpu[1:])))


if __name__ == "__main__":
    unittest.main()
