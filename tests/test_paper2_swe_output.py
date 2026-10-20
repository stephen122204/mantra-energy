"""SWE-bench runner output that is not plain UTF-8 text (agent-written files in another encoding, CR bytes)."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from studies.paper2.cohort import swebench_workload as sw

EMIT = "import sys; sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))"

# "docker exec -w /testbed C bash -lc SCRIPT" runs SCRIPT in $FAKE_TESTBED (a real git repository);
# "docker rm" is a no-op.
LOCAL_DOCKER = r'''#!/bin/sh
case "$1" in
  exec) shift 5; cd "$FAKE_TESTBED" && exec bash "$@" ;;
  *) exit 0 ;;
esac
'''


def emit(hexdata):
    return [sys.executable, "-c", EMIT, hexdata]


@pytest.mark.parametrize("data", ["hello\n", "a\r\nb\rc\n", "café ✓\n", ""])
def test_valid_utf8_tool_output_is_unchanged_from_text_mode(data):
    argv = emit(data.encode().hex())
    want = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8").stdout
    assert sw.run_cmd(argv, 30)[1] == want


def test_invalid_utf8_tool_output_is_replaced_not_raised_and_raw_is_exact():
    raw = b"x\x8fy\r\n"
    rc, out, _ = sw.run_cmd(emit(raw.hex()), 30)
    assert rc == 0 and out == "x�y\n"
    assert sw.run_cmd(emit(raw.hex()), 30, raw=True)[1] == raw


def git(repo, *args, **kw):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, **kw).stdout


def base_repo(path):
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@t"); git(path, "config", "user.name", "t")
    (path / "mod.py").write_text("def f():\n    return 1\n")
    (path / "crlf.txt").write_bytes(b"one\r\ntwo\r\n")
    git(path, "add", "-A"); git(path, "commit", "-q", "-m", "base")
    return path


def agent_runtime(tmp_path, monkeypatch, edit):
    testbed = base_repo(tmp_path / "testbed")
    edit(testbed)
    docker = tmp_path / "docker"
    docker.write_text(LOCAL_DOCKER)
    docker.chmod(0o755)
    monkeypatch.setenv("FAKE_TESTBED", str(testbed))
    shim = tmp_path / "bin"                      # coreutils timeout is absent on some developer machines
    shim.mkdir()
    (shim / "timeout").write_text('#!/bin/sh\nshift\nexec "$@"\n')
    (shim / "timeout").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")
    rt = sw.SweBenchRuntime(tmp_path / "sess", docker=str(docker))
    rt.workspace = tmp_path / "ws"
    rt.workspace.mkdir()
    rt.container = "p2-test"
    return rt, testbed


def applied_tree(tmp_path, patch: Path):
    """Apply the stored patch to a fresh base checkout with the harness's first command."""
    fresh = base_repo(tmp_path / "fresh")
    subprocess.run(["git", "apply", "--verbose", str(patch)], cwd=fresh, check=True, capture_output=True)
    return fresh


def tree_hashes(repo):
    return {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(repo.rglob("*")) if p.is_file() and ".git" not in p.parts}


def test_plain_text_diff_is_stored_unchanged(tmp_path, monkeypatch):
    rt, testbed = agent_runtime(tmp_path, monkeypatch, lambda r: (r / "mod.py").write_text("def f():\n    return 2\n"))
    patch = rt.finalize(SimpleNamespace())
    assert json.loads((rt.workspace / "finalize.json").read_text())["mode"] == "text"
    assert patch.read_bytes().startswith(b"diff --git a/mod.py") and not (rt.workspace / "model.patch.raw").exists()
    assert tree_hashes(applied_tree(tmp_path, patch)) == tree_hashes(testbed)


@pytest.mark.parametrize("name,edit", [
    ("latin-1 new file", lambda r: (r / "notes.txt").write_bytes(b"caf\xe9 \x8f\n")),
    ("non-utf8 byte in tracked file", lambda r: (r / "mod.py").write_bytes(b"def f():\n    return '\xff'\n")),
    ("carriage returns", lambda r: (r / "crlf.txt").write_bytes(b"one\r\ntwo\r\nthree\r\n")),
])
def test_patch_reconstructs_agent_files_byte_for_byte(tmp_path, monkeypatch, name, edit):
    def edits(r):
        edit(r)
        (r / "mod.py").write_bytes((r / "mod.py").read_bytes() + b"# touched\n")
    rt, testbed = agent_runtime(tmp_path, monkeypatch, edits)
    patch = rt.finalize(SimpleNamespace())
    meta = json.loads((rt.workspace / "finalize.json").read_text())
    assert meta["mode"] == "binary" and (rt.workspace / "model.patch.raw").exists()
    patch.read_bytes().decode("ascii")                    # what the harness writes with write_text, exactly
    assert tree_hashes(applied_tree(tmp_path, patch)) == tree_hashes(testbed), name
    assert rt.container is None


def test_unrepresentable_submission_is_not_resolved_and_not_infrastructure(tmp_path, monkeypatch):
    rt, _ = agent_runtime(tmp_path, monkeypatch, lambda r: None)
    rt._exec_raw = lambda script: (0, b"diff --git a/x b/x\n+\xff\n", "")
    rt.finalize(SimpleNamespace())
    assert rt.patch_mode == "unsupported" and rt.patch_path.read_bytes() == b""
    res = rt.verify(SimpleNamespace(), None)
    assert res["passed"] is False and res["unsupported_submission"] is True and "infrastructure" not in res


def test_bash_tool_output_with_invalid_bytes_completes(tmp_path, monkeypatch):
    rt, testbed = agent_runtime(tmp_path, monkeypatch, lambda r: (r / "bad.bin").write_bytes(b"out \x8f end\n"))
    out = sw.BashTool(rt.docker, rt.container, "cat bad.bin").execute()
    assert out["exit_code"] == 0 and out["output"] == "out � end\n"
