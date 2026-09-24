"""Repository repair workload: contract, confinement, withheld tests and verification.

The integration test needs a networkx 3.4.2 checkout and a tool Python with pytest:
ALEMS_NETWORKX_SOURCE=/abs/networkx-checkout ALEMS_REPO_TOOL_PYTHON=/abs/python
"""
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from studies.energy_diagnosis.moe import repo_workload as rw


def test_contract_and_validation_are_strict():
    rw.validate({"action": "read", "path": "networkx/dag.py", "start": 1})
    rw.validate({"action": "replace", "path": "networkx/a.py", "old": "x", "new": ""})
    for bad in (
        {"action": "read", "path": "networkx/dag.py"},
        {"action": "read", "path": "networkx/dag.py", "start": 0},
        {"action": "read", "path": "networkx/dag.py", "start": "1"},
        {"action": "test"},
        {"action": "test", "target": "x", "extra": 1},
        {"action": "shell", "cmd": "ls"},
        {"action": "replace", "path": "networkx/a.py", "old": "", "new": "y"},
    ):
        with pytest.raises(ValueError):
            rw.validate(bad)
    variants = rw.contract()["oneOf"]
    assert {v["properties"]["action"]["const"] for v in variants} == set(rw.ACTIONS)
    assert all(v["additionalProperties"] is False for v in variants)


def workspace(tmp_path):
    ws = tmp_path / "ws"
    (ws / "networkx" / "algorithms" / "tests").mkdir(parents=True)
    (ws / "networkx" / "algorithms" / "dag.py").write_text("def f():\n    return 1\n")
    (ws / "networkx" / "algorithms" / "tests" / "test_dag.py").write_text("def test_f():\n    pass\n")
    (tmp_path / "secret.txt").write_text("outside")
    return ws


def test_paths_are_confined_and_tests_are_read_only(tmp_path):
    tool = rw.RepoTool(workspace(tmp_path), sys.executable, str(tmp_path))
    assert tool.execute("list", path="networkx/algorithms")["entries"] == ["dag.py", "tests/"]
    got = tool.execute("read", path="networkx/algorithms/dag.py", start=2)
    assert got["text"] == "2:     return 1" and got["total_lines"] == 2
    for path in ("../secret.txt", "/etc/passwd", "networkx/../../secret.txt", "setup.py"):
        with pytest.raises(ValueError):
            tool.execute("read", path=path, start=1)
    with pytest.raises(ValueError, match="non-test"):
        tool.execute("replace", path="networkx/algorithms/tests/test_dag.py", old="pass", new="assert 0")
    with pytest.raises(ValueError, match="exactly once"):
        tool.execute("replace", path="networkx/algorithms/dag.py", old="missing", new="x")
    assert tool.execute("replace", path="networkx/algorithms/dag.py", old="return 1", new="return 2") == \
        {"replaced": "networkx/algorithms/dag.py"}
    assert tool.execute("search", pattern="return 2")["matches"] == ["networkx/algorithms/dag.py:2: return 2"]


def test_withhold_removes_named_tests_with_decorators():
    source = "import pytest\n\nclass TestA:\n    @pytest.mark.x\n    def test_keep(self):\n        pass\n\n    @pytest.mark.y\n    def test_drop(self):\n        assert 1\n\ndef test_top():\n    pass\n"
    out = rw._withhold(source, ("TestA::test_drop", "test_top"))
    assert "test_keep" in out and "test_drop" not in out and "mark.y" not in out and "test_top" not in out
    compile(out, "x", "exec")


SOURCE = os.environ.get("ALEMS_NETWORKX_SOURCE")
PYTHON = os.environ.get("ALEMS_REPO_TOOL_PYTHON")


@pytest.mark.skipif(not (SOURCE and PYTHON), reason="needs a networkx 3.4.2 checkout and tool Python")
@pytest.mark.parametrize("case", sorted(rw.CASES))
def test_real_cases_expose_bug_and_verify_only_true_repairs(tmp_path, case):
    spec = rw.CASES[case]
    task = rw.create_task(tmp_path / "task", case=case, source=SOURCE, python=PYTHON)
    assets = task.asset_path
    sandbox = str(assets / "sandbox")
    # The visible module exposes the defect; withheld tests are absent from the workspace.
    visible = rw.run_pytest(PYTHON, assets / "visible", [spec["module"]], sandbox)
    assert visible.returncode != 0 and "failed" in visible.stdout.splitlines()[-1]
    import ast
    tree = ast.parse((assets / "visible" / spec["module"]).read_text())
    present = {f"{c.name}::{f.name}" for c in tree.body if isinstance(c, ast.ClassDef) for f in c.body
               if isinstance(f, ast.FunctionDef)} | {f.name for f in tree.body if isinstance(f, ast.FunctionDef)}
    assert not set(spec["withheld"]) & present
    ws = tmp_path / "ws"
    shutil.copytree(assets / "visible", ws)
    assert rw.verify_workspace(assets, ws, PYTHON)["passed"] is False
    # Editing tests is rejected even if library code is also right.
    tests_edit = tmp_path / "ws-tests"
    shutil.copytree(ws, tests_edit)
    (tests_edit / spec["module"]).write_text("def test_nothing():\n    pass\n")
    assert rw.verify_workspace(assets, tests_edit, PYTHON)["reason"].startswith("non-library file changed")
    # The true repair passes the original module, withheld tests and independent held-out checks.
    target = ws / spec["file"]
    target.write_text(target.read_text().replace(spec["new"], spec["old"]))
    result = rw.verify_workspace(assets, ws, PYTHON)
    assert result["passed"] is True, result
    assert result["changed_files"] == [spec["file"]]
    meta = json.loads((assets / "task.json").read_text())
    assert meta["source_commit"] == rw.SOURCE_COMMIT and meta["case"] == case


@pytest.mark.skipif(not PYTHON, reason="needs the tool Python")
def test_sandbox_blocks_network_in_test_processes(tmp_path):
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "sandbox" / "sitecustomize.py").write_text(rw.SANDBOX)
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / "test_net.py").write_text(
        "import socket, pytest\n"
        "def test_blocked():\n"
        "    with pytest.raises(OSError, match='disabled'):\n"
        "        socket.create_connection(('1.1.1.1', 80), timeout=2)\n")
    result = rw.run_pytest(PYTHON, tmp_path / "root", ["test_net.py"], str(tmp_path / "sandbox"))
    assert result.returncode == 0, result.stdout + result.stderr
