"""Verified compressed incremental result snapshots over SSH, between batches.

Every snapshot retains its full manifest and only changed file bytes. Keep every
bundle and receipt in the chain. This is not a live-measurement backup service.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile

from .copy_results import digest, ssh_arguments

MAGIC = b"ALEMS-RESULT-ARCHIVE-1\n"
TERMINAL = {
    "completed",
    "failed",
    "timed_out",
    "interrupted",
    "interference_detected",
    "blocked_by_other_job",
}


def safe_name(name):
    if not isinstance(name, str) or not name or any(c in name for c in "\\\x00\r\n:"):
        raise ValueError("unsafe artifact path")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or str(path) != name
    ):
        raise ValueError("unsafe artifact path")
    return name


def validate_hashes(files):
    if not isinstance(files, dict):
        raise ValueError("invalid manifest")
    for name, value in files.items():
        safe_name(name)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("invalid artifact hash")
    return files


def manifest(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("result tree contains a symlink")
        if path.is_file():
            result[safe_name(path.relative_to(root).as_posix())] = digest(path)
    return result


def export_bundle(root, status_path, previous, output, max_bytes):
    root = Path(root).resolve()
    safe_name(status_path)
    validate_hashes(previous)
    status = json.loads((root / status_path).read_text())
    recovery = (root / status_path).parent.parent / "recovery.json"
    # A verified recovery record (nothing of the batch still running) makes an interrupted
    # batch's partial artifacts safe to snapshot; they must be backed up, not lost.
    recovered = recovery.exists() and json.loads(recovery.read_text()).get("status") == "interrupted"
    if status.get("status") not in TERMINAL and not recovered:
        raise ValueError("result job is not terminal; no live backup")
    files = manifest(root)
    changed = {
        name: value for name, value in files.items() if previous.get(name) != value
    }
    header = dict(
        protocol="result-archive-v1",
        files=files,
        changed=changed,
        deleted=sorted(set(previous) - set(files)),
        # A recovered batch is recorded as such, with its original (non-terminal) status.
        remote_job=status if not recovered or status.get("status") in TERMINAL
        else dict(status="interrupted_recovered", original_status=status.get("status")),
    )
    with tempfile.TemporaryFile() as archive:
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            for name in changed:
                tar.add(root / name, arcname=name, recursive=False)
        size = archive.tell()
        if size > max_bytes:
            raise ValueError("compressed snapshot exceeds explicit size bound")
        if manifest(root) != files:
            raise ValueError("result tree changed while snapshot was built")
        header["archive_bytes"] = size
        encoded = json.dumps(header, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > 16 * 1024 * 1024:
            raise ValueError("snapshot manifest exceeds size bound")
        output.write(MAGIC)
        output.write(encoded)
        archive.seek(0)
        shutil.copyfileobj(archive, output)
    return header


def verify_bundle(path, previous):
    validate_hashes(previous)
    with Path(path).open("rb") as stream:
        if stream.readline() != MAGIC:
            raise ValueError("invalid archive protocol")
        encoded = stream.readline(16 * 1024 * 1024 + 1)
        if len(encoded) > 16 * 1024 * 1024 or not encoded.endswith(b"\n"):
            raise ValueError("invalid manifest length")
        header = json.loads(encoded)
        if header.get("protocol") != "result-archive-v1":
            raise ValueError("unsupported manifest protocol")
        if header.get("remote_job", {}).get("status") not in TERMINAL | {"interrupted_recovered"}:
            raise ValueError("snapshot does not record a terminal job")
        files = validate_hashes(header["files"])
        changed = validate_hashes(header["changed"])
        if changed != {n: h for n, h in files.items() if previous.get(n) != h}:
            raise ValueError("increment does not match prior manifest")
        if header["deleted"] != sorted(set(previous) - set(files)):
            raise ValueError("deleted-file manifest differs")
        if type(header.get("archive_bytes")) is not int or header["archive_bytes"] < 0:
            raise ValueError("invalid archive size")
        if Path(path).stat().st_size - stream.tell() != header["archive_bytes"]:
            raise ValueError("truncated or trailing transport bytes")
        seen = set()
        with tarfile.open(fileobj=stream, mode="r|gz") as tar:
            for member in tar:
                name = safe_name(member.name)
                if not member.isfile() or name in seen or name not in changed:
                    raise ValueError("unexpected, duplicate or non-file archive member")
                source = tar.extractfile(member)
                h = hashlib.sha256()
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    h.update(block)
                if h.hexdigest() != changed[name]:
                    raise ValueError("archive content hash mismatch: " + name)
                seen.add(name)
        if seen != set(changed):
            raise ValueError("missing archive member")
    return header


def previous_receipt(path, host, remote):
    if path is None:
        return {}, None
    path = Path(path).resolve()
    receipt = json.loads(path.read_text())
    if (
        receipt.get("status") != "verified"
        or receipt["host"] != host
        or receipt["remote_directory"] != remote
    ):
        raise ValueError("previous snapshot does not match source or is unverified")
    bundle = path.parent / "snapshot.bundle"
    if digest(bundle) != receipt["bundle_sha256"]:
        raise ValueError("previous bundle changed")
    return validate_hashes(receipt["manifest"]["files"]), dict(
        path=str(path), sha256=digest(path)
    )


def verified_chain(receipt_path):
    """Validate every bundle and receipt without extracting any files."""
    chain, seen = [], set()
    path = Path(receipt_path).resolve()
    identity = None
    while True:
        if path in seen:
            raise ValueError("cyclic snapshot chain")
        seen.add(path)
        receipt = json.loads(path.read_text())
        current_identity = (receipt.get("host"), receipt.get("remote_directory"))
        if receipt.get("status") != "verified" or (
            identity and current_identity != identity
        ):
            raise ValueError("unverified or mismatched snapshot chain")
        identity = current_identity
        bundle = path.parent / "snapshot.bundle"
        if digest(bundle) != receipt["bundle_sha256"]:
            raise ValueError("bundle changed")
        chain.append((receipt, bundle))
        link = receipt.get("previous")
        if not link:
            break
        path = Path(link["path"]).resolve()
        if digest(path) != link["sha256"]:
            raise ValueError("previous receipt changed")
    prior = {}
    for receipt, bundle in reversed(chain):
        header = verify_bundle(bundle, prior)
        if header != receipt["manifest"]:
            raise ValueError("receipt differs from bundle")
        prior = header["files"]
    return chain, prior


def restore_snapshot(receipt_path, destination):
    """Verify the complete chain, then restore its latest view to a new directory."""
    chain, prior = verified_chain(receipt_path)
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=False)
    restored = set()
    for receipt, bundle in chain:
        with bundle.open("rb") as stream:
            stream.readline()
            stream.readline()
            with tarfile.open(fileobj=stream, mode="r|gz") as tar:
                for member in tar:
                    name = safe_name(member.name)
                    if name in restored or prior.get(name) != receipt["manifest"][
                        "changed"
                    ].get(name):
                        continue
                    out = target / name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with out.open("xb") as output:
                        shutil.copyfileobj(tar.extractfile(member), output)
                    restored.add(name)
    if manifest(target) != prior:
        raise ValueError("restored snapshot does not match full manifest")
    return dict(status="verified", files=len(prior), destination=str(target.resolve()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--restore-receipt")
    parser.add_argument("--host")
    parser.add_argument("--remote-python")
    parser.add_argument("--remote-repository")
    parser.add_argument("--identity-file")
    parser.add_argument("--known-hosts")
    parser.add_argument("--remote-directory")
    parser.add_argument("--remote-status")
    parser.add_argument("--destination")
    parser.add_argument("--previous-receipt")
    parser.add_argument("--max-archive-mib", type=int, default=512)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    if args.restore_receipt:
        if not args.destination or args.serve:
            parser.error("restore requires a new destination and cannot serve")
        print(json.dumps(restore_snapshot(args.restore_receipt, args.destination)))
        return 0
    if not args.remote_directory or not args.remote_status:
        parser.error("snapshot requires remote directory and status")
    # The server uses its native filesystem; the SSH receiver targets POSIX.
    root = (
        Path(args.remote_directory)
        if args.serve
        else PurePosixPath(args.remote_directory)
    )
    if not root.is_absolute() or len(root.parts) < 4 or ".." in root.parts:
        parser.error("explicit dedicated result directory required")
    safe_name(args.remote_status)
    if not 1 <= args.max_archive_mib <= 4096 or not 1 <= args.timeout <= 3600:
        parser.error("invalid archive bound or timeout")
    bound = args.max_archive_mib * 1024 * 1024
    if args.serve:
        prior = json.load(sys.stdin)
        export_bundle(root, args.remote_status, prior, sys.stdout.buffer, bound)
        return 0
    if (
        not all(
            [
                args.host,
                args.identity_file,
                args.known_hosts,
                args.destination,
                args.remote_python,
                args.remote_repository,
            ]
        )
        or args.host.startswith("-")
        or any(c.isspace() for c in args.host)
    ):
        parser.error(
            "receiving mode requires a valid host, identity, known hosts and new destination"
        )
    prior, link = previous_receipt(args.previous_receipt, args.host, str(root))
    out = Path(args.destination).resolve()
    out.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(out).free < bound + 64 * 1024 * 1024:
        raise ValueError("insufficient receiving disk space for bounded snapshot")
    remote = [
        args.remote_python,
        "-m",
        "studies.energy_diagnosis.diagnostics.archive_results",
        "--serve",
        "--remote-directory",
        str(root),
        "--remote-status",
        args.remote_status,
        "--max-archive-mib",
        str(args.max_archive_mib),
    ]
    command = ssh_arguments(args.identity_file, args.known_hosts) + [
        args.host,
        "cd "
        + shlex.quote(args.remote_repository)
        + " && "
        + shlex.join(["env", "PYTHONPATH=" + args.remote_repository] + remote),
    ]
    wire = out / "snapshot.partial"
    try:
        with wire.open("xb") as stream, (out / "transport.stderr").open("wb") as errors:
            subprocess.run(
                command,
                input=json.dumps(prior).encode(),
                stdout=stream,
                stderr=errors,
                check=True,
                timeout=args.timeout,
            )
        header = verify_bundle(wire, prior)
        wire.rename(out / "snapshot.bundle")
        receipt = dict(
            status="verified",
            host=args.host,
            remote_directory=str(root),
            previous=link,
            bundle_sha256=digest(out / "snapshot.bundle"),
            manifest=header,
        )
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(
            json.dumps(
                dict(
                    status="verified",
                    files=len(header["files"]),
                    changed=len(header["changed"]),
                    archive_bytes=header["archive_bytes"],
                    receipt=str(out / "receipt.json"),
                )
            )
        )
        return 0
    except Exception as error:
        (out / "failure.json").write_text(
            json.dumps(
                dict(
                    status="failed",
                    error=str(error),
                    error_type=type(error).__name__,
                    retryable_transport=isinstance(error, subprocess.TimeoutExpired)
                    or (
                        isinstance(error, subprocess.CalledProcessError)
                        and error.returncode == 255
                    ),
                ),
                indent=2,
            )
            + "\n"
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
