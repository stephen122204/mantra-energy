import sqlite3
import unittest
from pathlib import Path

from core.readers.gpu_collector import (
    GPUCollector,
    MEASUREMENT_SAMPLED_POWER,
    NVMLBackend,
)
from core.database.repositories.samples import SamplesRepository
from core.database.schema import CREATE_GPU_SAMPLES
from core.energy_engine import EnergyEngine


class _PowerBackend:
    SOURCE = "nvml"
    MEASUREMENT_KIND = MEASUREMENT_SAMPLED_POWER
    PHYSICAL_REFRESH_NOTE = "test refresh differs from polling"


class TestSampledPowerIntegration(unittest.TestCase):
    def setUp(self):
        self.collector = object.__new__(GPUCollector)
        self.collector.backend = _PowerBackend()
        self.collector.source = "nvml"
        self.collector._prev_energy_uj = None
        self.collector._prev_power_mw = None
        self.collector._prev_ts_ns = None
        self.collector._prev_monotonic_ns = None

    def observe(self, epoch_ns, monotonic_ns, power_mw):
        signals = {} if power_mw is None else {"power_mw": power_mw}
        sample = self.collector._build_sample(
            epoch_ns, monotonic_ns, MEASUREMENT_SAMPLED_POWER,
            None, power_mw, signals,
        )
        self.collector._prev_energy_uj = None
        self.collector._prev_power_mw = power_mw
        self.collector._prev_ts_ns = epoch_ns
        self.collector._prev_monotonic_ns = monotonic_ns
        return sample

    def test_varying_intervals_and_power_are_integrated(self):
        first = self.observe(1_000, 10_000, 100_000)
        rising = self.observe(200_001_000, 200_010_000, 200_000)
        falling = self.observe(300_001_000, 300_010_000, 100_000)

        self.assertFalse(first.coverage_complete)
        self.assertEqual(first.unavailable_reason, "missing_start_sample")
        self.assertIsNone(first.energy_uj)
        self.assertEqual(rising.interval_ns, 200_000_000)
        self.assertEqual(rising.energy_uj, 30_000_000)
        self.assertEqual(falling.interval_ns, 100_000_000)
        self.assertEqual(falling.energy_uj, 15_000_000)
        self.assertEqual(falling.power_start_mw, 200_000)
        self.assertEqual(falling.power_end_mw, 100_000)
        self.assertEqual(falling.measurement_kind, "sampled_power")
        self.assertIn("refresh", falling.physical_refresh_note)

    def test_missing_power_preserves_two_incomplete_intervals(self):
        self.observe(1_000, 10_000, 100_000)
        missing = self.observe(100_001_000, 100_010_000, None)
        after_gap = self.observe(200_001_000, 200_010_000, 120_000)

        for sample in (missing, after_gap):
            self.assertFalse(sample.coverage_complete)
            self.assertIsNone(sample.energy_uj)
            self.assertEqual(sample.unavailable_reason, "missing_power_endpoint")
        self.assertEqual(missing.power_start_mw, 100_000)
        self.assertIsNone(missing.power_end_mw)
        self.assertIsNone(after_gap.power_start_mw)
        self.assertEqual(after_gap.power_end_mw, 120_000)

    def test_raw_power_and_coverage_are_persisted(self):
        first = self.observe(1_000, 10_000, 100_000)
        complete = self.observe(100_001_000, 100_010_000, 120_000)
        connection = sqlite3.connect(":memory:")
        connection.executescript(CREATE_GPU_SAMPLES)
        connection.execute(
            "CREATE TABLE energy_domains (domain_id INTEGER PRIMARY KEY, "
            "name TEXT, description TEXT, parent_domain_id INTEGER, "
            "is_leaf INTEGER, is_cumulative INTEGER, unit TEXT, "
            "reader_keys TEXT, legacy_column TEXT)"
        )
        migration = Path("migrations/schema/v083_gpu_sample_provenance.sql")
        connection.executescript(migration.read_text(encoding="utf-8"))

        class _DB:
            conn = connection

        SamplesRepository(_DB()).insert_gpu_samples(7, [first, complete])
        rows = connection.execute(
            "SELECT measurement_kind, power_start_mw, power_end_mw, "
            "coverage_complete, unavailable_reason, monotonic_start_ns, "
            "monotonic_end_ns FROM gpu_samples ORDER BY sample_id"
        ).fetchall()
        self.assertEqual(rows[0][0:5], (
            "sampled_power", None, 100_000, 0, "missing_start_sample"))
        self.assertEqual(rows[1][0:5], (
            "sampled_power", 100_000, 120_000, 1, None))
        self.assertEqual(rows[1][6] - rows[1][5], 100_000_000)

    def test_nvml_power_fallback_never_returns_power_as_energy(self):
        backend = object.__new__(NVMLBackend)
        backend._handle = object()
        backend._has_energy_counter = False
        backend._has_power_reading = True

        class _NVML:
            NVML_CLOCK_SM = 0
            NVML_CLOCK_MEM = 1
            NVML_TEMPERATURE_GPU = 0

            @staticmethod
            def nvmlDeviceGetPowerUsage(_handle):
                return 175_000

            @staticmethod
            def nvmlDeviceGetUtilizationRates(_handle):
                raise RuntimeError("not supplied")

            @staticmethod
            def nvmlDeviceGetClockInfo(_handle, _kind):
                raise RuntimeError("not supplied")

            @staticmethod
            def nvmlDeviceGetMemoryInfo(_handle):
                raise RuntimeError("not supplied")

            @staticmethod
            def nvmlDeviceGetTemperature(_handle, _kind):
                raise RuntimeError("not supplied")

        backend._pynvml = _NVML()
        self.assertEqual(backend.measurement_kind, MEASUREMENT_SAMPLED_POWER)
        self.assertIsNone(backend.read_energy_uj())
        self.assertEqual(backend.read_signals()["power_mw"], 175_000)

    def test_unsupported_backend_is_explicitly_unavailable(self):
        sample = self.collector._build_sample(
            1_000, 10_000, None, None, None, {})
        self.assertFalse(sample.coverage_complete)
        self.assertIsNone(sample.energy_uj)
        self.assertEqual(sample.unavailable_reason,
                         "unsupported_energy_measurement")

    def test_partial_power_coverage_is_not_published_as_total(self):
        first = self.observe(1_000, 10_000, 100_000)
        complete = self.observe(100_001_000, 100_010_000, 120_000)
        missing = self.observe(200_001_000, 200_010_000, None)
        engine = object.__new__(EnergyEngine)
        engine.start_readings = {}
        engine.last_gpu_samples = [first, complete, missing]
        self.assertIsNone(engine._resolve_gpu_total_uj(None))


if __name__ == "__main__":
    unittest.main()
