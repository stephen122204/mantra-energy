"""Workspaces copied from a read-only frozen preparation must stay editable by the agent."""
import os
import shutil
import stat
from types import SimpleNamespace

import pytest

from studies.energy_diagnosis.moe import program_workload as pw
from studies.energy_diagnosis.moe.etl_workload import ETLRuntime, ETLTool, create_task as create_etl
from studies.energy_diagnosis.moe.task_pack_fixture import PROGRAMS
from studies.energy_diagnosis.workloads.pilot_tasks import _hash, copy_workspace

CORRECT_ETL = ("SELECT r.region, COUNT(*) AS event_count, SUM(r.gross_cents-r.tax_cents) AS net_cents FROM raw r "
               "JOIN (SELECT event_id,MAX(seq) AS latest FROM raw GROUP BY event_id) v ON r.event_id=v.event_id "
               "AND r.seq=v.latest WHERE r.status='paid' GROUP BY r.region ORDER BY r.region")


def freeze(root):
    """Same effect as chmod -R a-w on a frozen preparation."""
    for item in sorted(root.rglob("*"), reverse=True) + [root]:
        item.chmod(item.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def thaw(root):
    for item in [root, *root.rglob("*")]:
        item.chmod(item.stat().st_mode | stat.S_IWUSR)


@pytest.fixture
def frozen(tmp_path):
    made = []
    yield made
    for root in made:
        thaw(root)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores write permission")
def test_copy_is_writable_and_source_stays_read_only(tmp_path, frozen):
    source = tmp_path / "frozen"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "mod.py").write_text("x = 1\n")
    (source / "private").mkdir()
    (source / "private" / "answer.json").write_text("{}")
    freeze(source); frozen.append(source)
    before = _hash(source)
    workspace = tmp_path / "ws"
    copy_workspace(source, workspace, ignore=shutil.ignore_patterns("private"))
    (workspace / "pkg" / "mod.py").write_text("x = 2\n")
    (workspace / "pkg" / "new.py").write_text("")
    assert not (workspace / "private").exists()
    assert _hash(source) == before
    assert not os.access(source / "pkg" / "mod.py", os.W_OK)
    assert not os.access(source / "pkg", os.W_OK)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores write permission")
@pytest.mark.parametrize("case", pw.CASES)
def test_program_task_from_frozen_assets_can_be_solved(tmp_path, frozen, case):
    task = pw.create_task(tmp_path / "assets", case=case, rows=32, seed=7)
    freeze(task.asset_path); frozen.append(task.asset_path)
    runtime = pw.ProgramRuntime(tmp_path / "run")
    runtime.begin(task, SimpleNamespace(execution_id="one"))
    tool = pw.ProgramTool(runtime.workspace)
    assert tool.execute("write", content=PROGRAMS[case]) == {"written": True}
    assert tool.execute("test")["passed"]
    assert runtime.verify(task, {"done": True})["passed"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores write permission")
def test_etl_task_from_frozen_assets_can_be_solved(tmp_path, frozen):
    task = create_etl(tmp_path / "assets", rows=128, seed=7)
    freeze(task.asset_path); frozen.append(task.asset_path)
    runtime = ETLRuntime(tmp_path / "runs")
    runtime.begin(task, SimpleNamespace(execution_id="one"))
    ETLTool(runtime.workspace).execute("write", CORRECT_ETL)
    assert runtime.verify(task, {"done": True})["passed"]
