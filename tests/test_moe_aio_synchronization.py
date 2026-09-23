"""Exercise the exact native notification helper at the lost-wakeup boundary."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("remove_lock", [False, True])
def test_predicate_update_cannot_overtake_waiter(tmp_path, remove_lock):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.fail("C++17 compiler required")
    header = (ROOT / "studies/energy_diagnosis/moe/native/transfer_lifecycle.h").read_text()
    if remove_lock:
        # Negative control: recreates the previous atomic-only notification.
        header = header.replace("std::lock_guard<std::mutex> lock(mutex);", "", 1)
    (tmp_path / "transfer_lifecycle.h").write_text(header)
    source = tmp_path / "test.cpp"
    source.write_text(r"""
#include "transfer_lifecycle.h"
#include <atomic>
#include <thread>
int main() {
  for (int i = 0; i < 20; ++i) {
    std::mutex mutex;
    std::condition_variable cv;
    std::atomic<bool> ready{false}, entered{false};
    std::unique_lock<std::mutex> lock(mutex);
    // The waiter has observed a false predicate and has not yet slept.
    if (ready.load()) return 10;
    std::thread notifier([&] {
      entered.store(true);
      alems::update_and_notify(mutex, cv, [&] { ready.store(true); });
    });
    while (!entered.load()) std::this_thread::yield();
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    bool overtook = ready.load();
    bool woke = cv.wait_for(lock, std::chrono::seconds(1),
                            [&] { return ready.load(); });
    lock.unlock();
    notifier.join();
    if (overtook) return 11;
    if (!woke) return 12;
  }
}
""")
    binary = tmp_path / "test"
    subprocess.run([compiler, "-std=c++17", "-pthread", "-I", str(tmp_path),
                    str(source), "-o", str(binary)], check=True, timeout=60)
    result = subprocess.run([str(binary)], timeout=30)
    assert result.returncode == (11 if remove_lock else 0)


def test_patch_uses_waiter_mutex_for_all_aio_notifications():
    patch = (ROOT / "studies/energy_diagnosis/moe/patches/"
             "moe-infinity-transfer-lifecycle.patch").read_text()
    added = "\n".join(line[1:] for line in patch.splitlines()
                      if line.startswith("+") and not line.startswith("+++"))
    assert added.count("update_and_notify(io_request->mutex, io_request->cv") == 2
    assert "update_and_notify(schedule_mutex_, schedule_cv_, [&]" in added
    assert "update_and_notify(schedule_mutex_, schedule_cv_, [] {})" in added


def test_dispatch_completion_notifications_share_waiter_mutex():
    patch = (ROOT / "studies/energy_diagnosis/moe/patches/"
             "moe-infinity-transfer-lifecycle.patch").read_text()
    section = patch.split("diff --git a/core/parallel/expert_dispatcher.cpp", 1)[1].split("diff --git ", 1)[0]
    added = "\n".join(line[1:] for line in section.splitlines()
                      if line.startswith("+") and not line.startswith("+++"))
    # Normal completion, route publication and failure all wake the same waiter.
    assert added.count("update_and_notify(pending_mutex_, pending_cv_") == 3
    assert '#include "prefetch/alems_transfer_lifecycle.h"' in added


def test_native_wait_binding_releases_python_lock():
    patch = (ROOT / "studies/energy_diagnosis/moe/patches/"
             "moe-infinity-transfer-lifecycle.patch").read_text()
    assert ('+      .def("wait_expert", &ExpertDispatcher::WaitHiddenStates,\n'
            '+           py::call_guard<py::gil_scoped_release>())') in patch
