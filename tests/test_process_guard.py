"""Pure process-topology checks plus actual supervisor fail-closed integration."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
from studies.energy_diagnosis.diagnostics.process_guard import (
    ProcessGuard,
    InterferenceDetected,
    snapshot,
)


def row(pid, parent=1, start=None, cpu=0, name="python"):
    return dict(
        pid=pid,
        ppid=parent,
        start_ticks=start or pid,
        cpu_ticks=cpu,
        uid=1000,
        name=name,
    )


def snap(rows, second=1, boot="boot"):
    return dict(
        boot_id=boot,
        monotonic_ns=second * 1_000_000_000,
        ticks_per_second=100,
        processes=rows,
    )


def test_owned_tree_allowed_external_job_and_pid_reuse_rejected(tmp_path):
    baseline = snap([row(1, 0, name="systemd"), row(10, name="daemon")])
    initial = snap(baseline["processes"] + [row(100), row(101, 100), row(102, 101)])
    readings = iter(
        [
            initial,
            snap(initial["processes"] + [row(103, 102)], 2),
            snap(initial["processes"] + [row(200)], 3),
        ]
    )
    guard = ProcessGuard(baseline, tmp_path / "log", 100, reader=lambda: next(readings))
    guard.check()
    with pytest.raises(InterferenceDetected, match="external process"):
        guard.check()
    records = [json.loads(line) for line in (tmp_path / "log").read_text().splitlines()]
    assert records[-1]["unexpected"][0]["pid"] == 200
    changed = snap(
        [row(1, 0, name="systemd"), row(10, start=99, name="daemon"), row(100)]
    )
    with pytest.raises(InterferenceDetected):
        ProcessGuard(baseline, tmp_path / "reused", 100, reader=lambda: changed)


def test_background_cpu_and_boot_change_stop(tmp_path):
    baseline = snap([row(10, name="daemon")])
    readings = iter([baseline, snap([row(10, cpu=50, name="daemon")], 2)])
    guard = ProcessGuard(baseline, tmp_path / "log", 100, reader=lambda: next(readings))
    with pytest.raises(InterferenceDetected, match="CPU budget"):
        guard.check()
    with pytest.raises(InterferenceDetected, match="another boot"):
        ProcessGuard(
            baseline, tmp_path / "boot", 100, reader=lambda: snap([], boot="new")
        )


def test_previously_owned_reparented_worker_is_retained_for_cleanup(tmp_path):
    # Teardown race: the supervisor exits before its worker is reaped, so the worker
    # is reparented to init. It is still owned work, not an external process.
    baseline = snap([row(1, 0, name="systemd")])
    readings = iter(
        [
            snap([row(1, 0, name="systemd"), row(100), row(101, 100), row(102, 101)]),
            snap([row(1, 0, name="systemd"), row(102, 1, cpu=500)], 2),
            snap([row(1, 0, name="systemd"), row(102, 1, cpu=500)], 3),
            snap([row(1, 0, name="systemd"), row(102, 1, cpu=500), row(300, 102)], 4),
        ]
    )
    guard = ProcessGuard(baseline, tmp_path / "log", 100, reader=lambda: next(readings))
    record = guard.check()
    assert record["reasons"] == [] and record["unexpected"] == []
    assert guard.surviving_owned() == [102]
    # Anything the orphan starts after leaving the owned tree was never observed as owned.
    with pytest.raises(InterferenceDetected, match="external process"):
        guard.check()


def test_linux_stat_parsing_handles_parentheses_and_skips_kernel_threads(tmp_path):
    boot = tmp_path / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("testboot")
    for pid, flags in [(10, 0), (20, 0x00200000)]:
        path = tmp_path / str(pid)
        path.mkdir()
        fields = [
            "S",
            "1",
            "0",
            "0",
            "0",
            "0",
            str(flags),
            "0",
            "0",
            "0",
            "0",
            "123",
            "45",
            "0",
            "0",
            "0",
            "0",
            "0",
            "0",
            "987",
        ]
        (path / "stat").write_text(f"{pid} (name (with spaces)) " + " ".join(fields))
    if sys.platform != "linux":
        pytest.skip("Linux sysconf clock tick snapshot")
    result = snapshot(tmp_path)
    assert len(result["processes"]) == 1
    actual = result["processes"][0]
    assert (
        actual["name"] == "name (with spaces)"
        and actual["start_ticks"] == 987
        and actual["cpu_ticks"] == 168
    )


def test_supervisor_records_guard_failure_and_cleans_owned_child(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("Linux guard integration")
    from studies.energy_diagnosis.diagnostics import run_bounded, process_guard
    import datetime as dt

    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(snap([])))

    class FakeGuard:
        def __init__(self, baseline, log, root):
            self.calls = 0

        def check(self):
            self.calls += 1
            raise InterferenceDetected("injected unrelated build")

        def surviving_owned(self):
            return []

    monkeypatch.setattr(process_guard, "ProcessGuard", FakeGuard)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_bounded",
            "--output",
            str(tmp_path / "job"),
            "--cwd",
            str(tmp_path),
            "--seconds",
            "5",
            "--cutoff-utc",
            (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat(),
            "--lock",
            str(tmp_path / "lock"),
            "--process-baseline",
            str(baseline),
            "--",
            sys.executable,
            "-c",
            "import time;time.sleep(60)",
        ],
    )
    assert run_bounded.main() == 76
    status = json.loads((tmp_path / "job/status.json").read_text())
    assert (
        status["status"] == "interference_detected"
        and status["measurement_batch_valid"] is False
    )
    assert status["cleanup_complete"] is True
    assert not run_bounded.alive(status["child_pid"])


def urow(pid, parent, uid, name):
    return dict(row(pid, parent, name=name), uid=uid)


def test_preauth_sshd_from_scanners_is_exempt_but_logins_and_cpu_are_not(tmp_path, monkeypatch):
    import studies.energy_diagnosis.diagnostics.process_guard as guard_module
    monkeypatch.setattr(guard_module, "_privsep_uids", lambda: {0, 105})
    listener = urow(50, 1, 0, "sshd")
    baseline = snap([row(1, 0, name="systemd"), listener, row(100)])
    scanner = [urow(300, 50, 0, "sshd"), urow(301, 300, 105, "sshd")]
    login = [urow(400, 50, 0, "sshd"), urow(401, 400, 1000, "sshd"), urow(402, 401, 1000, "bash")]
    readings = iter([
        baseline,
        snap(baseline["processes"] + scanner, 2),
        snap(baseline["processes"] + login, 3),
    ])
    guard = ProcessGuard(baseline, tmp_path / "log", 100, reader=lambda: next(readings))
    guard.check()  # unauthenticated connection handlers: not interference
    with pytest.raises(InterferenceDetected, match="external process"):
        guard.check()  # an authenticated session below sshd still stops the run
    # A pre-auth handler outside a baseline listener is not exempt.
    rogue = snap(baseline["processes"] + [urow(500, 1, 0, "sshd")], 2)
    readings = iter([baseline, rogue])
    guard = ProcessGuard(baseline, tmp_path / "rogue", 100, reader=lambda: next(readings))
    with pytest.raises(InterferenceDetected, match="external process"):
        guard.check()
    # Exempt handlers still count against the background CPU budget.
    busy = [urow(300, 50, 0, "sshd"), urow(301, 300, 105, "sshd")]
    readings = iter([snap(baseline["processes"] + busy, 1),
                     snap(baseline["processes"] + [urow(300, 50, 0, "sshd"), dict(urow(301, 300, 105, "sshd"), cpu_ticks=90)], 2)])
    guard = ProcessGuard(baseline, tmp_path / "cpu", 100, reader=lambda: next(readings))
    with pytest.raises(InterferenceDetected, match="CPU budget"):
        guard.check()


def test_supervisor_cpu_placement_is_applied_and_recorded(tmp_path):
    import datetime as dt
    import os
    from studies.energy_diagnosis.diagnostics.run_bounded import cpu_list
    assert cpu_list("8-10,3,9") == [3, 8, 9, 10]
    for invalid in ("", "4-2", "x"):
        with pytest.raises(ValueError):
            cpu_list(invalid)
    if sys.platform != "linux":
        pytest.skip("Linux affinity")
    cpu = min(os.sched_getaffinity(0))
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "studies.energy_diagnosis.diagnostics.run_bounded",
         "--output", str(tmp_path / "job"), "--cwd", str(tmp_path), "--seconds", "20",
         "--cutoff-utc", (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat(),
         "--lock", str(tmp_path / "lock"), "--supervisor-cpus", str(cpu), "--",
         sys.executable, "-c", "import os; print(sorted(os.sched_getaffinity(0)))"],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    status = json.loads((tmp_path / "job/status.json").read_text())
    assert status["supervisor_cpus"] == [cpu] and status["status"] == "completed"
    # Without its own affinity request the child inherits the supervisor placement.
    assert (tmp_path / "job/run.log").read_text().strip() == str([cpu])


def test_supervisor_captures_its_own_baseline_for_unattended_batches(tmp_path):
    import datetime as dt
    if sys.platform != "linux":
        pytest.skip("Linux guard integration")
    root = Path(__file__).resolve().parents[1]
    base = [sys.executable, "-m", "studies.energy_diagnosis.diagnostics.run_bounded", "--cwd", str(tmp_path),
            "--seconds", "20", "--cutoff-utc", (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat(),
            "--lock", str(tmp_path / "lock")]
    ok = subprocess.run(base + ["--output", str(tmp_path / "job"), "--capture-process-baseline", "--",
                                sys.executable, "-c", "print('ok')"], cwd=root, capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0, ok.stderr
    assert json.loads((tmp_path / "job/status.json").read_text())["status"] == "completed"
    assert json.loads((tmp_path / "job/process-baseline.json").read_text())["processes"]
    both = subprocess.run(base + ["--output", str(tmp_path / "both"), "--capture-process-baseline",
                                  "--process-baseline", str(tmp_path / "job/process-baseline.json"), "--", "true"],
                          cwd=root, capture_output=True, text=True, timeout=60)
    assert both.returncode == 2


def test_snapshot_skips_process_that_exits_during_stat_read(tmp_path, monkeypatch):
    # On Linux, reading /proc/<pid>/stat of a process that exited after the directory listing raises ESRCH
    # (ProcessLookupError), not FileNotFoundError. Seen on gigaio-08 (2026-10-01) as a failed batch:
    # "[Errno 3] No such process". The vanished process must simply be skipped.
    boot = tmp_path / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("testboot")
    fields = ["S", "1"] + ["0"] * 9 + ["123", "45"] + ["0"] * 6 + ["987"]
    for pid in (10, 11):
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "stat").write_text(f"{pid} (python) " + " ".join(fields))
    real_read = Path.read_text

    def read_text(self, *args, **kwargs):
        if self == tmp_path / "11" / "stat":
            raise ProcessLookupError(3, "No such process")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    result = snapshot(tmp_path)
    assert [row["pid"] for row in result["processes"]] == [10]
