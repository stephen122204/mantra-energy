"""Recovery and corruption checks for incremental, quiescent result backups."""
import io
import json
import tarfile
from pathlib import Path

import pytest

from studies.energy_diagnosis.diagnostics.archive_results import (
    MAGIC,
    digest,
    export_bundle,
    manifest,
    previous_receipt,
    restore_snapshot,
    safe_name,
    verify_bundle,
)


def snapshot(root, out, previous=None):
    out.mkdir()
    prior, link = previous_receipt(previous, "test-host", str(root))
    with (out / "snapshot.bundle").open("wb") as stream:
        export_bundle(root, "job/status.json", prior, stream, 1024 * 1024)
    header = verify_bundle(out / "snapshot.bundle", prior)
    receipt = dict(
        status="verified",
        host="test-host",
        remote_directory=str(root),
        previous=link,
        bundle_sha256=digest(out / "snapshot.bundle"),
        manifest=header,
    )
    path = out / "receipt.json"
    path.write_text(json.dumps(receipt))
    return path, header


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "results"
    (root / "job").mkdir(parents=True)
    (root / "job/status.json").write_text('{"status":"completed"}')
    (root / "unchanged.txt").write_text("preserve this")
    (root / "changed.txt").write_text("old")
    (root / "deleted.txt").write_text("gone later")
    return root


def test_incremental_chain_restores_latest_and_preserves_old(root, tmp_path):
    first, h1 = snapshot(root, tmp_path / "first")
    first_hash = digest(first.parent / "snapshot.bundle")
    (root / "changed.txt").write_text("new")
    (root / "deleted.txt").unlink()
    (root / "new.txt").write_text("added")
    second, h2 = snapshot(root, tmp_path / "second", first)
    assert set(h2["changed"]) == {"changed.txt", "new.txt"}
    assert h2["deleted"] == ["deleted.txt"]
    assert len(h2["changed"]) < len(h2["files"])
    restored = tmp_path / "restored"
    assert restore_snapshot(second, restored)["status"] == "verified"
    assert manifest(restored) == manifest(root)
    restore_snapshot(first, tmp_path / "old-restored")
    assert (tmp_path / "old-restored/changed.txt").read_text() == "old"
    assert digest(first.parent / "snapshot.bundle") == first_hash
    with pytest.raises(FileExistsError):
        restore_snapshot(second, restored)


def test_active_job_and_symlink_refused(root, tmp_path):
    (root / "job/status.json").write_text('{"status":"running"}')
    with pytest.raises(ValueError, match="not terminal"):
        export_bundle(root, "job/status.json", {}, io.BytesIO(), 1024**2)
    (root / "job/status.json").write_text('{"status":"completed"}')
    try:
        (root / "linked").symlink_to(root / "changed.txt")
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(ValueError, match="symlink"):
        export_bundle(root, "job/status.json", {}, io.BytesIO(), 1024**2)


def test_mutation_during_export_refused(root, monkeypatch):
    original = tarfile.TarFile.add

    def changing(tar, *args, **kwargs):
        result = original(tar, *args, **kwargs)
        (root / "changed.txt").write_text("mutated after initial manifest")
        return result

    monkeypatch.setattr(tarfile.TarFile, "add", changing)
    with pytest.raises(ValueError, match="changed while"):
        export_bundle(root, "job/status.json", {}, io.BytesIO(), 1024**2)


def test_corrupt_transport_and_chain_refused(root, tmp_path):
    first, _ = snapshot(root, tmp_path / "first")
    bundle = first.parent / "snapshot.bundle"
    original = bundle.read_bytes()
    bundle.write_bytes(original[:-1])
    with pytest.raises(ValueError, match="truncated"):
        verify_bundle(bundle, {})
    with pytest.raises(ValueError, match="changed"):
        previous_receipt(first, "test-host", str(root))
    bundle.write_bytes(original)
    with pytest.raises(ValueError, match="source"):
        previous_receipt(first, "wrong-host", str(root))
    second, _ = snapshot(root, tmp_path / "second", first)
    first.write_text(first.read_text() + " ")
    with pytest.raises(ValueError, match="receipt changed"):
        restore_snapshot(second, tmp_path / "restored")


@pytest.mark.parametrize(
    "name", ["../x", "/x", "a/../x", "a//x", "a\\x", "C:x", "./x", ""]
)
def test_unsafe_names_refused(name):
    with pytest.raises(ValueError):
        safe_name(name)


@pytest.mark.parametrize("kind", ["hash", "duplicate", "symlink", "missing"])
def test_invalid_archive_members_refused(root, tmp_path, kind):
    receipt, header = snapshot(root, tmp_path / "first")
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for name in header["changed"]:
            if kind == "missing" and name == "changed.txt":
                continue
            data = (root / name).read_bytes()
            if kind == "hash" and name == "changed.txt":
                data = b"tampered"
            member = tarfile.TarInfo(name)
            member.size = len(data)
            if kind == "symlink" and name == "changed.txt":
                member.type = tarfile.SYMTYPE
                member.linkname = "/outside"
                member.size = 0
            tar.addfile(member, io.BytesIO(data))
            if kind == "duplicate" and name == "changed.txt":
                tar.addfile(member, io.BytesIO(data))
    header["archive_bytes"] = len(raw.getvalue())
    bundle = receipt.parent / "bad.bundle"
    bundle.write_bytes(MAGIC + json.dumps(header).encode() + b"\n" + raw.getvalue())
    with pytest.raises(ValueError):
        verify_bundle(bundle, {})


def test_server_cli_round_trip(root, tmp_path):
    import subprocess
    import sys

    bundle = tmp_path / "wire.bundle"
    with bundle.open("wb") as out:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "studies.energy_diagnosis.diagnostics.archive_results",
                "--serve",
                "--remote-directory",
                str(root),
                "--remote-status",
                "job/status.json",
            ],
            input=b"{}",
            stdout=out,
            check=True,
            timeout=10,
        )
    assert verify_bundle(bundle, {})["files"] == manifest(root)
