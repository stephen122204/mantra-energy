"""One agent session = one task attempt, run as its own process against the shared server.

    python -m studies.paper2.cohort.session --spec SESSION_DIR/spec.json            # execute
    python -m studies.paper2.cohort.session --spec SESSION_DIR/spec.json --verify   # grade later

Execution reuses the C2 agent loop (``GoalExecutor._chat``: protocol, tool parsing, budgets,
bounded tool processes) and the task-pack runtimes unchanged; only the model adapter differs.
Agent-requested tools/tests run inside execution. The trusted verifier does NOT run here: the
session pickles its runtime and answer, and ``--verify`` grades them afterwards in the same
isolated verification process the harness uses, outside the cohort's energy interval.
Outputs (all under SESSION_DIR): requests.jsonl, model-calls.json, tool-results.json,
tool-events.json, agent-trace.json, outcome.json, runtime.pkl, verification.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

OUTCOMES = {"completed": "completed", "incomplete": "agent_failed", "timed_out": "timed_out", "crashed": "infra_failed"}


def _dump(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, default=str, indent=1))
    tmp.replace(path)


def _load_task(spec):
    import cloudpickle
    from studies.energy_diagnosis.moe import task_pack
    task = cloudpickle.loads(Path(spec["task_pickle"]).read_bytes())
    modules = {} if spec["task_kind"] == "swebench" else {task.task_id: task_pack.MODULES[spec["task_kind"]]}
    return task, modules


def execute(spec_path: Path) -> int:
    spec = json.loads(spec_path.read_text())
    root = spec_path.parent
    if spec.get("tool_cpus"):
        os.environ["ALEMS_TOOL_CPUS"] = spec["tool_cpus"]
    from studies.energy_diagnosis.local_run import GoalExecutor
    from studies.energy_diagnosis.moe.task_pack import PackRuntime
    from studies.paper2.cohort.client import MistralRenderer, SharedServerAdapter
    import cloudpickle

    task, modules = _load_task(spec)
    req_log = open(root / "requests.jsonl", "a")

    def record(rec):
        req_log.write(json.dumps(rec) + "\n")
        req_log.flush()

    srv, lim = spec["server"], spec["limits"]
    adapter = SharedServerAdapter(srv["base_url"], srv["served_model"], MistralRenderer(spec["tekken"]),
                                  max_tokens=lim["max_tokens"], max_model_len=srv["max_model_len"],
                                  record=record, session_id=spec["session_id"])
    if spec["task_kind"] == "swebench":
        from studies.paper2.cohort.swebench_workload import SweBenchRuntime
        runtime = SweBenchRuntime(root, **spec.get("swebench", {}))
    else:
        runtime = PackRuntime(modules, root)
    executor = GoalExecutor({task.task_id: task}, adapter, None, root, max_steps=lim["max_turns"],
                            timeout_seconds=lim["deadline_s"], simulated=False, workload_runtime=runtime,
                            protocol=spec.get("protocol", "chat-tools-v2"), sampling=spec["sampling"],
                            max_tool_calls=lim["max_tool_calls"], max_output_tokens=lim["max_total_output_tokens"],
                            tool_call_format=spec.get("tool_call_format", "mistral"))
    lease = SimpleNamespace(execution_id=spec["session_id"], attempt_id=spec["attempt_id"],
                            started_ns=time.monotonic_ns(), clock_domain=spec.get("clock_domain", "host-monotonic"))
    plan = SimpleNamespace(setting_id="cohort", planned_run_id=f"{spec['pair_key']}-cohort",
                           model_sha256=spec["config_id"], tool_concurrency=False, tool_workers=1,
                           verifier_version=spec.get("verifier_version", "task-pack"))
    model_calls, tool_results, spans, events, artifacts = [], [], [], [], []
    trace = dict(protocol=executor.protocol, terminal=None, turns=[])
    started_wall = time.time()
    status, error, answer = "crashed", "session did not start", None
    try:
        runtime.begin(task, lease)
        context = dict(task_id=task.task_id, asset_sha256=task.asset_sha256, goal=task.prompt,
                       tool_results=tool_results, **runtime.context(task))
        status, error, answer, _response, _owned = executor._chat(task, lease, plan, context, model_calls,
                                                                  tool_results, spans, events, trace, artifacts, None)
    except Exception as exc:  # infrastructure failure inside the session: preserved, never retried here
        status, error = "crashed", f"{type(exc).__name__}: {exc}"
        trace["exception"] = traceback.format_exc()
    finalize = getattr(runtime.active, "finalize", None) if runtime.active is not None else None
    if finalize:  # e.g. SWE-bench: store the working-tree diff and remove the container (part of the attempt)
        try:
            finalize(task)
        except Exception as exc:
            trace["finalize_error"] = f"{type(exc).__name__}: {exc}"
            status, error = "crashed", trace["finalize_error"]
    ended_wall = time.time()
    req_log.close()
    _dump(root / "model-calls.json", model_calls)
    _dump(root / "tool-results.json", tool_results)
    _dump(root / "tool-events.json", events)
    _dump(root / "agent-trace.json", dict(trace=trace, spans=[getattr(s, "to_dict", lambda: str(s))() for s in spans]))
    if runtime.active is not None:
        (root / "runtime.pkl").write_bytes(cloudpickle.dumps(runtime.active))
    _dump(root / "outcome.json", dict(session_id=spec["session_id"], attempt_id=spec["attempt_id"], task_id=task.task_id,
                                      execution_status=status, outcome=OUTCOMES.get(status, "infra_failed"),
                                      terminal=trace.get("terminal"), error=error, answer=answer,
                                      turns=len(trace["turns"]), started_wall=started_wall, ended_wall=ended_wall))
    return 0


def verify(spec_path: Path) -> int:
    """Trusted grading in the harness's isolated verification process; never inside the energy interval."""
    spec = json.loads(spec_path.read_text())
    root = spec_path.parent
    outcome = json.loads((root / "outcome.json").read_text())
    result = dict(session_id=spec["session_id"], task_id=outcome["task_id"], t_start=time.time())
    if outcome["outcome"] != "completed":
        result.update(verdict="not_run", reason=f"agent outcome {outcome['outcome']}")
    else:
        import cloudpickle
        from studies.energy_diagnosis.local_run import _VerificationTool
        from studies.energy_diagnosis.workloads.bounded_executor import BoundedToolExecutor, ToolCall
        task, _ = _load_task(spec)
        runtime = cloudpickle.loads((root / "runtime.pkl").read_bytes())
        ex = BoundedToolExecutor({"verify": _VerificationTool(runtime.verify, task, outcome["answer"])},
                                 timeout_seconds=float(spec["limits"].get("verify_timeout_s", 900)))
        checked = ex.execute([ToolCall("verify", "verify", {})])["verify"]
        if checked.status == "completed":
            res = checked.result
            result.update(verdict="unavailable" if res.get("infrastructure") else ("pass" if res["passed"] else "fail"),
                          reason=res.get("reason", ""),
                          detail=json.loads(json.dumps(res, default=str)))
        else:
            result.update(verdict="unavailable", reason=checked.error or checked.status)
    result["t_end"] = time.time()
    _dump(root / "verification.json", result)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    return verify(a.spec) if a.verify else execute(a.spec)


if __name__ == "__main__":
    sys.exit(main())
