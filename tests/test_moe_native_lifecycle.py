"""Compile and exercise the same C++ lifecycle installed into the GPU queue."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_native_lifecycle(tmp_path):
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.fail("A C++17 compiler is required for native lifecycle acceptance")
    source = tmp_path / "lifecycle.cpp"
    source.write_text(
        r"""
#include "transfer_lifecycle.h"
#include <cassert>
#include <limits>
#include <thread>
int main() {
  alems::TransferLedger ledger;
  auto a = ledger.admit(1, 64, 64, 10, 0, "cpu");
  assert(a && ledger.inflight() == 64);
  assert(!ledger.admit(2, 1, 64, 10, 0, "cpu"));
  assert(!ledger.admit(1, 1, 1000, 10, 0, "cpu"));
  a->start(); a->finish("completed", 64); a->finish("failed", 0);
  a.reset(); assert(ledger.inflight() == 0);
  auto records = ledger.drain(); assert(records.size() == 1);
  assert(records[0].outcome == "completed" && records[0].transferred_bytes == 64);
  assert(records[0].enqueue_ns <= records[0].start_ns);
  assert(records[0].start_ns <= records[0].end_ns);
  // The same expert can be admitted again after eviction; no stale tombstone.
  { auto b = ledger.admit(1, 64, 64, 11, 0, "cpu"); assert(b); }
  assert(ledger.inflight() == 0);
  records = ledger.drain(); assert(records.size() == 1);
  assert(records[0].outcome == "cancelled" && records[0].transferred_bytes == 0);
  // Queue removal must not retire a transfer still owned by the worker.
  auto queued = ledger.admit(3, 32, 64, 12, 0, "cpu");
  auto worker = queued; worker->start(); queued.reset();
  assert(ledger.inflight() == 32);
  worker->finish("failed", 0); worker.reset();
  assert(ledger.inflight() == 0); ledger.drain();
  assert(!ledger.admit(1, -1, 100, 1, 0, "cpu"));
  assert(!ledger.admit(1, 1, -1, 1, 0, "cpu"));
  auto big = ledger.admit(1, std::numeric_limits<long long>::max(),
                          std::numeric_limits<long long>::max(), 1, 0, "cpu");
  assert(big && !ledger.admit(2, 1, std::numeric_limits<long long>::max(), 1, 0, "cpu"));
  big.reset(); ledger.drain();
  std::vector<std::thread> workers;
  for (unsigned i = 0; i < 8; ++i) workers.emplace_back([&, i] {
    for (unsigned j = 0; j < 1000; ++j) {
      auto t = ledger.admit(i, 16, 128, j, 0, "cpu");
      assert(t); t->start(); t->finish(j % 2 ? "completed" : "failed", j % 2 ? 16 : 0);
    }
  });
  for (auto& w : workers) w.join();
  assert(ledger.inflight() == 0 && ledger.drain().size() == 8000);
  for (unsigned j = 0; j < 66000; ++j) { auto t = ledger.admit(1, 1, 1, j, 0, "cpu"); }
  assert(ledger.dropped() == 464 && ledger.inflight() == 0);
}
""",
        encoding="utf-8",
    )
    binary = tmp_path / "lifecycle"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-pthread",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(ROOT / "studies/energy_diagnosis/moe/native"),
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
        timeout=60,
    )
    subprocess.run([str(binary)], check=True, timeout=30)
