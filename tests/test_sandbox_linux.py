"""Escape attempts against the Landlock sandbox (Linux with Landlock only)."""
import json
import sys

import pytest

from studies.energy_diagnosis.moe import sandbox

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Landlock is Linux-only")


def attempt(body, tmp_path):
    secret = tmp_path / "expected.json"
    secret.write_text(json.dumps({"answer": 42}))
    src = "def f():\n" + "".join("    " + l + "\n" for l in body.format(secret=secret, dir=tmp_path).splitlines())
    return sandbox.run(src, "f", [[]], 20)


def test_landlock_active(tmp_path):
    status, payload = attempt("return 1", tmp_path)
    assert status == "ok" and payload["landlock_abi"] >= 1 and payload["outputs"] == [1]


@pytest.mark.parametrize("body", [
    "return open('{secret}').read()",                                   # direct read of an answer file
    "import os\nreturn os.listdir('{dir}')",                           # directory listing
    "return open('{dir}/../' + '{secret}'.split('/')[-2] + '/expected.json').read()",  # traversal
    "import os\nreturn open('/proc/%d/environ' % os.getppid()).read()",  # process inspection
    "return open('/proc/self/status').read()",
    "import os\nos.symlink('{secret}', '/tmp/x_link')\nreturn 1",      # symlink creation
    "open('/tmp/x_written', 'w').write('x')\nreturn 1",                # any write
    "import subprocess\nreturn subprocess.run(['cat', '{secret}'], capture_output=True).stdout",  # subprocess
    "import os\nos.fork()\nreturn 1",                                   # fork
    "import socket\ns = socket.socket()\ns.connect(('127.0.0.1', 22))\nreturn 1",  # network
    "import numpy\nreturn 1",                                           # non-stdlib import
])
def test_escape_attempts_fail(tmp_path, body):
    status, payload = attempt(body, tmp_path)
    assert status == "error", (status, payload)
    assert "42" not in json.dumps(payload)


def test_stdlib_imports_work(tmp_path):
    status, payload = attempt("import collections, heapq, itertools, functools, bisect, math\nreturn 7", tmp_path)
    assert status == "ok" and payload["outputs"] == [7]


def test_timeout_is_enforced(tmp_path):
    status, _ = sandbox.run("def f():\n    while True:\n        pass\n", "f", [[]], 2)
    assert status == "timeout"
