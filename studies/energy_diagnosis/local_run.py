"""Bounded local-model/tool/measurement/verifier/ledger execution.

Run with --help. Fixture mode exercises real HTTP parsing and tool computation
with explicitly simulated model/sensors. Live mode never substitutes fixtures.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlparse
import uuid

from core.execution.adapters.openai_compat import OpenAICompatAdapter
from studies.energy_diagnosis.campaign import ArtifactRef, PlannedRun, RunLedger
from studies.energy_diagnosis.campaign.runner import (
    BoundedCampaignRunner,
    CampaignSchedule,
    ScheduleBlock,
    ExecutionOutcome,
    OutcomeMetadata,
)
from studies.energy_diagnosis.contracts import (
    ExecutionRecord,
    ModelResponse,
    SpanEvent,
    VerifierResult,
)
from studies.energy_diagnosis.runtime.node_measurement import (
    FixtureCounterReader,
    NodeCounterReader,
    NodeMeasurement,
    environment_identity,
)
from studies.energy_diagnosis.workloads.bounded_executor import (
    BoundedToolExecutor,
    ToolCall,
)
from studies.energy_diagnosis.workloads.pilot_tasks import (
    load_pilot_tasks,
    verify_pilot,
    PILOT_VERIFIER_VERSION,
    _hash as asset_hash,
)
from studies.energy_diagnosis.workloads.pilot_tools import PilotAssetTool

SETTINGS = {"C00": (False, 1), "C01": (False, 4), "C10": (True, 1), "C11": (True, 4)}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def write_artifact(root, relative, value, role):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    # Attempt identities are unique; replacing an artifact would break auditability.
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return ArtifactRef(
        relative.as_posix(), role, hashlib.sha256(content.encode()).hexdigest()
    )


class FixtureAPI:
    """Deterministic HTTP responder, clearly labeled and only explicitly selected."""

    def __init__(self, case="success"):
        self.case = case

    def __enter__(self):
        case = self.case

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                raw = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                context = json.loads(raw["messages"][-1]["content"])
                if case == "model_failure":
                    self.send_response(500)
                    self.end_headers()
                    return
                history = context["tool_results"]
                if not history:
                    answer = {
                        "tool_calls": [
                            {"id": "inspect", "tool": "inspect_asset", "args": {}}
                        ]
                    }
                else:
                    result = history[-1]["result"]
                    answer = {
                        "answer": {
                            **result,
                            "task_id": context["task_id"],
                            "evidence": [context["asset_sha256"]],
                        }
                    }
                    if case == "wrong_answer":
                        if "total_revenue" in result:
                            answer["answer"]["total_revenue"] = "-999"
                        else:
                            answer["answer"]["checks"] = []
                text = json.dumps(answer)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in (
                    {"choices": [{"delta": {"content": text}}]},
                    {
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 10,
                            "total_tokens": 20,
                        },
                    },
                ):
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class DelayedFixtureTool:
    def __init__(self, tool):
        self.tool = tool

    def execute(self, workers=1):
        time.sleep(20)
        return self.tool.execute(workers=workers)


class GoalExecutor:
    def __init__(
        self,
        tasks,
        adapter,
        measurement,
        artifact_root,
        *,
        max_steps,
        timeout_seconds,
        simulated,
        lifecycle=None,
        workload_runtime=None,
        initialized_model_window=False,
    ):
        self.tasks = tasks
        self.adapter = adapter
        self.measurement = measurement
        self.artifact_root = artifact_root
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.simulated = simulated
        self.lifecycle = lifecycle
        self.workload_runtime = workload_runtime
        self.initialized_model_window = initialized_model_window
        if initialized_model_window and lifecycle is None:
            raise ValueError("initialized-model measurement requires an owned lifecycle")

    def _termination_invalidity(self, owned_terminated):
        """Why captured energy cannot be a complete goal interval, or None.

        Unverified termination blocks finalization altogether. A worker that was
        killed and reaped while its device work was never confirmed idle has
        terminated (the attempt can be finalized and the batch continues), but
        its interval is still not a complete, idle-bracketed goal.
        """
        if not owned_terminated:
            return "live model termination unverified"
        if (
            self.lifecycle is not None
            and not self.simulated
            and getattr(self.lifecycle.backend, "termination_forced", False)
        ):
            return "owned worker terminated before device work was confirmed idle"
        return None

    def __call__(self, request):
        plan = request.scheduled_run.planned_run
        task = self.tasks[plan.task_id]
        if asset_hash(task.asset_path) != task.asset_sha256:
            raise ValueError("immutable task asset changed before execution")
        lease = request.lease
        model_calls = []
        tool_results = []
        spans = []
        events = []
        artifacts = []
        response = None
        answer = None
        status = "incomplete"
        error = "step budget exhausted"
        owned_terminated = True
        inner_started = inner_settled = False
        inner_window = dict(
            protocol="initialized-model-fresh-process-v1",
            status="unavailable", reason="initialized boundary not captured",
            measurements=[], clock_domain=lease.clock_domain,
            goal_execution_id=lease.execution_id,
            scope="model initialized before task; fresh process caches; outer deadline and startup/release costs retained",
        )
        prefix = Path("goals") / lease.execution_id
        context = dict(
            task_id=task.task_id,
            asset_sha256=task.asset_sha256,
            goal=task.prompt,
            instruction='Return only JSON. To inspect the local input use {"tool_calls":[{"id":"unique_id","tool":"inspect_asset","args":{}}]}. After inspecting results return {"answer":{...}}. Never invent observations. For data answers use total_units and total_revenue; for repository answers use file_count and checks. Include task_id and evidence [asset_sha256].',
            tool_results=tool_results,
        )
        try:
            if self.lifecycle:
                self.lifecycle.begin_goal(lease.attempt_id)
            if self.initialized_model_window:
                self.measurement.checkpoint("initialized_model_start")
                inner_started = True
            if self.workload_runtime:
                self.workload_runtime.begin(task, lease)
                context.update(self.workload_runtime.context(task))
            for step in range(self.max_steps):
                if (
                    time.monotonic_ns() - lease.started_ns
                ) / 1e9 >= self.timeout_seconds:
                    status, error = "timed_out", "goal deadline exhausted between calls"
                    break
                prompt = json.dumps(context, sort_keys=True)
                started = time.monotonic_ns()
                self.adapter.model_config["request_timeout_seconds"] = max(
                    0.001, self.timeout_seconds - (started - lease.started_ns) / 1e9
                )
                if self.lifecycle:
                    self.lifecycle.before_model(f"{lease.attempt_id}:model:{step}")
                raw = self.adapter.call(prompt, 0.0)
                ended = time.monotonic_ns()
                tokens = raw.get("tokens") or {}
                ok = raw.get("status", "ok") == "ok"
                response = ModelResponse(
                    f"{lease.attempt_id}:model:{step}",
                    "completed" if ok else "error",
                    plan.model_sha256,
                    started,
                    ended,
                    lease.clock_domain,
                    text=raw.get("content") if ok else raw.get("partial_content"),
                    prompt_tokens=tokens.get("prompt"),
                    completion_tokens=tokens.get("completion"),
                    token_provenance=raw.get("token_provenance", "unknown"),
                    error="" if ok else raw.get("error", "model failed"),
                )
                model_calls.append(
                    dict(response=response.to_dict(), adapter=raw, prompt=prompt)
                )
                spans.append(
                    SpanEvent(
                        response.request_id,
                        lease.attempt_id,
                        "model",
                        started,
                        started,
                        ended,
                        "completed" if ok else "failed",
                        input_sha256=digest(prompt),
                        output_sha256=digest(raw),
                        error=response.error,
                    )
                )
                if self.lifecycle and ok:
                    self.lifecycle.after_model()
                if not ok:
                    status, error = "crashed", response.error
                    # A disconnected live inference server may still own work.
                    # Checkpoint and stop the campaign until its termination is verified.
                    owned_terminated = (
                        self.simulated or raw.get("owned_work_terminated") is True
                    )
                    break
                try:
                    decision = json.loads(response.text)
                except (json.JSONDecodeError, TypeError) as exc:
                    status, error = "completed", f"invalid answer JSON: {exc}"
                    break
                if not isinstance(decision, dict):
                    status, error = "completed", "model decision must be an object"
                    break
                if "answer" in decision:
                    answer = decision["answer"]
                    status, error = "completed", ""
                    break
                calls = decision.get("tool_calls")
                if not isinstance(calls, list) or not 1 <= len(calls) <= 8:
                    status, error = (
                        "crashed",
                        "model must provide 1..8 tool calls or an answer",
                    )
                    break
                graph = []
                runtime_tools = {}
                for c in calls:
                    if self.workload_runtime:
                        if not isinstance(c, dict):
                            raise ValueError("tool call must be an object")
                        runtime_tools[c["tool"]] = self.workload_runtime.tool(task, c)
                        graph.append(
                            ToolCall(
                                str(c["id"]),
                                c["tool"],
                                c.get("args", {}),
                                tuple(c.get("depends_on", ())),
                            )
                        )
                        continue
                    if (
                        not isinstance(c, dict)
                        or c.get("tool") != "inspect_asset"
                        or c.get("args", {}) != {}
                    ):
                        raise ValueError("tool request is outside the declared schema")
                    graph.append(
                        ToolCall(
                            str(c["id"]),
                            "inspect_asset",
                            {},
                            tuple(c.get("depends_on", ())),
                        )
                    )
                local_events = []
                token = None

                def record_tool_event(event):
                    nonlocal token
                    local_events.append(event)
                    # Start only after a child enters tool invocation, rather
                    # than while the parent is still launching that process.
                    # The child never waits for this callback: receipt can lag
                    # behind body completion on short tools, which stays visible
                    # in body timestamps and observed_ns.
                    if (
                        self.lifecycle
                        and token is None
                        and event["event"] == "body_start"
                    ):
                        token = self.lifecycle.start_pause()

                tool = PilotAssetTool(str(task.asset_path), task.family)
                if (
                    self.simulated
                    and self.adapter.model_config.get("fixture_case") == "tool_timeout"
                ):
                    tool = DelayedFixtureTool(tool)
                if self.lifecycle:
                    # Selection is charged inside the goal window, before tool
                    # launch. Admission itself waits for body-start notification.
                    self.lifecycle.plan_pause()
                tool_executor = BoundedToolExecutor(
                    runtime_tools or {"inspect_asset": tool},
                    max_concurrent_calls=2 if plan.tool_concurrency else 1,
                    workers_per_tool=plan.tool_workers,
                    timeout_seconds=max(
                        0.001,
                        self.timeout_seconds
                        - (time.monotonic_ns() - lease.started_ns) / 1e9,
                    ),
                    event_sink=record_tool_event,
                )
                pause_error = None
                if self.lifecycle:
                    try:
                        outcomes = tool_executor.execute(graph)
                    finally:
                        events.extend(local_events)
                        try:
                            if token is not None:
                                self.lifecycle.end_pause(token)
                        except Exception as exc:
                            pause_error = exc
                else:
                    outcomes = tool_executor.execute(graph)
                    events.extend(local_events)
                for c in graph:
                    outcome = outcomes[c.call_id]
                    tool_results.append(asdict(outcome))
                    matching = [e for e in local_events if e["call_id"] == c.call_id]
                    ready = next(
                        (e["monotonic_ns"] for e in matching if e["event"] == "ready"),
                        matching[-1]["monotonic_ns"],
                    )
                    begin = next(
                        (e["monotonic_ns"] for e in matching if e["event"] == "start"),
                        ready,
                    )
                    end = next(
                        e["monotonic_ns"] for e in matching if e["event"] == "end"
                    )
                    spans.append(
                        SpanEvent(
                            f"{lease.attempt_id}:tool:{step}:{c.call_id}",
                            lease.attempt_id,
                            "tool",
                            ready,
                            begin,
                            end,
                            outcome.status,
                            workers_configured=plan.tool_workers,
                            workers_observed=outcome.workers_observed or None,
                            input_sha256=digest(c.args),
                            output_sha256=digest(outcome.result),
                            error=outcome.error or "",
                        )
                    )
                if pause_error is not None:
                    raise pause_error
                if any(o.status != "completed" for o in outcomes.values()):
                    status = (
                        "timed_out"
                        if any(o.status == "timed_out" for o in outcomes.values())
                        else "crashed"
                    )
                    error = "tool execution did not complete"
                    break
        except Exception as exc:
            status, error = "crashed", f"{type(exc).__name__}: {exc}"
            # Unexpected failures need conservative ownership handling.
            from studies.energy_diagnosis.workloads.bounded_executor import (
                BoundedExecutionError,
            )

            if isinstance(exc, BoundedExecutionError):
                owned_terminated = False
        if self.lifecycle:
            try:
                if self.initialized_model_window:
                    self.lifecycle.settle_work()
                    inner_settled = True
                else:
                    self.lifecycle.end_goal()
            except Exception as exc:
                status, error = "crashed", f"{error}; expert cleanup failed: {exc}"
                if not self.initialized_model_window:
                    owned_terminated = (
                        owned_terminated and self.lifecycle.backend.process is None
                    )
                inner_window["reason"] = f"task work not confirmed idle: {exc}"
        if self.lifecycle and not self.initialized_model_window:
            owned_terminated = (
                owned_terminated and self.lifecycle.backend.owned_work_terminated
            )
        verify_start = time.monotonic_ns()
        if status == "completed":
            try:
                result = (
                    self.workload_runtime.verify(task, answer)
                    if self.workload_runtime
                    else verify_pilot(task, answer)
                )
                verifier = VerifierResult(
                    plan.verifier_version,
                    "pass" if result["passed"] else "fail",
                    result["reason"],
                )
            except Exception as exc:
                verifier = VerifierResult(
                    plan.verifier_version, "unavailable", str(exc)
                )
        else:
            verifier = VerifierResult(plan.verifier_version, "unavailable", error)
        verify_end = time.monotonic_ns()
        spans.append(
            SpanEvent(
                f"{lease.attempt_id}:verify",
                lease.attempt_id,
                "verify",
                verify_start,
                verify_start,
                verify_end,
                "completed" if verifier.outcome in {"pass", "fail"} else "failed",
                error=(
                    verifier.reason if verifier.outcome not in {"pass", "fail"} else ""
                ),
            )
        )
        if self.initialized_model_window:
            try:
                if inner_started and inner_settled and self.lifecycle.backend.idle_confirmed:
                    self.measurement.checkpoint("initialized_model_end")
                    inner_measurements = self.measurement.measure_between(
                        "initialized_model_start", "initialized_model_end"
                    )
                    inner_valid = bool(inner_measurements) and all(
                        m.status == "valid" for m in inner_measurements
                    )
                    inner_window.update(
                        status="valid" if inner_valid else "unavailable",
                        reason="" if inner_valid else "missing or invalid counter data",
                        measurements=[m.to_dict() for m in inner_measurements],
                    )
            except Exception as exc:
                inner_window.update(status="unavailable", reason=f"checkpoint failed: {exc}")
            finally:
                try:
                    self.lifecycle.end_goal()
                except Exception as exc:
                    status, error = "crashed", f"{error}; expert release failed: {exc}"
                owned_terminated = owned_terminated and self.lifecycle.backend.owned_work_terminated
            invalid_reason = self._termination_invalidity(owned_terminated)
            if invalid_reason:
                inner_window.update(status="invalid", reason=invalid_reason)
                inner_window["measurements"] = [
                    dict(m, status="invalid", energy_j=None, coverage=None, reason=invalid_reason)
                    for m in inner_window["measurements"]
                ]
        measured = self.measurement.finish_goal()
        if self.initialized_model_window:
            for name, begin, end in (
                ("before_task_window", "goal_start", "initialized_model_start"),
                ("after_task_window", "initialized_model_end", "goal_end"),
            ):
                try:
                    portion = self.measurement.measure_between(begin, end)
                    inner_window[name] = dict(measurements=[m.to_dict() for m in portion])
                except Exception as exc:
                    inner_window[name] = dict(measurements=[], reason=str(exc))
        invalid_reason = self._termination_invalidity(owned_terminated)
        if invalid_reason:
            measured = replace(
                measured,
                measurements=tuple(
                    replace(
                        m,
                        status="invalid",
                        energy_j=None,
                        coverage=None,
                        reason=f"{invalid_reason}; captured interval is not complete goal energy",
                    )
                    for m in measured.measurements
                ),
            )
            if self.initialized_model_window:
                for name in ("before_task_window", "after_task_window"):
                    inner_window[name] = dict(measurements=[], reason=invalid_reason)
        record = ExecutionRecord(
            lease.execution_id,
            lease.planned_run_id,
            lease.session_id,
            task.task_id,
            plan.setting_id,
            lease.attempt_number,
            status,
            lease.started_ns,
            measured.goal_end_ns,
            lease.clock_domain,
            verifier,
            simulated=self.simulated,
            model_response=response,
            spans=tuple(spans),
            measurements=measured.measurements,
            error=error if status != "completed" else "",
            notes=(
                "SIMULATED model and counters; real HTTP and tool execution."
                if self.simulated
                else "CPU/GPU domains only; no whole-node total."
            ),
        )
        for name, payload, role in [
            ("model-calls.json", model_calls, "model-calls"),
            ("tool-results.json", tool_results, "tool-results"),
            ("events.json", events, "tool-events"),
            ("measurement.json", measured.to_dict(), "raw-measurement"),
            ("answer.json", answer, "answer"),
            ("record.json", record.to_dict(), "execution-record"),
        ]:
            artifacts.append(
                write_artifact(self.artifact_root, prefix / name, payload, role)
            )
        if self.lifecycle:
            artifacts.append(
                write_artifact(
                    self.artifact_root,
                    prefix / "expert-events.json",
                    self.lifecycle.events,
                    "expert-events",
                )
            )
        if self.initialized_model_window:
            artifacts.append(write_artifact(
                self.artifact_root, prefix / "initialized-model-window.json",
                inner_window, "initialized-model-window",
            ))
        metadata = OutcomeMetadata(
            plan.setting_id,
            plan.tool_concurrency,
            plan.tool_workers,
            request.scheduled_run.preparation_sha256,
            observed_resources=(("cpu_affinity", measured.environment.cpu_allocation),),
            owned_work_terminated=owned_terminated,
            fidelity_status="eligible",
            sensor_gaps=tuple(
                m.domain_id for m in measured.measurements if m.status != "valid"
            ),
            cost_seconds=(("goal", (record.ended_ns - record.started_ns) / 1e9),),
            failure_reason=error,
        )
        if request.checkpoint:
            request.checkpoint(
                artifacts,
                {"owned_work_terminated": owned_terminated, "record_status": status},
            )
        return ExecutionOutcome(record, tuple(artifacts), metadata)


def run(args, *, endpoint=None):
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    selected = load_pilot_tasks()
    if args.task != "all":
        selected = tuple(t for t in selected if t.task_id == args.task)
    if not selected:
        raise ValueError("unknown task ID; use --list-tasks")
    settings = args.settings.split(",")
    if any(s not in SETTINGS for s in settings):
        raise ValueError("unknown setting")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    simulated = args.mode == "fixture"
    if (
        not simulated
        and subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    ):
        raise ValueError(
            "live runs require a clean checkout; commit reviewed code or use a fresh clone"
        )
    base_url = endpoint or args.base_url
    if urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(
            "this node-measured runner requires a loopback inference endpoint"
        )
    if not simulated and (
        not args.model or not args.model_sha256 or not args.allocation_id
    ):
        raise ValueError("live mode needs --model, --model-sha256 and --allocation-id")
    for key in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(key, "")
        os.environ[key] = ",".join(
            filter(None, [current, "127.0.0.1", "localhost", "::1"])
        )
    provider_id = "ollama_local" if args.provider == "ollama" else "vllm_local"
    adapter = OpenAICompatAdapter(
        dict(provider_id=provider_id, base_url=base_url, is_local=True),
        dict(
            model_id=args.model or "SIMULATED",
            max_tokens=args.max_tokens,
            stream=True,
            is_local=True,
            fixture_case=args.fixture_case if simulated else None,
        ),
    )
    model_hash = args.model_sha256 or digest(
        {"model": "SIMULATED", "case": args.fixture_case}
    )
    preparation = digest(
        dict(
            provider=args.provider,
            model=model_hash,
            temperature=0,
            max_tokens=args.max_tokens,
            max_steps=args.max_steps,
            deadline=args.deadline,
            mode=args.mode,
        )
    )
    verifier_hash = hashlib.sha256(
        Path(__file__).with_name("workloads").joinpath("pilot_tasks.py").read_bytes()
    ).hexdigest()
    plans = []
    for task in selected:
        for setting in settings:
            concurrency, workers = SETTINGS[setting]
            if workers != 1 and "tool_workers" not in task.eligible_controls:
                continue
            plans.append(
                PlannedRun(
                    f"{task.task_id}-{setting}",
                    len(plans) + 1,
                    task.task_id,
                    setting,
                    concurrency,
                    workers,
                    revision,
                    task.asset_sha256,
                    model_hash,
                    PILOT_VERIFIER_VERSION,
                    verifier_hash,
                    simulated=simulated,
                )
            )
    schedule = CampaignSchedule.build(
        [ScheduleBlock("local", "node", preparation, tuple(plans))], seed=args.seed
    )
    reader = (
        FixtureCounterReader(missing_gpu=args.fixture_case == "missing_telemetry")
        if simulated
        else NodeCounterReader(args.gpu_index)
    )
    device_identity = {"status": "SIMULATED"} if simulated else reader.device_identity()
    environment = environment_identity(
        revision,
        args.allocation_id or "SIMULATED",
        "SIMULATED" if simulated else args.isolation,
        devices=(
            device_identity.get("uuid", "SIMULATED" if simulated else "unknown-gpu"),
        ),
    )
    import importlib.metadata

    versions = {}
    for name in ("requests", "psutil", "cloudpickle", "nvidia-ml-py", "PyYAML"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    manifest = dict(
        device_identity=device_identity,
        runtime_versions=versions,
        working_tree_dirty=bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
        environment=asdict(environment),
        mode=args.mode,
        model_sha256=model_hash,
        provider=args.provider,
        base_url=base_url,
        preparation_sha256=preparation,
    )
    manifest_path = root / "environment.json"
    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    count = 0
    ledger = RunLedger(root / "ledger.sqlite", artifact_root=root)
    runner = BoundedCampaignRunner(ledger, schedule, root / "state")
    try:
        for _ in range(args.max_runs):
            measurement = NodeMeasurement(
                reader,
                environment,
                session_id=("fixture-" if simulated else "") + str(uuid.uuid4()),
            )
            if simulated:
                measurement.clock_domain = "fixture:" + measurement.clock_domain
                measurement.session.clock_domain = measurement.clock_domain
            started = measurement.start_goal()
            executor = GoalExecutor(
                {t.task_id: t for t in selected},
                adapter,
                measurement,
                root,
                max_steps=args.max_steps,
                timeout_seconds=args.deadline,
                simulated=simulated,
            )
            try:
                lease = runner.run_next(
                    session_id=measurement.session_id,
                    started_ns=started,
                    clock_domain=measurement.clock_domain,
                    executor=executor,
                )
            finally:
                if measurement.artifacts is None:
                    measurement.finish_goal()
            if lease is None:
                break
            count += 1
    finally:
        paths = runner.export(root / "exports")
        ledger.close()
        reader.close()
    report = json.loads(paths["campaign_validation"].read_text())
    print(
        json.dumps(
            dict(mode=args.mode, executed=count, output=str(root), validation=report),
            indent=2,
        )
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fixture", "live"], default="fixture")
    parser.add_argument("--output", default="artifacts/local-smoke")
    parser.add_argument("--task", default="all")
    parser.add_argument("--list-tasks", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--settings", default="C00")
    parser.add_argument("--max-runs", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--deadline", type=float, default=120)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--provider", choices=["vllm", "ollama"], default="vllm")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model")
    parser.add_argument("--model-sha256")
    parser.add_argument("--allocation-id")
    parser.add_argument("--isolation", default="unverified")
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument(
        "--fixture-case",
        choices=[
            "success",
            "wrong_answer",
            "model_failure",
            "tool_timeout",
            "missing_telemetry",
        ],
        default="success",
    )
    args = parser.parse_args(argv)
    if args.preflight:
        if args.mode != "live" or not args.allocation_id:
            parser.error("preflight needs --mode live and --allocation-id")
        from studies.energy_diagnosis.runtime.measurement import probe_capabilities

        reader = NodeCounterReader(args.gpu_index)
        try:
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip()
            environment = environment_identity(
                revision, args.allocation_id, args.isolation
            )
            report = probe_capabilities(reader, environment=environment).to_dict()
            report["device_identity"] = reader.device_identity()
            output = Path(args.output)
            output.mkdir(parents=True, exist_ok=True)
            path = output / ("preflight-" + str(time.time_ns()) + ".json")
            path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
            readable = {
                d["domain_id"] for d in report["domains"] if d["access"] == "readable"
            }
            if (
                not any(d.startswith("PACKAGE") for d in readable)
                or f"GPU_BOARD_{args.gpu_index}" not in readable
            ):
                raise SystemExit(2)
            return
        finally:
            reader.close()
    if args.list_tasks:
        print("\n".join(t.task_id for t in load_pilot_tasks()))
        return
    if args.max_runs < 1 or args.max_steps < 1 or not 0 < args.deadline <= 600:
        parser.error("invalid run/step/deadline budget")
    if args.mode == "fixture":
        args.provider = "vllm"
        with FixtureAPI(args.fixture_case) as endpoint:
            report = run(args, endpoint=endpoint)
    else:
        report = run(args)
    if not report["valid"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
