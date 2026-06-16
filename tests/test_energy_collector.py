"""
tests/test_energy_collector.py

Unit tests for EnergyCollector with mock reader — no DB required.
Tests verify: platform-agnostic sampling, delta computation,
wraparound correction, None handling, adapter fan-out.

Run: python3 -m pytest tests/test_energy_collector.py -v
"""

import threading
import time
import unittest
from typing import Dict, List, Optional
from unittest.mock import MagicMock

from core.readers.energy_collector import EnergyCollector
from core.readers.energy_sample import EnergySample
from core.readers.measurement_schema import (
    DomainDescriptor,
    MeasurementSchema,
    ENERGY_COUNTER,
    SCHEMA_RAPL_X86,
    SCHEMA_SPBM_ARM,
    SCHEMA_DUMMY,
)
from core.readers.persistence_adapter import PersistenceAdapter


class MockAdapter(PersistenceAdapter):
    """Test adapter that captures all received EnergySample objects."""

    def __init__(self):
        self.samples: List[EnergySample] = []
        self.flushed = False

    def write(self, sample: EnergySample) -> None:
        self.samples.append(sample)

    def flush(self) -> None:
        self.flushed = True


class MockReader:
    """Mock energy reader returning controlled counter values."""

    def __init__(self, schema: MeasurementSchema, readings: List[Dict]):
        self._schema = schema
        self._readings = readings    # sequence of read_energy() return values
        self._call_count = 0

    def get_measurement_schema(self) -> MeasurementSchema:
        return self._schema

    def read_energy(self) -> Dict[str, Optional[int]]:
        # Cycle through readings — last reading repeated if exhausted
        idx = min(self._call_count, len(self._readings) - 1)
        self._call_count += 1
        return self._readings[idx]

    def is_available(self) -> bool:
        return True

    def get_name(self) -> str:
        return "MockReader"


class TestEnergyCollectorBasic(unittest.TestCase):
    """Basic collector tests — delta computation and adapter fan-out."""

    def test_delta_computed_correctly(self):
        """Collector computes correct delta between two readings."""
        schema = SCHEMA_RAPL_X86
        readings = [
            {"package-0": 1000, "core": 500, "uncore": 100, "dram": 200},
            {"package-0": 1500, "core": 700, "uncore": 150, "dram": 300},
        ]
        reader = MockReader(schema, readings)
        adapter = MockAdapter()

        collector = EnergyCollector(reader, [adapter], run_id=1, source_id=1)
        collector.start()
        time.sleep(0.05)    # allow one tick at 100 Hz
        collector.stop()

        self.assertGreater(len(adapter.samples), 0)
        sample = adapter.samples[0]
        # PACKAGE delta: 1500 - 1000 = 500
        self.assertEqual(sample.get_domain("PACKAGE"), 500)
        self.assertEqual(sample.get_domain("CORE"), 200)
        self.assertTrue(adapter.flushed)

    def test_none_domain_skipped(self):
        """Domains returning None are absent from sample, not zero."""
        schema = SCHEMA_SPBM_ARM
        readings = [
            {"pkg": 1000, "cpu_p": 500, "cpu_e": None, "gpu": 2000},
            {"pkg": 1100, "cpu_p": 550, "cpu_e": None, "gpu": 2100},
        ]
        reader = MockReader(schema, readings)
        adapter = MockAdapter()

        collector = EnergyCollector(reader, [adapter], run_id=1, source_id=2)
        collector.start()
        time.sleep(0.15)    # allow one tick at 10 Hz
        collector.stop()

        self.assertGreater(len(adapter.samples), 0)
        sample = adapter.samples[0]
        # cpu_e returned None — must be absent, not zero
        self.assertFalse(sample.has_domain("CPU_E"))
        # pkg and cpu_p should be present
        self.assertTrue(sample.has_domain("PACKAGE"))
        self.assertTrue(sample.has_domain("CPU_P"))

    def test_wraparound_corrected(self):
        """32-bit counter wraparound corrected correctly."""
        # Simulate 32-bit RAPL counter wrapping
        wrap_max = 1 << 32
        schema = SCHEMA_RAPL_X86
        readings = [
            {"package-0": wrap_max - 100, "core": 0, "uncore": 0, "dram": 0},
            {"package-0": 200, "core": 0, "uncore": 0, "dram": 0},
            # Expected delta: 200 - (wrap_max - 100) + wrap_max = 300
        ]
        reader = MockReader(schema, readings)
        adapter = MockAdapter()

        collector = EnergyCollector(reader, [adapter], run_id=1, source_id=1)
        collector.start()
        time.sleep(0.05)
        collector.stop()

        self.assertGreater(len(adapter.samples), 0)
        sample = adapter.samples[0]
        # Wraparound: delta = 200 - (wrap_max-100) + wrap_max = 300
        self.assertEqual(sample.get_domain("PACKAGE"), 300)

    def test_empty_schema_no_op(self):
        """Collector with empty schema starts and stops without error."""
        reader = MockReader(SCHEMA_DUMMY, [{}])
        adapter = MockAdapter()

        collector = EnergyCollector(reader, [adapter], run_id=1, source_id=1)
        collector.start()
        time.sleep(0.05)
        collector.stop()

        # No samples written — empty schema produces nothing
        self.assertEqual(len(adapter.samples), 0)

    def test_multiple_adapters_receive_same_sample(self):
        """All registered adapters receive every sample."""
        schema = SCHEMA_SPBM_ARM
        readings = [
            {"pkg": 1000, "cpu_p": 500, "cpu_e": 100, "gpu": 2000},
            {"pkg": 1100, "cpu_p": 560, "cpu_e": 110, "gpu": 2050},
        ]
        reader = MockReader(schema, readings)
        adapter1 = MockAdapter()
        adapter2 = MockAdapter()

        collector = EnergyCollector(reader, [adapter1, adapter2], run_id=5, source_id=2)
        collector.start()
        time.sleep(0.2)
        collector.stop()

        # Both adapters receive identical sample count
        self.assertEqual(len(adapter1.samples), len(adapter2.samples))
        self.assertGreater(len(adapter1.samples), 0)

    def test_run_id_propagated_to_sample(self):
        """EnergySample carries the run_id set at collector construction."""
        schema = SCHEMA_RAPL_X86
        readings = [
            {"package-0": 100, "core": 50, "uncore": 10, "dram": 20},
            {"package-0": 200, "core": 100, "uncore": 20, "dram": 40},
        ]
        reader = MockReader(schema, readings)
        adapter = MockAdapter()

        collector = EnergyCollector(reader, [adapter], run_id=42, source_id=1)
        collector.start()
        time.sleep(0.05)
        collector.stop()

        self.assertGreater(len(adapter.samples), 0)
        for sample in adapter.samples:
            # Every sample must carry the correct run_id
            self.assertEqual(sample.run_id, 42)


class TestMeasurementSchema(unittest.TestCase):
    """Schema correctness tests."""

    def test_rapl_schema_domains(self):
        """RAPL schema has correct domain names and counter width."""
        self.assertEqual(SCHEMA_RAPL_X86.source, "RAPL")
        self.assertEqual(SCHEMA_RAPL_X86.counter_width_bits, 32)
        names = [d.native_key for d in SCHEMA_RAPL_X86.domains]
        self.assertIn("package-0", names)
        self.assertIn("core", names)

    def test_spbm_schema_domains(self):
        """SPBM schema has correct GN100 domains and 64-bit counters."""
        self.assertEqual(SCHEMA_SPBM_ARM.source, "SPBM")
        self.assertEqual(SCHEMA_SPBM_ARM.counter_width_bits, 64)
        names = [d.native_key for d in SCHEMA_SPBM_ARM.domains]
        self.assertIn("pkg", names)
        self.assertIn("cpu_e", names)   # previously lost — must be present
        self.assertIn("gpu", names)     # previously lost — must be present

    def test_dummy_schema_empty(self):
        """Dummy schema has no domains."""
        self.assertEqual(len(SCHEMA_DUMMY.domains), 0)


if __name__ == "__main__":
    unittest.main()
