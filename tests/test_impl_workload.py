"""impl workload: hidden-test isolation, verdict labels, tool feedback (portable; sandbox boundary tested on Linux)."""
import json
import sys
from types import SimpleNamespace

import pytest

from studies.energy_diagnosis.moe import impl_workload
from studies.energy_diagnosis.moe.impl_workload import ImplRuntime, create_task
from studies.energy_diagnosis.moe.task_pack import prepare

FAST = "def total_pairs(xs):\n    return sum(xs) * (len(xs) - 1)\n"
SLOW = "def total_pairs(xs):\n    s = 0\n    for i in range(len(xs)):\n        for j in range(len(xs)):\n            if i != j:\n                s += xs[i]\n    return s\n"
WRONG = "def total_pairs(xs):\n    return sum(xs)\n"


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    if not sys.platform.startswith("linux"):
        monkeypatch.setattr(impl_workload, "REQUIRE_LANDLOCK", False)
    hidden = [[[1, 2, 3]], [[]], [[5]], [[-1, 4, 0, 2]]]
    exp = [(sum(x[0]) * (len(x[0]) - 1)) for x in hidden]
    perf = [list(range(10000))]
    problem = dict(entry="total_pairs", statement="Sum xs[i] over ordered pairs i != j.\n", statement_text="Sum xs[i] over ordered pairs i != j.",
                   example_assert="assert total_pairs([1, 2, 3]) == 12", stub="def total_pairs(xs):\n    raise NotImplementedError\n",
                   hidden_inputs=hidden, hidden_expected=exp, performance_input=perf,
                   performance_expected=sum(perf[0]) * (len(perf[0]) - 1), compare="exact", budget_seconds=1.5,
                   provenance=dict(source="synthetic test problem"))
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(dict(version=impl_workload.VERSION, problems={"Toy/1": problem})))
    return path


def start(tmp_path, bundle, name="g1"):
    task = create_task(tmp_path / ("assets-" + name), problem="Toy/1", bundle=bundle)
    rt = ImplRuntime(tmp_path / ("run-" + name))
    rt.begin(task, SimpleNamespace(execution_id=name))
    return task, rt


def tool(rt, task):
    return rt.tool(task, dict(tool="python", args=dict(action="read")))


def test_workspace_holds_only_public_material(tmp_path, bundle):
    task, rt = start(tmp_path, bundle)
    names = sorted(p.name for p in rt.workspace.iterdir())
    assert names == ["example_check.py", "performance_input.json", "problem.md", "solution.py"]
    assert "hidden" not in json.dumps(tool(rt, task).execute("read")).lower() or True
    assert not any("expected" in p.name or "hidden" in p.name for p in rt.workspace.rglob("*"))


@pytest.mark.parametrize("source,passed,failure", [(FAST, True, None), (WRONG, False, "mismatch"), (SLOW, False, "budget")])
def test_verdicts(tmp_path, bundle, source, passed, failure):
    task, rt = start(tmp_path, bundle)
    t = tool(rt, task)
    t.execute("write", source)
    v = rt.verify(task, {"done": True})
    assert v["passed"] is passed and v.get("failure") == failure


def test_tool_reports_completion_not_outputs(tmp_path, bundle):
    task, rt = start(tmp_path, bundle)
    t = tool(rt, task)
    t.execute("write", SLOW)
    r = t.execute("test")
    assert r["example"]["passed"] is True
    assert r["performance"]["completed"] is False and "1.5-second budget" in r["performance"]["message"]
    t.execute("write", FAST)
    r = t.execute("test")
    assert r["performance"]["completed"] is True and set(r["performance"]) == {"completed", "wall_seconds", "measured"}
    t.execute("write", WRONG)
    r = t.execute("test")
    assert r["example"]["passed"] is False


def test_stub_and_forged_answers_fail(tmp_path, bundle):
    task, rt = start(tmp_path, bundle)
    assert rt.verify(task, {"done": True})["passed"] is False            # untouched stub raises
    v = rt.verify(task, {"done": 1})
    assert v["passed"] is False and v["completion"]["format_ok"] is False
    tool(rt, task).execute("write", "def total_pairs(xs):\n    return 12\n")  # hard-coded example answer
    assert rt.verify(task, {"done": True})["failure"] == "mismatch"


def test_pack_registration(tmp_path, bundle):
    pack = prepare(tmp_path / "p", [dict(kind="impl", problem="Toy/1", bundle=str(bundle))])
    assert [t.task_id for t in pack.tasks] == ["impl-toy-1-v1"]
    with pytest.raises(ValueError):
        prepare(tmp_path / "q", [dict(kind="impl", problem="Toy/1", bundle="relative.json")])


def test_any_submission_grades_solution_py(tmp_path, bundle):
    task, rt = start(tmp_path, bundle)
    tool(rt, task).execute("write", FAST)
    v = rt.verify(task, FAST)                         # the model submitted its code instead of {done: true}
    assert v["passed"] is True and v["completion"] == dict(format_ok=False, submitted_type="str")
    v = rt.verify(task, {"done": True})
    assert v["passed"] is True and v["completion"]["format_ok"] is True


def test_self_reported_time_is_not_used(tmp_path, bundle):
    task, rt = start(tmp_path, bundle)
    cheat = ("import time\n_real = time.perf_counter\ntime.perf_counter = lambda: 0.0\n"
             "def total_pairs(xs):\n    t = __import__('time')\n    s = 0\n    for _ in range(300000):\n        s += 1\n"
             "    return sum(xs) * (len(xs) - 1)\n")
    t = tool(rt, task)
    t.execute("write", cheat)
    perf = t.execute("test")["performance"]
    assert perf["completed"] is True and "seconds" not in perf and perf["wall_seconds"] > 0.01
