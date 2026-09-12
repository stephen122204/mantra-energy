import tempfile
import unittest
from pathlib import Path

from core.readers.energy_collector import EnergyCollector
from core.readers.energy_sample import EnergySample
from core.readers.rapl_reader import RAPLReader
from scripts.detect_hardware import rapl_domain_key
from tests.test_energy_collector import MockAdapter, MockReader


class FixtureReader(RAPLReader):
    @staticmethod
    def _socket_id_from_path(path):
        # Windows cannot create ':' names. Decode only the fixture's portable
        # path spelling, then exercise the unchanged production parser.
        return RAPLReader._socket_id_from_path(path.replace("__colon__", ":").replace("\\", "/"))


class TestGraceRaplDomains(unittest.TestCase):
    def test_detector_keys_repeated_dram_by_socket(self):
        self.assertEqual(rapl_domain_key("/power/intel-rapl:0", "package-0"),
                         "package-0")
        self.assertEqual(rapl_domain_key("/power/intel-rapl:0:0", "dram"),
                         "dram-0")
        self.assertEqual(rapl_domain_key("/power/intel-rapl:1:0", "dram"),
                         "dram-1")

    def test_native_sysfs_path_decoding(self):
        self.assertEqual(RAPLReader._socket_id_from_path("/sys/class/powercap/intel-rapl:1/intel-rapl:1:0/energy_uj"), 1)
        self.assertEqual(RAPLReader._socket_id_from_path("/sys/class/powercap/intel-rapl:0/energy_uj"), 0)

    def _zone(self, root, zone, name, energy, maximum):
        directory = root / zone.replace(":", "__colon__")
        directory.mkdir(parents=True)
        (directory / "name").write_text(name, encoding="utf-8")
        (directory / "energy_uj").write_text(str(energy), encoding="utf-8")
        (directory / "max_energy_range_uj").write_text(
            str(maximum), encoding="utf-8")
        return str(directory / "energy_uj")

    def _reader(self, root):
        paths = {
            "package-0": self._zone(root, "intel-rapl:0", "package-0", 10, 1000),
            "dram-0": self._zone(root, "intel-rapl:0/intel-rapl:0:0", "dram", 20, 200),
            "package-1": self._zone(root, "intel-rapl:1", "package-1", 30, 2000),
            "dram-1": self._zone(root, "intel-rapl:1/intel-rapl:1:0", "dram", 40, 400),
        }
        return FixtureReader({"paths": paths})

    def test_dual_socket_schema_preserves_path_name_parent_and_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = self._reader(Path(tmp))
            domains = {d.canonical_name: d for d in reader.get_measurement_schema().domains}

            self.assertEqual(set(domains), {
                "PACKAGE_SOCKET_0", "DRAM_SOCKET_0",
                "PACKAGE_SOCKET_1", "DRAM_SOCKET_1",
            })
            self.assertEqual(domains["DRAM_SOCKET_0"].kernel_name, "dram")
            self.assertEqual(domains["DRAM_SOCKET_0"].socket_id, 0)
            self.assertEqual(domains["DRAM_SOCKET_0"].parent_domain, "PACKAGE_SOCKET_0")
            self.assertEqual(domains["DRAM_SOCKET_1"].max_energy_range_uj, 400)
            self.assertTrue(domains["PACKAGE_SOCKET_1"].native_path.endswith("energy_uj"))
            self.assertEqual(domains["PACKAGE_SOCKET_1"].scope, "socket-wide")

    def test_each_domain_wraps_or_resets_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema = self._reader(Path(tmp)).get_measurement_schema()
            readings = [
                {"package-0": 950, "dram-0": 190, "package-1": 1000, "dram-1": 200},
                {"package-0": 25, "dram-0": 5, "package-1": 900, "dram-1": 260},
            ]
            adapter = MockAdapter()
            collector = EnergyCollector(MockReader(schema, readings), [adapter], 1, 1)
            collector._prev = readings[0]

            current = readings[1]
            measured = {}
            for descriptor in schema.domains:
                previous = readings[0][descriptor.native_key]
                value = current[descriptor.native_key]
                delta = collector._counter_delta(previous, value, descriptor)
                if delta is None:
                    continue
                measured[descriptor.canonical_name] = delta

            self.assertEqual(measured["PACKAGE_SOCKET_0"], 75)
            self.assertEqual(measured["DRAM_SOCKET_0"], 15)
            self.assertNotIn("PACKAGE_SOCKET_1", measured)  # reset, not a wrap
            self.assertEqual(measured["DRAM_SOCKET_1"], 60)
            self.assertNotEqual(
                measured["PACKAGE_SOCKET_0"], measured["DRAM_SOCKET_0"])
            sample = EnergySample(1, 1, "RAPL", 1, measured)
            self.assertIsNone(sample.total_uj)


if __name__ == "__main__":
    unittest.main()
