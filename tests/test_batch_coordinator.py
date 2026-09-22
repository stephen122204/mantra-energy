"""Fault injection for ordered, resumable batch dispatch and verified checkpoints."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from studies.energy_diagnosis.diagnostics.archive_results import (
    digest,
    export_bundle,
    verify_bundle,
    previous_receipt,
)
from studies.energy_diagnosis.diagnostics.batch_coordinator import Coordinator, dispatch


class Clock:
    def __init__(self):
        self.now = 0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def setup(tmp_path):
    source = tmp_path / "remote" / "results"
    source.mkdir(parents=True)
    spec = dict(
        host="host",
        remote_directory=str(source),
        remote_repository="/remote/repo",
        remote_python="/remote/python",
        cutoff_utc="1970-01-01T00:10:00Z",
        retry_seconds=1,
        first_poll_delay_seconds=1,
        minimum_batch_seconds=60,
        batches=[
            dict(id=f"b{i}", status=f"b{i}.json", log=f"b{i}.log", argv=["/bin/true"])
            for i in range(2)
        ],
    )
    clock = Clock()
    events = []
    job = dict(status="completed", returncode=0, cleanup_complete=True)

    def remote(action, data):
        events.append((action, data.get("id")))
        if action == "dispatch":
            (source / data["status"]).write_text(json.dumps(job))
            return {"status": "dispatched"}
        return dict(job)

    def archive(batch, destination, previous):
        events.append(("archive", batch["id"]))
        destination.mkdir()
        prior, link = previous_receipt(previous, "host", str(source))
        with (destination / "snapshot.bundle").open("wb") as stream:
            export_bundle(source, batch["status"], prior, stream, 1024**2)
        header = verify_bundle(destination / "snapshot.bundle", prior)
        receipt = dict(
            status="verified",
            host="host",
            remote_directory=str(source),
            previous=link,
            manifest=header,
            bundle_sha256=digest(destination / "snapshot.bundle"),
        )
        p = destination / "receipt.json"
        p.write_text(json.dumps(receipt))
        return p

    return spec, clock, events, job, remote, archive


def test_transport_and_backup_retries_do_not_advance_before_verification(tmp_path):
    spec, clock, events, job, remote, archive = setup(tmp_path)
    counts = {"dispatch": 0, "status": 0, "archive": 0}

    def flaky_remote(action, data):
        counts[action] += 1
        if counts[action] == 1:
            raise subprocess.CalledProcessError(255, ["ssh"])
        return remote(action, data)

    def flaky_archive(*args):
        counts["archive"] += 1
        if counts["archive"] == 1:
            args[1].mkdir()
            (args[1] / "partial").write_text("preserved")
            raise subprocess.CalledProcessError(255, ["ssh"])
        return archive(*args)

    out = tmp_path / "local"
    c = Coordinator(
        spec, out, flaky_remote, flaky_archive, clock=clock.time, sleep=clock.sleep
    )
    assert c.run()["completed"] == ["b0", "b1"]
    assert events.index(("archive", "b0")) < events.index(("dispatch", "b1"))
    assert (out / "b0-copy-000/partial").read_text() == "preserved"
    events.clear()
    assert (
        Coordinator(
            spec, out, remote, archive, clock=clock.time, sleep=clock.sleep
        ).run()["status"]
        == "completed"
    )
    assert not events
    receipt = Path(c.state["previous_receipt"])
    (receipt.parent / "snapshot.bundle").write_bytes(b"bad")
    with pytest.raises(ValueError, match="changed"):
        Coordinator(
            spec, out, remote, archive, clock=clock.time, sleep=clock.sleep
        ).run()


def test_invalid_batch_is_backed_up_but_next_never_dispatched(tmp_path):
    spec, clock, events, job, remote, archive = setup(tmp_path)
    job.update(status="interference_detected", returncode=76)
    c = Coordinator(
        spec, tmp_path / "local", remote, archive, clock=clock.time, sleep=clock.sleep
    )
    with pytest.raises(RuntimeError, match="evidence retained"):
        c.run()
    assert ("archive", "b0") in events and ("dispatch", "b1") not in events
    assert c.state["previous_receipt"] and not c.state["completed"]


def test_integrity_failure_and_changed_spec_stop(tmp_path):
    spec, clock, events, job, remote, archive = setup(tmp_path)

    def bad_archive(*args):
        raise ValueError("hash mismatch")

    c = Coordinator(
        spec,
        tmp_path / "local",
        remote,
        bad_archive,
        clock=clock.time,
        sleep=clock.sleep,
    )
    with pytest.raises(ValueError, match="hash"):
        c.run()
    assert ("dispatch", "b1") not in events
    spec["batches"][0]["argv"].append("changed")
    with pytest.raises(ValueError, match="specification changed"):
        Coordinator(
            spec,
            tmp_path / "local",
            remote,
            archive,
            clock=clock.time,
            sleep=clock.sleep,
        )


def test_budget_never_authorizes_new_job_near_cutoff(tmp_path):
    spec, clock, events, job, remote, archive = setup(tmp_path)
    clock.now = 550

    def no_budget(action, data):
        assert action == "dispatch" and data["allow_create"] is False
        return {"status": "not_dispatched"}

    with pytest.raises(RuntimeError, match="launch budget"):
        Coordinator(
            spec,
            tmp_path / "local",
            no_budget,
            archive,
            clock=clock.time,
            sleep=clock.sleep,
        ).run()
    assert not events


def test_dispatch_idempotent_and_changed_identity_refused(tmp_path):
    root = tmp_path / "results"
    request = dict(
        root=str(root),
        id="b0",
        argv=[sys.executable, "-c", 'print("one launch")'],
        cwd=str(tmp_path),
        status="status.json",
        log="launch.log",
        allow_create=True,
    )
    first = dispatch(request)
    assert first["status"] == "dispatched"
    assert dispatch(request)["status"] == "already_dispatched"
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not (root / "launch.log").read_text():
        time.sleep(0.01)
    assert (root / "launch.log").read_text().strip() == "one launch"
    request["argv"][-1] = 'print("changed")'
    with pytest.raises(ValueError, match="identity"):
        dispatch(request)


def test_ambiguous_intent_is_not_relaunched(tmp_path, monkeypatch):
    request = dict(
        root=str(tmp_path / "results"),
        id="b0",
        argv=["missing-command"],
        cwd=str(tmp_path),
        status="status.json",
        log="launch.log",
        allow_create=True,
    )

    def fail(*args, **kwargs):
        raise OSError("launch failure")

    monkeypatch.setattr(subprocess, "Popen", fail)
    with pytest.raises(OSError):
        dispatch(request)
    assert dispatch(request)["status"] == "already_dispatched"
