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
# chat-tools-v3 is v2 plus one Mistral parsing rule: a call whose [ARGS] marker is absent
# ([TOOL_CALLS]name{json}) is the same call. vLLM 0.10.2 detokenizes Mistral output without
# every control token except [TOOL_CALLS], so its tool parser cannot tell the two forms apart.
PROTOCOL_V3 = "chat-tools-v3"
CHAT_PROTOCOLS = (PROTOCOL_VERSION, PROTOCOL_V2, PROTOCOL_V3)
FEEDBACK_HINTS = {
    "unbalanced tool_call tags": 'write each call as <tool_call>{"name": ..., "arguments": {...}}</tool_call>, '
                                 "including the closing tag",
    "no tool call": 'text outside <tool_call> tags is not acted on; wrap the call as '
                    '<tool_call>{"name": "TOOL_NAME", "arguments": {...}}</tool_call>. '
                    'To finish, use name "submit_answer" and arguments {"answer": <your task answer>}',
}
# Tool-call syntax the model's chat template renders and the model emits. "hermes" (Qwen:
# <tool_call>{json}</tool_call>) is the default; "mistral" (tekken v13, e.g. Devstral Small 2:
# [TOOL_CALLS]name[ARGS]{json}, one marker per call, no call ids) is selected per model config.
TOOL_CALL_FORMATS = ("hermes", "mistral")
# Each format's markers must be single tokens of the model's tokenizer (checked at engine boot).
TOOL_CALL_MARKERS = dict(hermes=("<tool_call>", "</tool_call>"), mistral=("[TOOL_CALLS]", "[ARGS]"))
# Mistral markers are control tokens; feedback text must never spell them, or the rendered
# user message would carry control tokens the model did not emit.
MISTRAL_FEEDBACK_HINTS = {
    "no tool call": "text alone is not acted on; respond with a tool call. "
                    'To finish, call submit_answer with arguments {"answer": <your task answer>}',
    "tool call without an arguments object": "give each call its tool name followed by one JSON arguments object",
}
FEEDBACK_HINTS_BY_FORMAT = dict(hermes=FEEDBACK_HINTS, mistral=MISTRAL_FEEDBACK_HINTS)
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
    repaired: str = ""             # accepted deviation from the strict format (chat-tools-v2 and v3 only)


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
    return _decision(calls, content, repaired)


def _decision(calls, content, repaired=""):
    """Submit/ordinary-call rules shared by every tool-call syntax."""
    if any(name == SUBMIT for name, _ in calls):
        if len(calls) != 1:
            return Decision("malformed", reason="submit_answer mixed with other tool calls", content=content)
        arguments = calls[0][1]
        if set(arguments) != {"answer"}:
            return Decision("malformed", reason="submit_answer takes exactly {answer}", content=content)
        return Decision("answer", answer=arguments["answer"], content=content, repaired=repaired)
    return Decision("tool_calls", calls=tuple(calls), content=content, repaired=repaired)


_MISTRAL_CALL = "[TOOL_CALLS]"
_MISTRAL_ARGS = "[ARGS]"


def parse_mistral_response(text, max_calls=MAX_CALLS_PER_TURN, *, accept_missing_args_marker=False):
    """Parse a Mistral tekken-v13 response: optional text, then one or more
    [TOOL_CALLS]name[ARGS]{json} calls (Devstral Small 2 chat template and mistral-common
    InstructTokenizerV13). Never guesses: anything else after the first marker is malformed.

    accept_missing_args_marker (chat-tools-v3) also reads a segment with no [ARGS] marker as
    name{json}: the name runs to the first "{" and the rest must be one JSON object, under the
    same name and JSON rules. A segment with two or more [ARGS] markers stays malformed.

    The response ends at the end-of-sequence token, so the last call's JSON runs to the end of
    the text. Malformed and no-action turns keep the whole response as visible content: the
    Mistral chat template rejects an assistant message with neither content nor tool calls.
    """
    if not isinstance(text, str):
        return Decision("malformed", reason="response text missing")
    start = text.find(_MISTRAL_CALL)
    if start < 0:
        if _MISTRAL_ARGS in text:
            return Decision("malformed", reason="arguments marker outside a tool call", content=text.strip())
        return Decision("no_action", reason="no tool call", content=text.strip())
    content = text[:start].strip()
    if _MISTRAL_ARGS in content:
        return Decision("malformed", reason="arguments marker outside a tool call", content=text.strip())
    segments = text[start + len(_MISTRAL_CALL):].split(_MISTRAL_CALL)
    if len(segments) > max_calls:
        return Decision("malformed", reason=f"more than {max_calls} tool calls", content=text.strip())
    calls, repaired = [], ""
    for segment in segments:
        parts = segment.split(_MISTRAL_ARGS)
        if len(parts) == 1 and accept_missing_args_marker and "{" in segment:
            brace = segment.index("{")
            parts = [segment[:brace], segment[brace:]]
            repaired = "tool call without [ARGS] marker accepted"
        if len(parts) != 2:
            return Decision("malformed", reason="tool call without an arguments object", content=text.strip())
        name = parts[0].strip()
        if not name or any(c.isspace() for c in name) or "[" in name or "{" in name:
            return Decision("malformed", reason="tool call name missing or invalid", content=text.strip())
        try:
            arguments = strict_loads(parts[1].strip())
        except ValueError as exc:
            return Decision("malformed", reason=f"invalid tool call JSON: {exc}", content=text.strip())
        if not isinstance(arguments, dict):
            return Decision("malformed", reason="tool call arguments must be a JSON object", content=text.strip())
        calls.append((name, arguments))
    decision = _decision(calls, content, repaired)
    if decision.kind == "malformed":
        return Decision("malformed", reason=decision.reason, content=text.strip())
    return decision


def parse_tool_response(text, tool_call_format="hermes", *, accept_unclosed_final=False,
                        accept_missing_args_marker=False):
    """Dispatch on the model's tool-call syntax. hermes is parse_response unchanged."""
    if tool_call_format == "hermes":
        return parse_response(text, accept_unclosed_final=accept_unclosed_final)
    if tool_call_format == "mistral":
        # No closing tag exists in this syntax, so there is nothing for v2 to repair.
        return parse_mistral_response(text, accept_missing_args_marker=accept_missing_args_marker)
    raise ValueError(f"unknown tool-call format {tool_call_format!r}")


@dataclass
class Conversation:
    """Model-visible history. Deterministic given identical tool semantics."""
    goal: str
    tools: list
    max_turns: int
    protocol: str = PROTOCOL_VERSION
    messages: list = field(default_factory=list)
    turns_used: int = 0
    tool_call_format: str = "hermes"

    def __post_init__(self):
        if self.tool_call_format not in TOOL_CALL_FORMATS:
            raise ValueError(f"unknown tool-call format {self.tool_call_format!r}")
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
        if self.tool_call_format == "mistral" and not message["content"] and "tool_calls" not in message:
            # The Mistral template raises on an empty assistant message; the turn still counts and
            # the feedback that follows is merged with the preceding message by the same template.
            return
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
        hints = self.protocol in (PROTOCOL_V2, PROTOCOL_V3)
        hint = FEEDBACK_HINTS_BY_FORMAT[self.tool_call_format].get(reason) if hints else None
        error = f"{reason}: {hint}. Call a tool or submit_answer." if hint else f"{reason}. Call a tool or submit_answer."
        self.messages.append(dict(role="user", content=json.dumps(
            dict(status="error", error=error, turns_remaining=self.remaining()), sort_keys=True)))


def to_native_text(decision, tool_call_format="hermes"):
    """Legacy scripted decision {tool_calls|answer} -> model-format text (fixtures only)."""
    if "answer" in decision:
        calls = [dict(name=SUBMIT, arguments=dict(answer=decision["answer"]))]
    else:
        calls = [dict(name=c["tool"], arguments=c.get("args", {})) for c in decision["tool_calls"]]
    if tool_call_format == "mistral":
        return "".join(f"{_MISTRAL_CALL}{c['name']}{_MISTRAL_ARGS}{json.dumps(c['arguments'])}" for c in calls)
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
