"""Reproduce a native worker requiring the GIL while Python awaits completion."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeGilWaitTest(unittest.TestCase):
    def test_binding_releases_gil_and_negative_control_deadlocks(self):
        torch = importlib.util.find_spec('torch')
        compiler = shutil.which('c++')
        if torch is None or compiler is None:
            self.skipTest('native qualification requires PyTorch pybind headers and C++ compiler')
        include = Path(torch.origin).parent / 'include'
        patch = (ROOT / 'studies/energy_diagnosis/moe/patches/moe-infinity-transfer-lifecycle.patch').read_text()
        self.assertIn('+      .def("wait_expert", &ExpertDispatcher::WaitHiddenStates,\n+           py::call_guard<py::gil_scoped_release>())', patch)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for release in (True, False):
                with self.subTest(release=release):
                    module = 'native_wait_good' if release else 'native_wait_bad'
                    guard = ', py::call_guard<py::gil_scoped_release>()' if release else ''
                    source = tmp / (module + '.cpp')
                    source.write_text('''#include <pybind11/pybind11.h>
#include <thread>
#include <condition_variable>
#include <mutex>
namespace py = pybind11;
void wait_for_worker() {
  std::mutex mutex;
  std::condition_variable cv;
  bool done = false;
  std::thread worker([&] {
    // Tensor destruction can need Python refcount work on the native worker.
    py::gil_scoped_acquire acquire;
    { std::lock_guard<std::mutex> lock(mutex); done = true; }
    cv.notify_one();
  });
  std::unique_lock<std::mutex> lock(mutex);
  cv.wait(lock, [&] { return done; });
  lock.unlock();
  worker.join();
}
PYBIND11_MODULE(''' + module + ''', m) {
  m.def("wait_expert", &wait_for_worker''' + guard + ''');
}
''')
                    binary = tmp / (module + sysconfig.get_config_var('EXT_SUFFIX'))
                    command = [compiler, '-std=c++17', '-shared', '-fPIC', '-pthread',
                               '-I' + str(include), '-I' + sysconfig.get_path('include'),
                               str(source), '-o', str(binary)]
                    if sys.platform == 'darwin':
                        command += ['-undefined', 'dynamic_lookup']
                    subprocess.run(command, check=True, capture_output=True, timeout=90)
                    command = [sys.executable, '-c', f'import {module}; {module}.wait_expert()']
                    if release:
                        subprocess.run(command, cwd=tmp, check=True, timeout=5)
                    else:
                        with self.assertRaises(subprocess.TimeoutExpired):
                            subprocess.run(command, cwd=tmp, check=True, timeout=2)


if __name__ == '__main__':
    unittest.main()
