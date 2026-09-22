"""Serial bounded batches with verified off-node checkpoints and transport retries.

The remote launch command owns its timeout, exclusive measurement window and
cleanup. During measurement it must prevent new SSH inspection sessions (or use
another isolation mechanism); the coordinator does not make SSH polling free.
No later batch is dispatched until the prior terminal output is verified locally.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import time

from .archive_results import previous_receipt, safe_name, verified_chain
from .copy_results import ssh_arguments

TERMINAL = {
    "completed",
    "failed",
    "interrupted",
    "timed_out",
    "interference_detected",
    "blocked_by_other_job",
}


def write(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.replace(path)


def dispatch(request):
    """Remote intent marker prevents duplicate launch after an uncertain SSH result."""
    root = Path(request["root"]).resolve()
    name = safe_name(request["id"])
    if "/" in name:
        raise ValueError("batch id must be one path component")
    intent = root / "dispatch" / f"{name}.json"
    intent.parent.mkdir(parents=True, exist_ok=True)
    identity = dict(argv=request["argv"], cwd=request["cwd"], status=request["status"])
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()
    ).hexdigest()
    if intent.exists():
        existing = json.loads(intent.read_text())
        if existing["fingerprint"] != fingerprint:
            raise ValueError("changed batch launch identity")
        return dict(status="already_dispatched", intent=existing)
    if not request["allow_create"]:
        return dict(
            status="not_dispatched", reason="insufficient remaining launch budget"
        )
    # A crash after this marker but before Popen is intentionally ambiguous:
    # never silently rerun an experiment whose launch outcome is unknown.
    with intent.open("x") as f:
        f.write(
            json.dumps(
                dict(
                    fingerprint=fingerprint, status="dispatch_intent", identity=identity
                )
            )
        )
    logfile = root / safe_name(request["log"])
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with logfile.open("xb") as output:
        child = subprocess.Popen(
            request["argv"],
            cwd=request["cwd"],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    result = dict(
        fingerprint=fingerprint, status="dispatched", pid=child.pid, identity=identity
    )
    write(intent, result)
    return result


def validate(spec):
    if spec["host"].startswith("-") or any(c.isspace() for c in spec["host"]):
        raise ValueError("invalid host")
    for key in ["remote_directory", "remote_repository", "remote_python"]:
        path = PurePosixPath(spec[key])
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("explicit remote paths required")
    if len(PurePosixPath(spec["remote_directory"]).parts) < 4:
        raise ValueError("dedicated result directory required")
    cutoff = dt.datetime.fromisoformat(spec["cutoff_utc"].replace("Z", "+00:00"))
    if cutoff.utcoffset() != dt.timedelta(0):
        raise ValueError("UTC cutoff required")
    for key in ["retry_seconds", "first_poll_delay_seconds", "minimum_batch_seconds"]:
        if type(spec[key]) not in (int, float) or not 0 < spec[key] <= 86400:
            raise ValueError("invalid time budget")
    names = []
    for batch in spec["batches"]:
        names.append(safe_name(batch["id"]))
        if "/" in batch["id"]:
            raise ValueError("batch id must be one component")
        safe_name(batch["status"])
        safe_name(batch["log"])
        if not batch["argv"] or not all(
            isinstance(a, str) and "\x00" not in a for a in batch["argv"]
        ):
            raise ValueError("invalid launch argv")
    if not names or len(set(names)) != len(names):
        raise ValueError("empty or duplicate batches")
    return cutoff.timestamp()


class Coordinator:
    def __init__(
        self, spec, out, remote, archive, *, clock=time.time, sleep=time.sleep
    ):
        self.spec = spec
        self.out = Path(out)
        self.remote = remote
        self.archive = archive
        self.clock = clock
        self.sleep = sleep
        self.cutoff = validate(spec)
        self.out.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        self.state_path = self.out / "state.json"
        self.state = (
            json.loads(self.state_path.read_text())
            if self.state_path.exists()
            else dict(spec_sha256=identity, completed=[], previous_receipt=None)
        )
        if self.state["spec_sha256"] != identity:
            raise ValueError("coordinator specification changed")

    def save(self, **extra):
        self.state.update(extra)
        write(self.state_path, self.state)

    def run(self):
        if self.state["previous_receipt"]:
            verified_chain(self.state["previous_receipt"])
        for batch in self.spec["batches"]:
            if batch["id"] in self.state["completed"]:
                continue
            if self.state["previous_receipt"]:
                previous_receipt(
                    self.state["previous_receipt"],
                    self.spec["host"],
                    self.spec["remote_directory"],
                )
            self.save(status="dispatching_or_rejoining", batch=batch["id"])
            while True:
                if self.clock() >= self.cutoff:
                    raise TimeoutError("cutoff reached; no new dispatch")
                request = dict(
                    root=self.spec["remote_directory"],
                    id=batch["id"],
                    argv=batch["argv"],
                    cwd=self.spec["remote_repository"],
                    status=batch["status"],
                    log=batch["log"],
                    allow_create=self.clock() + self.spec["minimum_batch_seconds"]
                    < self.cutoff,
                )
                try:
                    reply = self.remote("dispatch", request)
                    if reply.get("status") == "not_dispatched":
                        raise RuntimeError("insufficient remaining launch budget")
                    if reply.get("status") not in {"dispatched", "already_dispatched"}:
                        raise ValueError("invalid dispatch response")
                    break
                except (OSError, subprocess.SubprocessError) as error:
                    self.save(status="retrying_dispatch", error=str(error))
                    self.sleep(self.spec["retry_seconds"])
            self.sleep(self.spec["first_poll_delay_seconds"])
            while True:
                if self.clock() >= self.cutoff:
                    raise TimeoutError("terminal batch not confirmed before cutoff")
                try:
                    job = self.remote("status", batch)
                    if job.get("status") in TERMINAL:
                        break
                    if job.get("status") not in {"starting", "running"}:
                        raise ValueError("unrecognized job status")
                except (OSError, subprocess.SubprocessError) as error:
                    self.save(status="waiting_for_terminal_batch", error=str(error))
                self.sleep(self.spec["retry_seconds"])
            self.save(status="backing_up", remote_job=job)
            attempt = 0
            while True:
                if self.clock() >= self.cutoff:
                    raise TimeoutError("backup cutoff reached; no next launch")
                destination = self.out / f"{batch['id']}-copy-{attempt:03d}"
                attempt += 1
                if destination.exists():
                    continue
                try:
                    receipt = self.archive(
                        batch, destination, self.state["previous_receipt"]
                    )
                    previous_receipt(
                        receipt, self.spec["host"], self.spec["remote_directory"]
                    )
                    saved = json.loads(Path(receipt).read_text())
                    if saved["manifest"]["remote_job"] != job:
                        raise ValueError("job changed between terminal read and backup")
                    break
                except (OSError, subprocess.SubprocessError) as error:
                    self.save(
                        status="retrying_backup",
                        error=str(error),
                        failed_destination=str(destination),
                    )
                    self.sleep(self.spec["retry_seconds"])
            self.save(previous_receipt=str(receipt))
            if (
                job["status"] != "completed"
                or job.get("returncode") != 0
                or not job.get("cleanup_complete")
            ):
                self.save(status="stopped_invalid_batch")
                raise RuntimeError("batch failed; evidence retained; no next launch")
            self.state["completed"].append(batch["id"])
            self.save(status="batch_verified")
        self.save(status="completed")
        return self.state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec")
    parser.add_argument("--output")
    parser.add_argument("--dispatch-json")
    args = parser.parse_args()
    if args.dispatch_json:
        print(json.dumps(dispatch(json.loads(args.dispatch_json))))
        return 0
    if not args.spec or not args.output:
        parser.error("spec and output required")
    if os.name != "posix":
        parser.error(
            "coordinator host requires POSIX advisory locking; archive tools remain portable"
        )
    import fcntl

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / "coordinator.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    spec = json.loads(Path(args.spec).read_text())
    validate(spec)
    ssh = ssh_arguments(spec["identity_file"], spec["known_hosts"]) + [spec["host"]]

    def remote(action, data):
        if action == "dispatch":
            argv = [
                "env",
                "PYTHONPATH=" + spec["remote_repository"],
                spec["remote_python"],
                "-m",
                "studies.energy_diagnosis.diagnostics.batch_coordinator",
                "--dispatch-json",
                json.dumps(data),
            ]
            command = shlex.join(argv)
        else:
            command = "cat " + shlex.quote(
                str(PurePosixPath(spec["remote_directory"]) / data["status"])
            )
        return json.loads(
            subprocess.check_output(ssh + [command], text=True, timeout=35)
        )

    def archive(batch, destination, previous):
        argv = [
            sys.executable,
            "-m",
            "studies.energy_diagnosis.diagnostics.archive_results",
            "--host",
            spec["host"],
            "--identity-file",
            spec["identity_file"],
            "--known-hosts",
            spec["known_hosts"],
            "--remote-python",
            spec["remote_python"],
            "--remote-repository",
            spec["remote_repository"],
            "--remote-directory",
            spec["remote_directory"],
            "--remote-status",
            batch["status"],
            "--destination",
            str(destination),
        ]
        if previous:
            argv += ["--previous-receipt", previous]
        with (out / (destination.name + ".log")).open("w") as log:
            try:
                subprocess.run(
                    argv, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1000
                )
            except subprocess.CalledProcessError:
                failure = destination / "failure.json"
                if not failure.exists() or not json.loads(failure.read_text()).get(
                    "retryable_transport"
                ):
                    raise ValueError(
                        "backup failed integrity/source validation; see preserved failure report"
                    )
                raise
        return destination / "receipt.json"

    controller = Coordinator(spec, out, remote, archive)
    try:
        controller.run()
    except BaseException as error:
        controller.save(status="stopped", error=str(error))
        raise
    print(json.dumps(controller.state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
