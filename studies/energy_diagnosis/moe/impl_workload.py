"""Bounded Python implementation tasks with hidden tests and a performance budget (kind 'impl').

Problems are adapted from EvalPerf (performance-exercising input, reference solutions of different cost) and
EvalPlus MBPP+ (base and plus test inputs, canonical solution). This is an adaptation to the ALEMS agent tool
interface, not an EvalPerf or EvalPlus benchmark result.

Assets: ``public/`` (problem statement with its example assert, a stub ``solution.py``, the example check and
the performance input) is the only part copied into the model's workspace. ``private/`` (hidden inputs, expected
outputs computed with the canonical solution, comparison mode and the performance budget) stays in the asset
directory and is used only by the verifier, which runs the candidate in a separate scratch directory and
compares outputs in the verifier process.

Tool ``python``: read (statement and current solution), write(content) (replace solution.py), test (run the
example check, then run the function on the performance input under the wall-clock budget and report only
whether it finished and how long it took; its output is never returned). Budget overruns are reported with an
explicit message.

Verification: every hidden input must produce the expected output (hidden run bounded at HIDDEN_SECONDS), and the
performance input must finish within the budget with the expected output. Failure labels: budget (performance
input exceeded the budget), mismatch (a wrong output), error (exception, crash or hidden-run timeout).
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash, copy_workspace, workspace_write
from . import sandbox
from .tool_contracts import action_contract, validate_action

VERSION = "impl-evalperf-mbppplus-v1"
IMPL_ACTIONS = {"read": None, "write": "content", "test": None}
HIDDEN_SECONDS = 60.0
EXAMPLE_SECONDS = 10.0
MEMORY_BYTES = 8 << 30
# Submitted code never runs without the kernel boundary on Linux; tests elsewhere must opt out explicitly.
REQUIRE_LANDLOCK = sys.platform.startswith("linux")

class BudgetExceeded(Exception):
    pass


def _run(source, entry, inputs, seconds, example=None):
    """Execute submitted code in the Landlock sandbox (sandbox.py). Returns (status, payload).

    The budget and every reported time are the whole-process wall time measured here, by the parent (interpreter
    start, input load and execution). Any timing computed inside the child is under the submitted code's control
    and is discarded."""
    t0 = time.monotonic()
    status, payload = sandbox.run(source, entry, inputs, seconds, example=example, memory_bytes=MEMORY_BYTES,
                                  require_landlock=REQUIRE_LANDLOCK)
    wall = time.monotonic() - t0
    if isinstance(payload, dict):
        payload.pop("seconds", None)
        payload["wall_seconds"] = wall
    return status, (payload if payload is not None else dict(wall_seconds=wall))


def _norm(value, mode):
    """Canonical form for comparison: 'exact', or 'set' (order-insensitive over the top-level container)."""
    if mode == "set":
        items = value.get("__set__") if isinstance(value, dict) and "__set__" in value else value
        if not isinstance(items, list):
            return ("scalar", json.dumps(value, sort_keys=True))
        return ("set", sorted(json.dumps(v, sort_keys=True) for v in items))
    return json.dumps(value, sort_keys=True)


def _close(a, b, atol):
    """Structural equality with EvalPlus-style float tolerance (abs <= atol, or rel <= 1e-9)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        # An infinite difference must never pass because its relative tolerance
        # is also infinite. Exact signed infinities can only match themselves.
        if not math.isfinite(a) or not math.isfinite(b):
            return a == b
        return a == b or abs(a - b) <= max(atol, 1e-9 * max(abs(a), abs(b)))
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y, atol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], atol) for k in a)
    return a == b


def equal(got, want, mode, atol=0.0):
    if mode not in {"exact", "set"} or not math.isfinite(atol) or atol < 0:
        raise ValueError("invalid comparison mode or tolerance")
    if atol and mode == "exact":
        return _close(got, want, atol)
    return _norm(got, mode) == _norm(want, mode)


# Model-visible submission wording. v1 is the wording used by the step-3 screen; it conflicts with the
# system prompt (answer object) and models wrote the answer as text. v2 uses the repo workload's v3 wording.
PROMPTS = {
    "v1": "Grading runs your final solution.py; when finished, submit {done:true}.",
    "v2": 'Grading runs your final solution.py. When it is complete, call the submit_answer tool with answer '
          '{"done": true}; do not write the answer as text.',
    "v3": 'Grading runs your final solution.py. When it is complete, finish with exactly this tool call: '
          '<tool_call>{"name":"submit_answer","arguments":{"answer":{"done":true}}}</tool_call>. '
          'The plain text {"answer":{"done":true}} does not call a tool and does not finish the task. '
          'Submission triggers independent grading of solution.py; it does not assert that your code passed.',
}


def create_task(root, *, problem, bundle, prompt="v2"):
    """Materialize one problem from a prepared bundle (build with impl_prepare.py)."""
    if prompt not in PROMPTS:
        raise ValueError("unknown impl prompt version")
    wording = prompt
    bundle = Path(bundle).resolve(strict=True)
    data = json.loads(bundle.read_text())
    if data.get("version") != VERSION or problem not in data["problems"]:
        raise ValueError("unknown impl problem or bundle version")
    spec = data["problems"][problem]
    budget = spec.get("budget_seconds")
    tolerance = spec.get("atol", 0.0)
    if (type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0
            or type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0):
        raise ValueError("budget must be finite and positive; tolerance finite and nonnegative")
    if (not spec.get("hidden_inputs") or len(spec["hidden_inputs"]) != len(spec.get("hidden_expected", []))
            or spec.get("compare") not in {"exact", "set"}):
        raise ValueError("nonempty aligned hidden checks and a supported comparison are required")
    root = Path(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as temp:
        stage = Path(temp) / "assets"
        (stage / "public").mkdir(parents=True)
        (stage / "private").mkdir()
        (stage / "public" / "problem.md").write_text(spec["statement"], encoding="utf-8")
        (stage / "public" / "solution.py").write_text(spec["stub"], encoding="utf-8")
        (stage / "public" / "example_check.py").write_text(
            "# example check (runs in the sandbox with solution.py)\n" + spec["example_assert"] + "\n", encoding="utf-8")
        (stage / "public" / "performance_input.json").write_text(json.dumps(spec["performance_input"]))
        (stage / "private" / "hidden_inputs.json").write_text(json.dumps(spec["hidden_inputs"]))
        (stage / "private" / "expected.json").write_text(json.dumps(dict(
            hidden=spec["hidden_expected"], performance=spec["performance_expected"])))
        (stage / "private" / "meta.json").write_text(json.dumps(dict(
            version=VERSION, problem=problem, entry=spec["entry"], compare=spec["compare"], atol=spec.get("atol", 0.0),
            budget_seconds=spec["budget_seconds"], provenance=spec["provenance"]), indent=1, sort_keys=True))
        fingerprint = _hash(stage)
        if root.exists():
            if _hash(root) != fingerprint:
                raise ValueError("existing impl assets differ")
        else:
            stage.rename(root)
    slug = problem.lower().replace("/", "-")
    budget = spec["budget_seconds"]
    prompt = (spec["statement_text"] + "\n\nImplement the function in solution.py with the python tool: read the problem and the "
              "current solution, write the complete solution.py, and test it. The test runs the example check and then "
              f"runs your function on a larger performance input with a {budget:g}-second budget. "
              "Your solution must be correct on additional hidden inputs and must finish the performance input within the "
              "budget. " + PROMPTS[wording])
    return PilotTask(f"impl-{slug}-{wording}", "python-implementation", "evalperf-mbppplus-adapted-v1", root, {}, fingerprint, (), prompt)


class ImplTool:
    def __init__(self, workspace, entry, budget):
        self.workspace, self.entry, self.budget = Path(workspace), entry, budget

    def execute(self, action, content=None, workers=1):
        if workers != 1 or action not in IMPL_ACTIONS:
            raise ValueError("invalid python action")
        sol = self.workspace / "solution.py"
        if action == "read":
            if content is not None:
                raise ValueError("read takes no content")
            return dict(problem=(self.workspace / "problem.md").read_text(encoding="utf-8"), solution=sol.read_text(encoding="utf-8"))
        if action == "write":
            if not isinstance(content, str) or not content.strip() or len(content.encode()) > 32768:
                raise ValueError("provide the complete solution.py up to 32768 bytes")
            workspace_write(sol, content, encoding="utf-8")
            return {"written": True}
        if content is not None:
            raise ValueError("test takes no content")
        source = sol.read_text(encoding="utf-8")
        ex_code = (self.workspace / "example_check.py").read_text(encoding="utf-8").split("\n", 1)[1]
        status, payload = _run(source, self.entry, None, EXAMPLE_SECONDS, example=ex_code)
        if status == "ok":
            example = dict(passed=True)
        elif status == "timeout":
            example = dict(passed=False, output=f"example check did not finish within {EXAMPLE_SECONDS:g} seconds")
        else:
            example = dict(passed=False, output=(payload or {}).get("error", status))
        perf_input = json.loads((self.workspace / "performance_input.json").read_text())
        status, payload = _run(source, self.entry, [perf_input], self.budget)
        if status == "timeout":
            performance = dict(completed=False, message=f"the function did not finish on the performance input within the "
                                                        f"{self.budget:g}-second budget and was stopped")
        elif status != "ok":
            performance = dict(completed=False, message="the function raised an error on the performance input",
                               error=str((payload or {}).get("error", status))[-1500:])
        else:
            performance = dict(completed=True, wall_seconds=round(payload["wall_seconds"], 3),
                               measured="whole-process wall time (interpreter start, input load, execution)")
        return dict(example=example, performance=performance)


class ImplRuntime:
    def __init__(self, root):
        self.root = Path(root)

    def begin(self, task, lease):
        if _hash(task.asset_path) != task.asset_sha256:
            raise ValueError("impl inputs changed")
        self.workspace = self.root / "workspaces" / lease.execution_id
        # Only public material enters the model-visible workspace.
        copy_workspace(task.asset_path / "public", self.workspace)
        self.meta = json.loads((task.asset_path / "private" / "meta.json").read_text())

    def context(self, task):
        meta = json.loads((task.asset_path / "private" / "meta.json").read_text())
        return dict(family=task.family, tools={"python": {
            "description": 'The action argument is mandatory on every call. action="read" returns the problem statement and '
            'the current solution.py. action="write" requires content containing the complete replacement solution.py and '
            'returns written=true. action="test" runs the example check and then runs the function on a larger performance '
            f'input with a {meta["budget_seconds"]:g}-second budget (whole-process wall time), reporting whether it finished '
            'and how long it took (its output is not shown). Use the Python standard library only.',
            "args": {"action": "required: read, write or test", "content": "required only for write; complete solution.py"},
            "parameters": action_contract(IMPL_ACTIONS),
            "example_call": {"id": "read_1", "tool": "python", "args": {"action": "read"}}}},
            instruction='Return only JSON {"tool_calls":[{"id":"unique","tool":"python","args":{"action":"read"}}]} or {"answer":{"done":true}}. '
            "Read first, then write the solution, then test it. Include action every time; do not supply content to read/test.")

    def tool(self, task, call):
        if call.get("tool") != "python":
            raise ValueError("invalid python tool request")
        validate_action(call.get("args"), IMPL_ACTIONS)
        return ImplTool(self.workspace, self.meta["entry"], self.meta["budget_seconds"])

    def verify(self, task, answer):
        # Any submission ends the goal; grading always runs the program in solution.py. Whether the submission used
        # the stated {"done": true} format is recorded, never used as the verdict.
        self._completion = dict(format_ok=isinstance(answer, dict) and set(answer) == {"done"} and answer.get("done") is True,
                                submitted_type=type(answer).__name__)
        if _hash(task.asset_path) != task.asset_sha256:
            raise ValueError("impl inputs changed")
        private = task.asset_path / "private"
        meta = json.loads((private / "meta.json").read_text())
        expected = json.loads((private / "expected.json").read_text())
        hidden = json.loads((private / "hidden_inputs.json").read_text())
        source = (self.workspace / "solution.py").read_text(encoding="utf-8")
        status, payload = _run(source, meta["entry"], hidden, HIDDEN_SECONDS)
        if status == "refused":
            raise RuntimeError("sandbox unavailable")      # infrastructure, never a model failure
        if status == "timeout":
            return dict(passed=False, reason=f"hidden tests did not finish within {HIDDEN_SECONDS:g} seconds",
                        failure="hidden_timeout", completion=self._completion)
        if status != "ok":
            return dict(passed=False, reason=f"hidden tests: {status}", failure="runtime_error", completion=self._completion)
        wrong = [i for i, (got, want) in enumerate(zip(payload["outputs"], expected["hidden"]))
                 if not equal(got, want, meta["compare"], meta.get("atol", 0.0))]
        if wrong or len(payload["outputs"]) != len(expected["hidden"]):
            return dict(passed=False, reason=f"hidden tests: {len(wrong)} of {len(hidden)} outputs differ", failure="mismatch", completion=self._completion)
        perf_input = json.loads((task.asset_path / "public" / "performance_input.json").read_text())
        status, payload = _run(source, meta["entry"], [perf_input], meta["budget_seconds"])
        if status == "refused":
            raise RuntimeError("sandbox unavailable")
        if status == "timeout":
            return dict(passed=False, reason=f"performance input did not finish within the {meta['budget_seconds']:g}-second budget",
                        failure="budget", completion=self._completion)
        if status != "ok":
            return dict(passed=False, reason="performance input: error", failure="runtime_error", completion=self._completion)
        if not equal(payload["outputs"][0], expected["performance"], meta["compare"], meta.get("atol", 0.0)):
            return dict(passed=False, reason="performance input output differs", failure="mismatch", completion=self._completion)
        return dict(passed=True, reason=f"hidden tests passed ({len(hidden)} inputs); performance input finished in "
                                        f"{payload['wall_seconds']:.3f} s (whole-process wall) within the budget",
                    performance_wall_seconds=payload["wall_seconds"], completion=self._completion)
