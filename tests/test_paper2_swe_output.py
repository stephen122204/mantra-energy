"""SWE-bench runner output that is not valid UTF-8 (agent-written files in another encoding)."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from studies.paper2.cohort import swebench_workload as sw

FAKE_DOCKER = r'''#!/bin/sh
case "$*" in
  *"git diff --cached"*) printf 'diff --git a/x.py b/x.py\n+caf\351\r\n' ;;
  *"exec"*) printf 'out \217 end\n' ;;
esac
'''

EMIT = "import sys; sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))"


def emit(hexdata):
    return [sys.executable, "-c", EMIT, hexdata]


@pytest.mark.parametrize("data", ["hello\n", "a\r\nb\rc\n", "café ✓\n", ""])
def test_valid_utf8_output_is_unchanged_from_text_mode(data):
    argv = emit(data.encode().hex())
    want = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8").stdout
    assert sw.run_cmd(argv, 30)[1] == want


def test_invalid_utf8_output_is_replaced_not_raised_and_raw_is_exact():
    raw = b"x\x8fy\r\n"
    rc, out, _ = sw.run_cmd(emit(raw.hex()), 30)
    assert rc == 0 and out == "x�y\n"
    assert sw.run_cmd(emit(raw.hex()), 30, raw=True)[1] == raw


def _runtime(tmp_path):
    docker = tmp_path / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    rt = sw.SweBenchRuntime(tmp_path / "sess", docker=str(docker))
    rt.workspace = tmp_path / "ws"
    rt.workspace.mkdir()
    rt.container = "p2-test"
    return rt


def test_finalize_keeps_a_non_utf8_diff_instead_of_crashing(tmp_path):
    rt = _runtime(tmp_path)
    patch = rt.finalize(SimpleNamespace())
    assert patch.read_text() == "diff --git a/x.py b/x.py\n+caf�\n"
    assert (rt.workspace / "model.patch.raw").read_bytes() == b"diff --git a/x.py b/x.py\n+caf\xe9\r\n"
    meta = json.loads((rt.workspace / "finalize.json").read_text())
    assert meta["utf8_valid"] is False and meta["raw_bytes"] == 32 and rt.container is None


def test_bash_tool_output_with_invalid_bytes_completes(tmp_path):
    rt = _runtime(tmp_path)
    out = sw.BashTool(rt.docker, rt.container, "cat f").execute()
    assert out["exit_code"] == 0 and out["output"] == "out � end\n"
