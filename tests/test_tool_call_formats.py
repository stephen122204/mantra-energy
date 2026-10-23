"""Per-model tool-call syntax: hermes (Qwen, default) and mistral (tekken v13, e.g. Devstral Small 2)."""
import json

import pytest

from studies.energy_diagnosis.agent_protocol import (
    SUBMIT, TOOL_CALL_MARKERS, Conversation, function_tools, parse_mistral_response, parse_response,
    parse_tool_response, to_native_text,
)
from studies.energy_diagnosis.moe import run as campaign
from studies.energy_diagnosis.moe.llamacpp_backend import check_tool_call_markers


def mcall(name, arguments):
    # What the Devstral chat template renders for an assistant tool call (arguments|tojson).
    return f"[TOOL_CALLS]{name}[ARGS]{json.dumps(arguments)}"


def test_mistral_calls_answer_and_visible_text():
    d = parse_mistral_response("Checking schema." + mcall("sql", {"action": "schema"})
                               + mcall("sql", {"action": "query", "sql": "SELECT 1"}))
    assert d.kind == "tool_calls" and d.content == "Checking schema."
    assert d.calls == (("sql", {"action": "schema"}), ("sql", {"action": "query", "sql": "SELECT 1"}))
    d = parse_mistral_response(mcall(SUBMIT, {"answer": {"count": 3}}))
    assert d.kind == "answer" and d.answer == {"count": 3} and d.content == ""
    # Compact JSON and whitespace around the name are the same call.
    assert parse_mistral_response('[TOOL_CALLS] sql [ARGS]{"action":"schema"}\n').calls == (("sql", {"action": "schema"}),)
    d = parse_mistral_response("The answer is 3.")
    assert d.kind == "no_action" and d.reason == "no tool call" and d.content == "The answer is 3."
    # Hermes tags are plain text for a Mistral model: not a call.
    assert parse_mistral_response('<tool_call>{"name": "sql", "arguments": {}}</tool_call>').kind == "no_action"


@pytest.mark.parametrize("text,reason", [
    ('[TOOL_CALLS]sql{"action": "schema"}', "without an arguments object"),
    ('[TOOL_CALLS]sql[ARGS]{}[ARGS]{}', "without an arguments object"),
    ('[TOOL_CALLS][ARGS]{"action": "schema"}', "name missing"),
    ('[TOOL_CALLS]sql[CALL_ID]abc123def[ARGS]{"action": "schema"}', "name missing or invalid"),
    ('[TOOL_CALLS]sql[ARGS]{"action": "schema"', "invalid tool call JSON"),
    ('[TOOL_CALLS]sql[ARGS]{"a": 1} trailing', "invalid tool call JSON"),
    ('[TOOL_CALLS]sql[ARGS]{"a": 1, "a": 2}', "duplicate"),
    ('[TOOL_CALLS]sql[ARGS]{"x": NaN}', "non-finite"),
    ('[TOOL_CALLS]sql[ARGS]["schema"]', "must be a JSON object"),
    ('sql[ARGS]{"action": "schema"}', "arguments marker outside"),
    ('x[ARGS]y' + mcall("sql", {}), "arguments marker outside"),
    (mcall(SUBMIT, {"answer": {}}) + mcall("sql", {"action": "schema"}), "mixed"),
    (mcall(SUBMIT, {"answer": {}, "extra": 1}), "exactly"),
    ("".join(mcall("sql", {"action": "schema"}) for _ in range(9)), "more than"),
])
def test_ambiguous_mistral_responses_are_malformed_and_keep_the_text(text, reason):
    d = parse_mistral_response(text)
    assert d.kind == "malformed" and reason in d.reason
    # Never empty: the Mistral template rejects an assistant message with no content and no calls.
    assert d.content == text.strip()


def test_hermes_dispatch_is_parse_response_unchanged():
    samples = ['<tool_call>\n{"name": "sql", "arguments": {}}\n</tool_call>',
               '<tool_call>\n{"name": "submit_answer", "arguments": {"answer": 2}}', "plain text",
               mcall("sql", {})]
    for text in samples:
        for v2 in (False, True):
            assert parse_tool_response(text, accept_unclosed_final=v2) == parse_response(text, accept_unclosed_final=v2)
            assert parse_tool_response(text, "hermes", accept_unclosed_final=v2) == parse_response(text, accept_unclosed_final=v2)
    assert parse_tool_response(mcall("sql", {}), "mistral").kind == "tool_calls"
    with pytest.raises(ValueError):
        parse_tool_response("x", "chatml")


def test_fixture_text_round_trips_in_both_formats():
    for decision in ({"tool_calls": [dict(id="a", tool="sql", args={"q": 1}), dict(id="b", tool="etl", args={})]},
                     {"answer": {"done": True}}):
        hermes, mistral = parse_response(to_native_text(decision)), parse_mistral_response(to_native_text(decision, "mistral"))
        assert (hermes.kind, hermes.calls, hermes.answer) == (mistral.kind, mistral.calls, mistral.answer)


def test_mistral_feedback_never_spells_control_tokens():
    tools = function_tools({})
    for protocol in ("chat-tools-v1", "chat-tools-v2"):
        c = Conversation("g", tools, 5, protocol=protocol, tool_call_format="mistral")
        for text in ("The answer is 3.", '[TOOL_CALLS]sql{"a": 1}', '[TOOL_CALLS]sql[ARGS]{"a": 1', "x[ARGS]{}"):
            d = parse_mistral_response(text)
            c.record_turn(d)
            c.feedback(d.reason)
            error = json.loads(c.messages[-1]["content"])["error"]
            assert "[TOOL_CALLS]" not in error and "[ARGS]" not in error and "<tool_call>" not in error
    v2 = Conversation("g", tools, 5, protocol="chat-tools-v2", tool_call_format="mistral")
    v2.feedback("no tool call")
    assert "submit_answer" in json.loads(v2.messages[-1]["content"])["error"]
    v1 = Conversation("g", tools, 5, tool_call_format="mistral")
    v1.feedback("no tool call")
    assert json.loads(v1.messages[-1]["content"])["error"] == "no tool call. Call a tool or submit_answer."
    with pytest.raises(ValueError):
        Conversation("g", tools, 5, tool_call_format="chatml")


def test_empty_mistral_turn_counts_but_is_not_rendered():
    tools = function_tools({})
    hermes, mistral = Conversation("g", tools, 5), Conversation("g", tools, 5, tool_call_format="mistral")
    for c, parse in ((hermes, parse_response), (mistral, parse_mistral_response)):
        c.record_turn(parse(""))
        assert c.turns_used == 1 and c.remaining() == 4
    assert [m["role"] for m in hermes.messages] == ["system", "user", "assistant"]   # unchanged hermes history
    assert [m["role"] for m in mistral.messages] == ["system", "user"]
    mistral.record_turn(parse_mistral_response(mcall("sql", {"a": 1})), ["t00c0"])
    assert mistral.messages[-1]["tool_calls"][0]["function"] == dict(name="sql", arguments={"a": 1})


class _Tokenizer:
    def __init__(self, single):
        self.single = set(single)

    def encode(self, text, add_special_tokens=True):
        return [1] if text in self.single else [1, 2, 3]


def test_boot_rejects_a_tool_call_format_the_tokenizer_does_not_have():
    qwen, devstral = _Tokenizer(TOOL_CALL_MARKERS["hermes"]), _Tokenizer(TOOL_CALL_MARKERS["mistral"])
    assert check_tool_call_markers(qwen, "hermes") == ("<tool_call>", "</tool_call>")
    assert check_tool_call_markers(devstral, "mistral") == ("[TOOL_CALLS]", "[ARGS]")
    for tokenizer, fmt in ((devstral, "hermes"), (qwen, "mistral")):
        with pytest.raises(ValueError, match="does not match this model"):
            check_tool_call_markers(tokenizer, fmt)
    with pytest.raises(ValueError, match="unknown"):
        check_tool_call_markers(qwen, "chatml")


def _fixture_run(tmp_path, config, *extra):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([dict(kind="business", rows=128, seed=7)]))
    config_path = tmp_path / "model.json"
    config_path.write_text(json.dumps(config))
    output = tmp_path / "run"
    campaign.main(["--mode", "fixture", "--config", str(config_path), "--output", str(output), "--task-pack", str(spec),
                   "--policies", "demand", "--max-runs", "1", "--deadline", "60", *extra])
    goal = next((output / "goals").glob("*/agent-trace.json"))
    return json.loads(goal.read_text()), json.loads(goal.with_name("model-calls.json").read_text())


@pytest.mark.parametrize("protocol", ["chat-tools-v1", "chat-tools-v2"])
def test_mistral_model_config_selects_the_parser_end_to_end(tmp_path, protocol):
    trace, calls = _fixture_run(tmp_path, dict(fixture_case="success", tool_call_format="mistral"),
                                "--agent-protocol", protocol)
    assert trace["outcome"] == "passed"
    assert calls[0]["adapter"]["content"].startswith("[TOOL_CALLS]")
    assert {t["kind"] for t in trace["turns"][:-1]} == {"tool_calls"} and trace["turns"][-1]["kind"] == "answer"


def test_misconfigured_format_is_rejected_before_any_goal(tmp_path):
    with pytest.raises(ValueError, match="tool_call_format"):
        _fixture_run(tmp_path, dict(fixture_case="success", tool_call_format="chatml"))
    assert not (tmp_path / "run" / "goals").exists()
    # A Mistral-format model parsed as hermes never makes a call: why the engine boot check exists.
    assert parse_response(to_native_text({"answer": 1}, "mistral")).kind == "no_action"


def test_weights_manifest_download_for_another_model(tmp_path, monkeypatch):
    """prepare download: Qwen defaults unchanged; --model/--revision/--pattern pin another repository."""
    import hashlib
    import sys
    import types
    from studies.energy_diagnosis.moe import prepare

    seen = []

    def snapshot_download(repo, revision, local_dir, allow_patterns):
        seen.append((repo, revision, allow_patterns))
        (tmp_path / "m" / "tokenizer.json").write_text("{}")

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=snapshot_download))
    rev = "55c5b41e98c2dbd21b0c8afffc540dcfc9eb5128"
    monkeypatch.setattr(sys, "argv", ["prepare", "download", str(tmp_path / "m"), "--model", "mistralai/Devstral-Small-2-24B-Instruct-2512",
                                      "--revision", rev, "--pattern", "tokenizer.json", "--pattern", "chat_template.jinja"])
    prepare.main()
    manifest = json.loads((tmp_path / "m" / "alems-weights.json").read_text())
    assert manifest == dict(model="mistralai/Devstral-Small-2-24B-Instruct-2512", revision=rev,
                            files={"tokenizer.json": hashlib.sha256(b"{}").hexdigest()})
    assert seen[-1] == ("mistralai/Devstral-Small-2-24B-Instruct-2512", rev, ["tokenizer.json", "chat_template.jinja"])
    monkeypatch.setattr(sys, "argv", ["prepare", "download", str(tmp_path / "q")])
    (tmp_path / "m").mkdir(exist_ok=True)
    prepare.main()
    assert seen[-1] == (prepare.MODEL, prepare.REVISION, ["*.json", "*.safetensors", "*.jinja", "*.txt"])
    for argv in (["download", "x", "--model", "a/b"], ["download", "x", "--model", "a/b", "--revision", "main"],
                 ["build", "x", "--pattern", "*.json"]):
        monkeypatch.setattr(sys, "argv", ["prepare", *argv])
        with pytest.raises(SystemExit):
            prepare.main()
