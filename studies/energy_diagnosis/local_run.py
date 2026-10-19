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
from studies.energy_diagnosis.agent_protocol import (
    PROTOCOL_VERSION as CHAT_PROTOCOL,
    CHAT_PROTOCOLS,
    PROTOCOL_V2,
    Conversation,
    function_tools,
    outcome_class,
    parse_response,
    turn_seed,
)
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
    BoundedExecutionError,
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
from studies.energy_diagnosis.moe import event_log

SETTINGS = {"C00": (False, 1), "C01": (False, 4), "C10": (True, 1), "C11": (True, 4)}
STAGED_INSPECTION = "staged-inspection-v1"


class _VerificationTool:
    """Run the checker in an owned process so its deadline is enforceable."""
    def __init__(self, callback, task, answer):
        self.callback, self.task, self.answer = callback, task, answer

    def execute(self, workers=1):
        return self.callback(self.task, self.answer)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def write_artifact(root, relative, value, role, compact=False, encoded=None):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    # compact: identical JSON content without indentation; encoded: caller-supplied bytes (e.g. the
    # gzip event log). The recorded hash always covers the exact bytes written.
    if encoded is None:
        encoded = (json.dumps(value, sort_keys=True, allow_nan=False,
                              **(dict(separators=(",", ":")) if compact else dict(indent=2))) + "\n").encode()
    # Attempt identities are unique; replacing an artifact would break auditability.
    with path.open("xb") as handle:
        handle.write(encoded)
    return ArtifactRef(relative.as_posix(), role, hashlib.sha256(encoded).hexdigest())


def _answer_instruction(task):
    """Shared final schema; never includes reference totals."""
    fields = (dict(total_units="<computed number>", total_revenue="<computed number>")
              if task.family == "data" else
              dict(file_count="<computed integer>", checks=["<sorted relative paths>"]))
    final = {"answer": {**fields, "task_id": task.task_id,
                        "evidence": [task.asset_sha256]}}
    return (
        "After receiving successful tool_results, return this complete final shape: "
        + json.dumps(final) + ". Replace computed-value placeholders with values "
        "from the tool result. All totals or repository fields, task_id and evidence "
        "belong INSIDE answer; no required field belongs beside answer. Data totals "
        "must be numbers or decimal strings, never null. Repository checks must be "
        "a sorted list of relative paths. Never invent observations or evidence."
    )


def legacy_instruction(task):
    """Describe the existing JSON protocol without supplying reference answers."""
    tool = {"tool_calls": [{"id": "inspect_1", "tool": "inspect_asset", "args": {}}]}
    return (
        "Return only one JSON object per turn. First inspect the local input with "
        + json.dumps(tool) + ". Tool calls require a unique string id, tool "
        "inspect_asset and empty args {}; optional depends_on is a list of call ids. "
        "Return 1..8 tool calls, without an answer in the same object. "
        + _answer_instruction(task)
    )


def inspected_asset(tool_results):
    """Only runtime-owned successful inspection outcomes unlock the answer stage."""
    return any(r.get("tool") == "inspect_asset" and r.get("status") == "completed"
               and isinstance(r.get("result"), dict) for r in tool_results)


def staged_instruction(task, tool_results):
    if not inspected_asset(tool_results):
        tool = {"tool_calls": [{"id": "inspect_1", "tool": "inspect_asset", "args": {}}]}
        return (
            "Return only one JSON object requesting inspection of the local input: "
            + json.dumps(tool) + ". Use a unique string id, tool inspect_asset and "
            "empty args {}; optional depends_on is a list of call ids. Return 1..8 "
            "tool calls. No successful inspection result exists yet. Do not return "
            "an answer or invent observations."
        )
    # Reuse the reviewed final schema and its constraints, without the first-stage
    # tool-call example. Values come exclusively from actual runtime tool results.
    return ("Return only one JSON object using the actual successful inspect_asset "
            "result in tool_results. " + _answer_instruction(task))


class FixtureAPI:
    """Deterministic HTTP responder, clearly labeled and only explicitly selected."""

    def __init__(self, case="success", *, scripted_responses=None):
        self.case = case
        self.scripted_responses = None if scripted_responses is None else iter(scripted_responses)
        self.requests = []

    def __enter__(self):
        case = self.case
        scripted = self.scripted_responses
        requests_seen = self.requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                raw = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                context = json.loads(raw["messages"][-1]["content"])
                requests_seen.append(raw)
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
                text = next(scripted) if scripted is not None else json.dumps(answer)
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
        protocol="legacy-json-v1",
        sampling=None,
        max_tool_calls=None,
        max_output_tokens=None,
        diagnostic_variant=None,
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
        if protocol not in {"legacy-json-v1", *CHAT_PROTOCOLS}:
            raise ValueError("unknown agent protocol")
        if protocol in CHAT_PROTOCOLS and workload_runtime is None:
            raise ValueError("the chat protocol requires a workload runtime")
        # legacy-json-v1 reproduces V6: one user message per step holding a
        # static instruction and tool results. chat-tools-v1 is the native
        # multi-turn protocol (agent_protocol.py).
        self.protocol = protocol
        if diagnostic_variant not in {None, STAGED_INSPECTION}:
            raise ValueError("unknown diagnostic variant")
        if diagnostic_variant and (protocol != "legacy-json-v1" or workload_runtime is not None):
            raise ValueError("staged inspection requires the legacy pilot runtime")
        self.diagnostic_variant = diagnostic_variant
        self.sampling = sampling or dict(mode="greedy")
        self.max_tool_calls = max_tool_calls
        self.max_output_tokens = max_output_tokens

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

    def _chat(self, task, lease, plan, context, model_calls, tool_results, spans, events, trace, artifacts, checkpoint):
        """chat-tools-v1 turn loop -> (status, error, answer, response, owned_terminated).

        Tool errors and unusable responses are returned to the model as
        observations and cost a turn; only budget, deadline and infrastructure
        limits end the attempt. The reason is recorded in trace["terminal"].
        """
        deadline_ns = lease.started_ns + int(self.timeout_seconds * 1e9)
        conversation = Conversation(task.prompt, function_tools(context["tools"]), self.max_steps, protocol=self.protocol)
        meta = dict(task_id=task.task_id, family=task.family, asset_sha256=task.asset_sha256)
        suffix = "-" + plan.setting_id
        pair_key = plan.planned_run_id[: -len(suffix)] if plan.planned_run_id.endswith(suffix) else plan.planned_run_id
        trace.update(
            sampling=self.sampling,
            limits=dict(turns=self.max_steps, tool_calls=self.max_tool_calls,
                        output_tokens_per_turn=self.adapter.model_config["max_tokens"],
                        output_tokens_total=self.max_output_tokens, goal_seconds=self.timeout_seconds),
        )
        response, calls_used, output_used, seen = None, 0, 0, set()
        per_turn_tokens = self.adapter.model_config["max_tokens"]

        def save_turn(step, phase, payload):
            # Immutable partial evidence survives interruption before finalization.
            ref = write_artifact(self.artifact_root,
                Path("goals") / lease.execution_id / "turns" / f"{step:03d}-{phase}.json",
                dict(protocol=self.protocol, partial=True, step=step, phase=phase, payload=payload),
                f"agent-turn-{phase}")
            artifacts.append(ref)
            if checkpoint:
                checkpoint([ref], metadata=dict(stage=phase, step=step, partial=True))

        def stop(kind, detail, execution="incomplete"):
            trace["terminal"] = kind
            return execution, f"{kind}: {detail}", None, response, True

        for step in range(self.max_steps):
            now = time.monotonic_ns()
            if now >= deadline_ns:
                return stop("deadline_exceeded", "goal deadline reached between turns", "timed_out")
            remaining_output = None if self.max_output_tokens is None else self.max_output_tokens - output_used
            if remaining_output is not None and remaining_output <= 0:
                return stop("output_budget_exhausted", f"{output_used} output tokens used")
            call_budget = per_turn_tokens if remaining_output is None else min(per_turn_tokens, remaining_output)
            request = conversation.request()
            sampling = (dict(self.sampling, seed=turn_seed(self.sampling["seed"], pair_key, step))
                        if self.sampling["mode"] == "sampled" else dict(mode="greedy"))
            self.adapter.model_config["request_timeout_seconds"] = max(0.001, (deadline_ns - now) / 1e9)
            if self.lifecycle:
                self.lifecycle.before_model(f"{lease.attempt_id}:model:{step}")
            started = time.monotonic_ns()
            self.adapter.model_config["max_tokens"] = call_budget
            try:
                raw = self.adapter.chat(request, sampling, meta)
            finally:
                self.adapter.model_config["max_tokens"] = per_turn_tokens
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
            model_calls.append(dict(response=response.to_dict(), adapter=raw, request=request, sampling=sampling,
                                    max_tokens=call_budget))
            save_turn(step, "model", model_calls[-1])
            spans.append(SpanEvent(
                response.request_id, lease.attempt_id, "model", started, started, ended,
                "completed" if ok else "failed",
                input_sha256=digest(request), output_sha256=digest(raw), error=response.error,
            ))
            if self.lifecycle and ok:
                self.lifecycle.after_model()
            if not ok:
                # A disconnected live inference server may still own work.
                owned = self.simulated or raw.get("owned_work_terminated") is True
                kind = "deadline_exceeded" if time.monotonic_ns() >= deadline_ns else "infrastructure_failure"
                status, error, _, _, _ = stop(kind, response.error, "timed_out" if kind == "deadline_exceeded" else "crashed")
                return status, error, None, response, owned
            count = tokens.get("completion")
            if type(count) is not int or count < 0 or count > call_budget:
                return stop("infrastructure_failure", "missing or out-of-budget completion token count", "crashed")
            output_used += count
            finish = raw.get("finish_reason")
            turn = dict(step=step, finish_reason=finish, prompt_tokens=tokens.get("prompt"),
                        completion_tokens=tokens.get("completion"), sampling_seed=sampling.get("seed"),
                        output_budget=call_budget)
            trace["turns"].append(turn)
            if finish == "context_exhausted":
                return stop("context_exhausted", f"{tokens.get('prompt')} prompt tokens plus the output allowance exceed the context")
            if finish == "length":
                kind = "output_budget_exhausted" if remaining_output is not None and output_used >= self.max_output_tokens else "output_truncated"
                return stop(kind, f"response reached {call_budget} output tokens")
            decision = parse_response(raw.get("content"), accept_unclosed_final=self.protocol == PROTOCOL_V2)
            turn.update(kind=decision.kind, reason=decision.reason)
            if decision.repaired:
                turn["repaired"] = decision.repaired
            if decision.kind == "answer":
                conversation.record_turn(decision)
                return "completed", "", decision.answer, response, True
            if decision.kind != "tool_calls":
                conversation.record_turn(decision)
                conversation.feedback(decision.reason)
            else:
                if self.max_tool_calls is not None and calls_used + len(decision.calls) > self.max_tool_calls:
                    return stop("tool_call_budget_exhausted", f"{calls_used} of {self.max_tool_calls} calls used")
                calls_used += len(decision.calls)
                ids = [f"t{step:02d}c{i}" for i in range(len(decision.calls))]
                conversation.record_turn(decision, ids)
                graph, runtime_tools, rejected = [], {}, {}
                for cid, (name, arguments) in zip(ids, decision.calls):
                    key = digest([name, arguments])
                    turn["repeated_calls"] = turn.get("repeated_calls", 0) + (key in seen)
                    seen.add(key)
                    try:
                        runtime_tools[name] = self.workload_runtime.tool(task, dict(id=cid, tool=name, args=arguments))
                        graph.append(ToolCall(cid, name, arguments))
                    except (ValueError, KeyError, TypeError) as exc:
                        rejected[cid] = f"invalid call: {exc}"
                outcomes = self._execute_graph(graph, runtime_tools, plan, lease, step, spans, events, deadline_ns) if graph else {}
                timed_out = False
                for cid, (name, _) in zip(ids, decision.calls):
                    if cid in rejected:
                        conversation.tool_result(cid, name, "error", rejected[cid])
                        continue
                    outcome = outcomes[cid]
                    tool_results.append(asdict(outcome))
                    timed_out |= outcome.status == "timed_out"
                    if outcome.status == "completed":
                        conversation.tool_result(cid, name, "ok", outcome.result)
                    else:
                        conversation.tool_result(cid, name, "error", outcome.error or outcome.status)
                save_turn(step, "tools", dict(outcomes=[asdict(o) for o in outcomes.values()],
                                               rejected=rejected, next_request=conversation.request()))
                if timed_out:
                    return stop("deadline_exceeded", "tool execution reached the goal deadline", "timed_out")
            if self.max_output_tokens is not None and output_used >= self.max_output_tokens:
                return stop("output_budget_exhausted", f"{output_used} output tokens used")
        return stop("turn_budget_exhausted", f"{self.max_steps} turns without an answer")

    def _execute_graph(self, graph, runtime_tools, plan, lease, step, spans, events, deadline_ns):
        """Run one turn's calls inside a lifecycle tool pause; record spans and events."""
        local_events = []
        token = None

        def record_tool_event(event):
            nonlocal token
            local_events.append(event)
            # Start the pause only once a child is inside the tool body.
            if self.lifecycle and token is None and event["event"] == "body_start":
                token = self.lifecycle.start_pause()

        if self.lifecycle:
            self.lifecycle.plan_pause()
        executor = BoundedToolExecutor(
            runtime_tools,
            max_concurrent_calls=2 if plan.tool_concurrency else 1,
            workers_per_tool=plan.tool_workers,
            timeout_seconds=max(0.001, (deadline_ns - time.monotonic_ns()) / 1e9),
            event_sink=record_tool_event,
            deadline_ns=deadline_ns,
        )
        pause_error = None
        try:
            outcomes = executor.execute(graph)
        finally:
            events.extend(local_events)
            if self.lifecycle:
                try:
                    if token is not None:
                        self.lifecycle.end_pause(token)
                except Exception as exc:
                    pause_error = exc
        for c in graph:
            outcome = outcomes[c.call_id]
            matching = [e for e in local_events if e["call_id"] == c.call_id]
            ready = next((e["monotonic_ns"] for e in matching if e["event"] == "ready"), matching[-1]["monotonic_ns"])
            begin = next((e["monotonic_ns"] for e in matching if e["event"] == "start"), ready)
            end = next(e["monotonic_ns"] for e in matching if e["event"] == "end")
            spans.append(SpanEvent(
                f"{lease.attempt_id}:tool:{step}:{c.call_id}", lease.attempt_id, "tool", ready, begin, end,
                outcome.status, workers_configured=plan.tool_workers,
                workers_observed=outcome.workers_observed or None,
                input_sha256=digest(c.args), output_sha256=digest(outcome.result), error=outcome.error or "",
            ))
        if pause_error is not None:
            raise pause_error
        return outcomes

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
        deadline_ns = lease.started_ns + int(self.timeout_seconds * 1e9)
        trace = dict(protocol=self.protocol, terminal=None, turns=[])
        context = dict(
            task_id=task.task_id,
            asset_sha256=task.asset_sha256,
            goal=task.prompt,
            instruction=legacy_instruction(task),
            tool_results=tool_results,
        )
        try:
            if self.lifecycle:
                self.lifecycle.begin_goal(lease.attempt_id, task_id=plan.task_id)
            if self.initialized_model_window:
                self.measurement.checkpoint("initialized_model_start")
                inner_started = True
            if self.lifecycle:
                # static prepares its profile here, inside the measured task window.
                self.lifecycle.prepare_ahead()
            if self.workload_runtime:
                self.workload_runtime.begin(task, lease)
                context.update(self.workload_runtime.context(task))
            if self.protocol in CHAT_PROTOCOLS:
                status, error, answer, response, owned_terminated = self._chat(
                    task, lease, plan, context, model_calls, tool_results, spans, events, trace, artifacts, request.checkpoint
                )
            for step in range(self.max_steps if self.protocol not in CHAT_PROTOCOLS else 0):
                if (
                    time.monotonic_ns() - lease.started_ns
                ) / 1e9 >= self.timeout_seconds:
                    status, error = "timed_out", "goal deadline exhausted between calls"
                    break
                if self.diagnostic_variant == STAGED_INSPECTION:
                    context["instruction"] = staged_instruction(task, tool_results)
                prompt = json.dumps(context, sort_keys=True)
                started = time.monotonic_ns()
                self.adapter.model_config["request_timeout_seconds"] = max(
                    0.001, self.timeout_seconds - (started - lease.started_ns) / 1e9
                )
                if self.lifecycle:
                    self.lifecycle.before_model(f"{lease.attempt_id}:model:{step}")
                capture_relative = prefix / f"provider-response-{step}.body"
                if self.diagnostic_variant:
                    (self.artifact_root / prefix).mkdir(parents=True, exist_ok=True)
                    self.adapter.model_config["response_capture_path"] = str(
                        self.artifact_root / capture_relative)
                try:
                    raw = self.adapter.call(prompt, 0.0)
                finally:
                    if self.diagnostic_variant:
                        self.adapter.model_config.pop("response_capture_path", None)
                ended = time.monotonic_ns()
                if self.diagnostic_variant and raw.get("provider_response") is not None:
                    artifacts.append(ArtifactRef(capture_relative.as_posix(), "provider-response-body",
                                                 raw["provider_response"]["sha256"]))
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
                    deadline_ns=deadline_ns,
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
            status = "timed_out" if time.monotonic_ns() >= deadline_ns else "crashed"
            error = f"{type(exc).__name__}: {exc}"
            # Unexpected failures need conservative ownership handling.
            if isinstance(exc, BoundedExecutionError):
                owned_terminated = False
        if self.lifecycle:
            try:
                if self.initialized_model_window and inner_started:
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
        task_end_captured = False
        if self.initialized_model_window and inner_settled:
            # Task work is drained and the model is still resident: the loaded-model task window
            # (the upstream EpG window) ends here, before the verifier runs.
            try:
                self.measurement.checkpoint("task_end")
                task_end_captured = True
            except Exception as exc:
                inner_window["task_window_reason"] = f"task_end checkpoint failed: {exc}"
        verification_detail = dict(status="not_run", reason=error or "execution did not complete")
        verify_start = time.monotonic_ns()
        if status == "completed" and verify_start >= deadline_ns:
            status, error = "timed_out", "goal deadline reached before verification"
        if status == "completed":
            try:
                runtime = self.workload_runtime
                callback = (runtime.verification_callable(task) if hasattr(runtime, "verification_callable")
                            else runtime.verify if runtime is not None else verify_pilot)
                verification_executor = BoundedToolExecutor(
                    {"verify": _VerificationTool(callback, task, answer)},
                    timeout_seconds=max(0.001, (deadline_ns-time.monotonic_ns())/1e9),
                    deadline_ns=deadline_ns,
                )
                checked = verification_executor.execute([ToolCall("verify", "verify", {})])["verify"]
                if checked.status == "timed_out":
                    raise TimeoutError("goal deadline reached during verification")
                if checked.status != "completed":
                    raise RuntimeError(checked.error or "verifier process failed")
                result = checked.result
                verifier = VerifierResult(
                    plan.verifier_version,
                    "pass" if result["passed"] else "fail",
                    result["reason"],
                    evidence=((prefix / "verification.json").as_posix(),),
                )
                try:
                    verification_detail = dict(status="returned", result=json.loads(json.dumps(result, allow_nan=False)))
                except (TypeError, ValueError):
                    verification_detail = dict(status="unavailable", reason="verifier result was not JSON serializable")
            except Exception as exc:
                if isinstance(exc, TimeoutError):
                    status, error = "timed_out", str(exc)
                if isinstance(exc, BoundedExecutionError):
                    owned_terminated = False
                verification_detail = dict(status="error", reason=str(exc))
                verifier = VerifierResult(
                    plan.verifier_version, "unavailable", str(exc),
                    evidence=((prefix / "verification.json").as_posix(),),
                )
        else:
            verifier = VerifierResult(plan.verifier_version, "unavailable", error)
        verify_end = time.monotonic_ns()
        if status == "completed" and verify_end > deadline_ns:
            # The verifier result stays in verification.json for audit; a
            # result produced after the deadline is not a pass.
            status, error = "timed_out", "verification finished after goal deadline"
            verifier = VerifierResult(
                plan.verifier_version, "unavailable", error,
                evidence=((prefix / "verification.json").as_posix(),),
            )
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
                    if task_end_captured:
                        for name, begin, end in (
                            ("task_window", "initialized_model_start", "task_end"),
                            ("verifier_window", "task_end", "initialized_model_end"),
                        ):
                            portion = self.measurement.measure_between(begin, end)
                            inner_window[name] = dict(measurements=[m.to_dict() for m in portion])
            except Exception as exc:
                inner_window.update(status="unavailable", reason=f"checkpoint failed: {exc}")
            finally:
                try:
                    self.lifecycle.end_goal()
                except Exception as exc:
                    status, error = "crashed", f"{error}; expert release failed: {exc}".lstrip("; ")
                    if verifier.outcome in {"pass", "fail"}:
                        # The verifier result stays in verification.json for audit; an attempt whose
                        # backend release failed is not a completed run, so it is not a pass or fail.
                        verifier = VerifierResult(
                            plan.verifier_version, "unavailable",
                            f"backend release failed after verification: {exc}",
                            evidence=((prefix / "verification.json").as_posix(),),
                        )
                owned_terminated = owned_terminated and self.lifecycle.backend.owned_work_terminated
            invalid_reason = self._termination_invalidity(owned_terminated)
            if invalid_reason:
                inner_window.update(status="invalid", reason=invalid_reason)
                inner_window["measurements"] = [
                    dict(m, status="invalid", energy_j=None, coverage=None, reason=invalid_reason)
                    for m in inner_window["measurements"]
                ]
                for name in ("task_window", "verifier_window"):
                    if name in inner_window:
                        inner_window[name] = dict(measurements=[
                            dict(m, status="invalid", energy_j=None, coverage=None, reason=invalid_reason)
                            for m in inner_window[name]["measurements"]])
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
            ("verification.json", verification_detail, "verification-detail"),
            ("record.json", record.to_dict(), "execution-record"),
        ] + ([("agent-trace.json", dict(trace, outcome=outcome_class(
            status, verifier.outcome, trace["terminal"], ((verification_detail or {}).get("result") or {}).get("failure"))),
               "agent-trace")] if self.protocol in CHAT_PROTOCOLS else []):
            artifacts.append(
                write_artifact(self.artifact_root, prefix / name, payload, role)
            )
        if hasattr(self.measurement, "operating_state_artifact"):
            operating = self.measurement.operating_state_artifact()
            operating.update(goal_execution_id=lease.execution_id, simulated=self.simulated)
            artifacts.append(write_artifact(self.artifact_root, prefix / "operating-state.json",
                                            operating, "operating-state"))
        if self.lifecycle:
            artifacts.append(
                write_artifact(
                    self.artifact_root,
                    prefix / "expert-events.json.gz",
                    self.lifecycle.events,
                    "expert-events",
                    encoded=event_log.encode(self.lifecycle.events),
                )
            )
        if self.initialized_model_window:
            artifacts.append(write_artifact(
                self.artifact_root, prefix / "initialized-model-window.json",
                inner_window, "initialized-model-window",
            ))
        diagnostic_reason = ""
        if self.diagnostic_variant:
            inspection_ok = inspected_asset(tool_results)
            capture_ok = bool(model_calls) and all(
                c["adapter"].get("provider_response", {}).get("body_complete") is True
                for c in model_calls)
            if not inspection_ok:
                diagnostic_reason = "no successful inspect_asset before answer"
            elif not capture_ok:
                diagnostic_reason = "provider response capture incomplete"
            diagnostic = dict(
                variant=self.diagnostic_variant, inspection_completed=inspection_ok,
                provider_bodies_complete=capture_ok,
                passed=not diagnostic_reason and status == "completed" and verifier.outcome == "pass",
                reason=diagnostic_reason or error or verifier.reason,
                simulated=self.simulated,
            )
            artifacts.append(write_artifact(self.artifact_root, prefix / "diagnostic-acceptance.json",
                                            diagnostic, "diagnostic-acceptance"))
        metadata = OutcomeMetadata(
            plan.setting_id,
            plan.tool_concurrency,
            plan.tool_workers,
            request.scheduled_run.preparation_sha256,
            observed_resources=(("cpu_affinity", measured.environment.cpu_allocation),),
            owned_work_terminated=owned_terminated,
            fidelity_status="ineligible" if diagnostic_reason else "eligible",
            sensor_gaps=tuple(
                m.domain_id for m in measured.measurements if m.status != "valid"
            ),
            cost_seconds=(("goal", (record.ended_ns - record.started_ns) / 1e9),),
            failure_reason=diagnostic_reason or error,
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
            ollama_num_thread=getattr(args, "ollama_num_thread", None),
            ollama_num_ctx=getattr(args, "ollama_num_ctx", None),
            ollama_keep_alive=getattr(args, "ollama_keep_alive", None),
        ),
    )
    model_hash = args.model_sha256 or digest(
        {"model": "SIMULATED", "case": args.fixture_case}
    )
    preparation_config = dict(
        provider=args.provider, model=model_hash, temperature=0,
        max_tokens=args.max_tokens, max_steps=args.max_steps,
        deadline=args.deadline, mode=args.mode,
    )
    diagnostic_variant = getattr(args, "diagnostic_variant", None)
    if diagnostic_variant:
        preparation_config.update(diagnostic_variant=diagnostic_variant,
                                  provider_response_capture="http-entity-bytes-v1")
    ollama_preparation = None
    if args.provider == "ollama":
        ollama_preparation = adapter.build_ollama_preparation_payload()
        preparation_config.update(
            ollama_options=ollama_preparation["options"],
            ollama_keep_alive=ollama_preparation.get("keep_alive"),
        )
    preparation = digest(preparation_config)
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
        ollama_options=(ollama_preparation["options"] if ollama_preparation else None),
        ollama_keep_alive=getattr(args, "ollama_keep_alive", None),
    )
    manifest_path = root / "environment.json"
    if diagnostic_variant:
        manifest.update(diagnostic_variant=diagnostic_variant,
                        provider_response_capture="http-entity-bytes-v1")
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
                diagnostic_variant=diagnostic_variant,
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
    parser.add_argument("--ollama-num-thread", type=int)
    parser.add_argument("--ollama-num-ctx", type=int)
    parser.add_argument("--ollama-keep-alive", help="Ollama residency duration, e.g. 5m")
    parser.add_argument("--diagnostic-variant", choices=[STAGED_INSPECTION],
                        help="Opt-in staged custom-JSON prompt and raw provider body capture")
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
    if any(value is not None and value < 1 for value in
           (args.ollama_num_thread, args.ollama_num_ctx)):
        parser.error("Ollama thread/context values must be positive")
    if args.provider != "ollama" and any(value is not None for value in
            (args.ollama_num_thread, args.ollama_num_ctx, args.ollama_keep_alive)):
        parser.error("Ollama options require --provider ollama")
    if args.mode == "fixture" and any(value is not None for value in
            (args.ollama_num_thread, args.ollama_num_ctx, args.ollama_keep_alive)):
        parser.error("Ollama runner options are unavailable in fixture mode")
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
