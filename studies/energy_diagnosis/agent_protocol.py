"""Native multi-turn chat and tool-call protocol for workload runtimes.

Replaces the V6 single-message JSON protocol (legacy-json-v1), in which every
step re-sent one user message holding a static instruction and tool results
without the calls that produced them, and timing metadata reached the model.

Here the model sees a normal conversation rendered by its own chat template:
system rules, the goal, then each assistant tool call (name and arguments) and
its semantic result. Answers are submitted through a submit_answer tool.
Measurement metadata never enters model-visible messages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re

PROTOCOL_VERSION = "chat-tools-v1"
# chat-tools-v2 differs from v1 only in two model-visible details, both opt-in:
# an unclosed final <tool_call> is parsed to the end of the response (as the
# vLLM hermes parser does), and feedback after an unusable turn names the fix.
PROTOCOL_V2 = "chat-tools-v2"
CHAT_PROTOCOLS = (PROTOCOL_VERSION, PROTOCOL_V2)
FEEDBACK_HINTS = {
    "unbalanced tool_call tags": 'write each call as <tool_call>{"name": ..., "arguments": {...}}</tool_call>, '
                                 "including the closing tag",
    "no tool call": 'text outside <tool_call> tags is not acted on; wrap the call as '
                    '<tool_call>{"name": "TOOL_NAME", "arguments": {...}}</tool_call>. '
                    'To finish, use name "submit_answer" and arguments {"answer": <your task answer>}',
}
SUBMIT = "submit_answer"
MAX_CALLS_PER_TURN = 8
# Keys that describe execution cost rather than task semantics. They stay in
# records and must never reach the model: they differ between arms.
HIDDEN_KEYS = frozenset({"tool_accounting", "elapsed_ns", "cpu_ns", "workers_observed", "workers_configured"})

OUTCOMES = (
    "passed",
    "wrong_answer",
    "performance_budget_exceeded",
    "program_error",
    "program_timeout",
    "output_truncated",
    "turn_budget_exhausted",
    "tool_call_budget_exhausted",
    "output_budget_exhausted",
    "context_exhausted",
    "deadline_exceeded",
    "infrastructure_failure",
)

SYSTEM = (
    "You are an agent solving one task with the tools provided. Call tools to inspect data and "
    "compute results; you will receive each result before your next turn. Base the answer only on "
    "tool results. When the results support the answer, call submit_answer with "
    '{"answer": <object in the format the task specifies>}; submit_answer must be the only call in '
    "that turn. Each turn is one response; the number of turns is limited, and each tool result "
    "reports turns_remaining."
)


def strict_loads(text):
    """json.loads that rejects duplicate keys and non-finite numbers."""
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key {key!r}")
            out[key] = value
        return out

    def constant(name):
        raise ValueError(f"non-finite JSON number {name}")

    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float)


def visible(value):
    """Remove execution metadata recursively from a tool result."""
    if isinstance(value, dict):
        return {k: visible(v) for k, v in value.items() if k not in HIDDEN_KEYS}
    if isinstance(value, list):
        return [visible(v) for v in value]
    return value


def function_tools(runtime_tools):
    """Runtime tool contracts -> chat-template function tools, plus submit_answer."""
    tools = []
    for name, spec in sorted(runtime_tools.items()):
        parameters = spec.get("parameters")
        if parameters is None:
            args = spec.get("args", {})
            parameters = dict(type="object", properties={k: dict(type="string", description=v) for k, v in args.items()},
                              additionalProperties=False)
        tools.append(dict(type="function", function=dict(name=name, description=spec.get("description", ""), parameters=parameters)))
    tools.append(dict(type="function", function=dict(
        name=SUBMIT,
        description="Submit the final answer. Must be the only call in its turn; ends the task.",
        parameters=dict(type="object", properties=dict(answer=dict(type="object", description="Answer in the format the task specifies.")),
                        required=["answer"], additionalProperties=False))))
    return tools


@dataclass(frozen=True)
class Decision:
    kind: str                      # tool_calls | answer | no_action | malformed
    calls: tuple = ()              # ((name, arguments), ...)
    answer: object = None
    reason: str = ""
    content: str = ""              # visible text outside tool-call blocks
    repaired: str = ""             # accepted deviation from the strict format (chat-tools-v2 only)


_BLOCK = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)


def parse_response(text, max_calls=MAX_CALLS_PER_TURN, *, accept_unclosed_final=False):
    """Parse a Qwen-format response. Never guesses: anything ambiguous is malformed.

    accept_unclosed_final (chat-tools-v2): a last <tool_call> with no closing tag
    runs to the end of the response, like vLLM's hermes parser
    (<tool_call>(.*?)</tool_call>|<tool_call>(.*)). Its JSON is still parsed strictly.
    """
    if not isinstance(text, str):
        return Decision("malformed", reason="response text missing")
    tail, repaired = None, ""
    if accept_unclosed_final:
        start = text.rfind("<tool_call>")
        if start >= 0 and "</tool_call>" not in text[start:]:
            text, tail = text[:start], text[start + len("<tool_call>"):]
            repaired = "unclosed final tool_call accepted"
    blocks = _BLOCK.findall(text) + ([tail] if tail is not None else [])
    content = _BLOCK.sub("", text).strip()
    if "<tool_call>" in content or "</tool_call>" in content:
        return Decision("malformed", reason="unbalanced tool_call tags", content=content)
    if not blocks:
        return Decision("no_action", reason="no tool call", content=content)
    if len(blocks) > max_calls:
        return Decision("malformed", reason=f"more than {max_calls} tool calls", content=content)
    calls = []
    for block in blocks:
        try:
            call = strict_loads(block.strip())
        except ValueError as exc:
            return Decision("malformed", reason=f"invalid tool call JSON: {exc}", content=content)
        if not isinstance(call, dict) or set(call) != {"name", "arguments"} or not isinstance(call["name"], str) \
                or not isinstance(call["arguments"], dict):
            return Decision("malformed", reason="tool call must be {name, arguments}", content=content)
        calls.append((call["name"], call["arguments"]))
    if any(name == SUBMIT for name, _ in calls):
        if len(calls) != 1:
            return Decision("malformed", reason="submit_answer mixed with other tool calls", content=content)
        arguments = calls[0][1]
        if set(arguments) != {"answer"}:
            return Decision("malformed", reason="submit_answer takes exactly {answer}", content=content)
        return Decision("answer", answer=arguments["answer"], content=content, repaired=repaired)
    return Decision("tool_calls", calls=tuple(calls), content=content, repaired=repaired)


@dataclass
class Conversation:
    """Model-visible history. Deterministic given identical tool semantics."""
    goal: str
    tools: list
    max_turns: int
    protocol: str = PROTOCOL_VERSION
    messages: list = field(default_factory=list)
    turns_used: int = 0

    def __post_init__(self):
        self.messages = [dict(role="system", content=SYSTEM),
                         dict(role="user", content=f"{self.goal}\n\nYou have {self.max_turns} turns.")]

    def request(self):
        return dict(messages=json.loads(json.dumps(self.messages)), tools=self.tools)

    def record_turn(self, decision, call_ids=()):
        self.turns_used += 1
        message = dict(role="assistant", content=decision.content)
        if decision.kind == "tool_calls":
            message["tool_calls"] = [dict(type="function", id=i, function=dict(name=n, arguments=a))
                                     for i, (n, a) in zip(call_ids, decision.calls)]
        self.messages.append(message)

    def remaining(self):
        return self.max_turns - self.turns_used

    def tool_result(self, call_id, name, status, payload):
        body = dict(status=status, turns_remaining=self.remaining())
        body["result" if status == "ok" else "error"] = visible(payload)
        self.messages.append(dict(role="tool", tool_call_id=call_id, name=name,
                                  content=json.dumps(body, sort_keys=True, allow_nan=False)))

    def feedback(self, reason):
        # No tool result exists to carry the notice, so it is a user message.
        hint = FEEDBACK_HINTS.get(reason) if self.protocol == PROTOCOL_V2 else None
        error = f"{reason}: {hint}. Call a tool or submit_answer." if hint else f"{reason}. Call a tool or submit_answer."
        self.messages.append(dict(role="user", content=json.dumps(
            dict(status="error", error=error, turns_remaining=self.remaining()), sort_keys=True)))


def to_native_text(decision):
    """Legacy scripted decision {tool_calls|answer} -> Qwen-format text (fixtures only)."""
    if "answer" in decision:
        calls = [dict(name=SUBMIT, arguments=dict(answer=decision["answer"]))]
    else:
        calls = [dict(name=c["tool"], arguments=c.get("args", {})) for c in decision["tool_calls"]]
    return "\n".join(f"<tool_call>\n{json.dumps(c)}\n</tool_call>" for c in calls)


def legacy_context(request, meta):
    """Chat request -> legacy context shape consumed by fixture scripted models."""
    # Scripted models count successful results to choose the next call, so a
    # failed call is retried rather than skipped.
    results = []
    for message in request["messages"]:
        if message["role"] == "tool":
            body = json.loads(message["content"])
            if body.get("status") == "ok":
                results.append(dict(result=body["result"]))
    return dict(meta, tool_results=results)


# Verifier failure labels (verification.json result["failure"]) -> attempt outcome. A correct-but-slow program,
# a crashing program and a worker/sandbox fault are not wrong answers; unknown or absent labels stay wrong_answer.
FAILURE_OUTCOMES = {
    "budget": "performance_budget_exceeded",
    "budget_exceeded": "performance_budget_exceeded",
    "error": "program_error",
    "runtime_error": "program_error",
    "hidden_timeout": "program_timeout",
    "worker_error": "infrastructure_failure",
}


def outcome_class(execution_status, verifier_outcome, terminal, failure=None):
    """One reason per attempt. Every class is still an attempt with its energy."""
    if terminal:
        return terminal
    if execution_status == "completed":
        if verifier_outcome == "fail":
            return FAILURE_OUTCOMES.get(failure, "wrong_answer")
        return {"pass": "passed"}.get(verifier_outcome, "infrastructure_failure")
    if execution_status == "timed_out":
        return "deadline_exceeded"
    return "infrastructure_failure"


def turn_seed(base, pair_key, step):
    """Sampling seed shared by both arms of a pair at the same turn."""
    import hashlib
    return int.from_bytes(hashlib.sha256(f"{base}:{pair_key}:{step}".encode()).digest()[:4], "big") & 0x7FFFFFFF


class ScriptedChatAdapter:
    """Fixture-only: exposes chat() over a scripted legacy-protocol model."""

    def __init__(self, scripted):
        self.scripted = scripted
        self.model_config = scripted.model_config

    def chat(self, request, sampling, meta):
        raw = self.scripted.call(json.dumps(legacy_context(request, meta)), 0)
        if raw.get("status", "ok") != "ok":
            return raw
        return dict(raw, content=to_native_text(json.loads(raw["content"])), finish_reason="stop")
