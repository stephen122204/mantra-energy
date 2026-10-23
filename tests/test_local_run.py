"""Cross-component checks through the actual CLI, HTTP adapter, tools and ledger."""

import json
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest
from studies.energy_diagnosis import local_run

ROOT = Path(__file__).resolve().parents[1]


def command(output, *args):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "studies.energy_diagnosis.local_run",
            "--mode",
            "fixture",
            "--output",
            str(output),
            *args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    return json.loads(result.stdout)


def test_all_pilot_settings_and_resume(tmp_path):
    output = tmp_path / "pilot"
    first = command(output, "--settings", "C00,C01,C10,C11", "--max-runs", "12")
    assert first["executed"] == 12  # repo fixtures only declare 1-worker eligibility
    assert first["validation"]["counts"]["terminal"] == 12
    assert first["validation"]["errors"] == []
    attempts = [
        json.loads(line)
        for line in (output / "exports" / "attempts.jsonl").read_text().splitlines()
    ]
    assert len(attempts) == 12
    # Durable artifacts include actual model calls, computed tool output and raw counters.
    paths = list((output / "goals").glob("*/model-calls.json"))
    assert len(paths) == 12
    for path in paths:
        calls = json.loads(path.read_text())
        assert len(calls) == 2
        assert all(c["response"]["status"] == "completed" for c in calls)
        assert "expected" not in json.loads(calls[0]["prompt"])
        assert (
            json.loads(path.with_name("record.json").read_text())["verifier"]["outcome"]
            == "pass"
        )
    again = command(output, "--settings", "C00,C01,C10,C11", "--max-runs", "12")
    assert again["executed"] == 0
    assert again["validation"]["counts"]["attempts"] == 12


def test_wrong_answer_and_model_failure_retained(tmp_path):
    for case in ("wrong_answer", "model_failure"):
        output = tmp_path / case
        report = command(output, "--fixture-case", case)
        assert report["validation"]["counts"]["attempts"] == 1
        record = json.loads(next((output / "goals").glob("*/record.json")).read_text())
        assert record["simulated"] is True
        assert record["verifier"]["outcome"] == (
            "fail" if case == "wrong_answer" else "unavailable"
        )
        assert record["measurements"]
        assert all(m["energy_j"] is not None for m in record["measurements"])
        assert record["execution_status"] == (
            "completed" if case == "wrong_answer" else "crashed"
        )
        assert len(list((output / "goals").glob("*/measurement.json"))) == 1


def test_integrated_timeout_and_missing_telemetry(tmp_path):
    output = tmp_path / "timeout"
    command(output, "--fixture-case", "tool_timeout", "--deadline", "2")
    record = json.loads(next((output / "goals").glob("*/record.json")).read_text())
    assert record["execution_status"] == "timed_out"
    assert record["verifier"]["outcome"] == "unavailable"
    assert record["measurements"]
    output = tmp_path / "missing"
    command(output, "--fixture-case", "missing_telemetry")
    record = json.loads(next((output / "goals").glob("*/record.json")).read_text())
    assert record["verifier"]["outcome"] == "pass"
    domains = {m["domain_id"]: m for m in record["measurements"]}
    assert domains["GPU_FIXTURE"]["energy_j"] is None
    assert domains["GPU_FIXTURE"]["status"] == "unavailable"
    assert domains["CPU_FIXTURE"]["status"] == "valid"


@pytest.mark.parametrize("preserved_attempt", [1, 2])
def test_preserved_live_failures_replayed_as_scripted_http(tmp_path, monkeypatch, preserved_attempt):
    """Both original responses are identical; replay is simulated model coverage."""
    text = (ROOT / "tests/fixtures/v100_failed_answer.txt").read_text()
    fixture = local_run.FixtureAPI(scripted_responses=[text])
    monkeypatch.setattr(local_run, "FixtureAPI", lambda case: fixture)
    output = tmp_path / f"replay-{preserved_attempt}"
    local_run.main(["--mode", "fixture", "--task", "data-units-v2",
                    "--output", str(output)])
    goal = next((output / "goals").iterdir())
    record = json.loads((goal / "record.json").read_text())
    assert record["simulated"] is True
    assert record["execution_status"] == "completed"
    assert record["verifier"]["outcome"] == "fail"
    assert record["verifier"]["reason"] == "task identity or evidence mismatch"
    assert json.loads((goal / "answer.json").read_text()) == {
        "total_units": None, "total_revenue": None}
    assert json.loads((goal / "tool-results.json").read_text()) == []
    calls = json.loads((goal / "model-calls.json").read_text())
    assert len(calls) == 1 and calls[0]["response"]["text"] == text
    assert len(fixture.requests) == 1
    # Even correcting only the nesting cannot make the null totals pass.
    decision = json.loads(text)
    nested = {**decision["answer"], "task_id": decision["task_id"], "evidence": decision["evidence"]}
    task = next(t for t in local_run.load_pilot_tasks() if t.task_id == "data-units-v2")
    assert local_run.verify_pilot(task, nested)["reason"] == "malformed answer"
    report = json.loads((output / "exports/campaign-validation.json").read_text())
    assert report["valid"] and not report["observations"][0]["analysis_eligible"]


def test_scripted_inspection_then_answer_keeps_real_tool_evidence(tmp_path):
    """Scripted model, actual CSV tool/verifier/ledger; no live-model claim."""
    output = tmp_path / "scripted-success"
    command(output, "--task", "data-units-v2")
    goal = next((output / "goals").iterdir())
    calls = json.loads((goal / "model-calls.json").read_text())
    assert len(calls) == 2
    first = json.loads(calls[0]["response"]["text"])
    assert first == {"tool_calls": [{"id": "inspect", "tool": "inspect_asset", "args": {}}]}
    results = json.loads((goal / "tool-results.json").read_text())
    assert len(results) == 1 and results[0]["status"] == "completed"
    assert results[0]["result"] == {"total_units": "10", "total_revenue": "50.00"}
    assert json.loads(calls[1]["prompt"])["tool_results"] == results
    answer = json.loads((goal / "answer.json").read_text())
    assert answer["total_units"] == "10" and answer["total_revenue"] == "50.00"
    assert answer["task_id"] == "data-units-v2"
    assert answer["evidence"] == [json.loads(calls[0]["prompt"])["asset_sha256"]]
    record = json.loads((goal / "record.json").read_text())
    assert record["simulated"] and record["verifier"]["outcome"] == "pass"
    assert [span["kind"] for span in record["spans"]] == ["model", "tool", "model", "verify"]


def test_prompt_defines_task_specific_complete_final_shape():
    for task in local_run.load_pilot_tasks():
        instruction = local_run.legacy_instruction(task)
        sample = instruction.split("complete final shape: ", 1)[1].split(". Replace", 1)[0]
        final = json.loads(sample)
        assert set(final) == {"answer"}
        assert final["answer"]["task_id"] == task.task_id
        assert final["answer"]["evidence"] == [task.asset_sha256]
        fields = {"total_units", "total_revenue"} if task.family == "data" else {"file_count", "checks"}
        assert set(final["answer"]) == fields | {"task_id", "evidence"}
        assert "INSIDE answer" in instruction and "never null" in instruction


@pytest.mark.parametrize("flag,value", [("--ollama-num-thread", "0"), ("--ollama-num-ctx", "-1")])
def test_invalid_ollama_options_rejected_before_execution(tmp_path, flag, value):
    with pytest.raises(SystemExit) as error:
        local_run.main(["--provider", "ollama", flag, value, "--output", str(tmp_path / "unused")])
    assert error.value.code == 2
    assert not (tmp_path / "unused").exists()


def test_ollama_cli_options_reach_live_runner_without_launching_it(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(local_run, "run", lambda args: captured.append(args) or {"valid": True})
    local_run.main(["--mode", "live", "--provider", "ollama", "--ollama-num-thread", "8",
                    "--ollama-num-ctx", "4096", "--ollama-keep-alive", "5m",
                    "--output", str(tmp_path / "unused")])
    assert captured[0].ollama_num_thread == 8
    assert captured[0].ollama_num_ctx == 4096
    assert captured[0].ollama_keep_alive == "5m"
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("mode,provider", [("live", "vllm"), ("fixture", "ollama")])
def test_ollama_options_cannot_be_silently_ignored(mode, provider):
    with pytest.raises(SystemExit) as error:
        local_run.main(["--mode", mode, "--provider", provider, "--ollama-num-thread", "8"])
    assert error.value.code == 2


@pytest.mark.parametrize("family", ["data", "repository"])
def test_staged_scripted_http_transitions_only_after_real_inspection(tmp_path, family):
    """Scripted model/sensors; actual HTTP, local tool, verifier and ledger."""
    task_id = next(t.task_id for t in local_run.load_pilot_tasks() if t.family == family)
    output = tmp_path / "staged"
    command(output, "--task", task_id, "--diagnostic-variant", local_run.STAGED_INSPECTION)
    goal = next((output / "goals").iterdir())
    calls = json.loads((goal / "model-calls.json").read_text())
    assert len(calls) == 2
    initial, final = [json.loads(c["prompt"]) for c in calls]
    assert initial["tool_results"] == []
    assert '"tool_calls"' in initial["instruction"]
    assert '"answer"' not in initial["instruction"]
    assert "<computed" not in initial["instruction"]
    results = json.loads((goal / "tool-results.json").read_text())
    assert len(results) == 1 and results[0]["tool"] == "inspect_asset"
    assert results[0]["status"] == "completed"
    assert final["tool_results"] == results
    assert '"answer"' in final["instruction"] and '"tool_calls"' not in final["instruction"]
    assert "expected" not in initial and "expected" not in final
    assert (goal / "diagnostic-acceptance.json").exists()
    diagnostic = json.loads((goal / "diagnostic-acceptance.json").read_text())
    assert diagnostic["passed"] and diagnostic["simulated"]
    assert diagnostic["inspection_completed"] and diagnostic["provider_bodies_complete"]
    record = json.loads((goal / "record.json").read_text())
    assert record["verifier"]["outcome"] == "pass" and record["simulated"]
    entry = json.loads((output / "exports/attempts.jsonl").read_text())
    refs = [ref for ref in entry["attempt"]["artifacts"] if ref["role"] == "provider-response-body"]
    assert len(refs) == 2
    for ref, call in zip(refs, calls):
        body = (output / ref["path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == ref["sha256"] == call["adapter"]["provider_response"]["sha256"]
        assert len(body) == call["adapter"]["provider_response"]["bytes_received"]
        assert body.endswith(b"data: [DONE]\n\n")
    manifest = json.loads((output / "environment.json").read_text())
    assert manifest["diagnostic_variant"] == local_run.STAGED_INSPECTION
    assert manifest["provider_response_capture"] == "http-entity-bytes-v1"


@pytest.mark.parametrize("outcomes", [[], [dict(tool="inspect_asset", status="failed", result={})],
                                     [dict(tool="other", status="completed", result={})],
                                     [dict(tool="inspect_asset", status="completed", result=None)]])
def test_staged_prompt_does_not_unlock_for_unsuccessful_inspection(outcomes):
    task = local_run.load_pilot_tasks()[0]
    text = local_run.staged_instruction(task, outcomes)
    assert '"tool_calls"' in text and '"answer"' not in text and "<computed" not in text


def test_scripted_failed_inspection_retained_without_next_model_turn(tmp_path, monkeypatch):
    """Scripted failing tool through the real executor; no live model/hardware."""
    class FailingInspection:
        def execute(self, workers=1):
            from studies.energy_diagnosis.workloads.bounded_executor import ToolResultEnvelope
            return ToolResultEnvelope(False, None, "scripted inspection failure")
    monkeypatch.setattr(local_run, "PilotAssetTool", lambda *args: FailingInspection())
    output = tmp_path / "failed-inspection"
    local_run.main(["--mode", "fixture", "--task", "data-units-v2", "--diagnostic-variant",
                    local_run.STAGED_INSPECTION, "--output", str(output)])
    goal = next((output / "goals").iterdir())
    calls = json.loads((goal / "model-calls.json").read_text())
    assert len(calls) == 1
    assert '"answer"' not in json.loads(calls[0]["prompt"])["instruction"]
    results = json.loads((goal / "tool-results.json").read_text())
    assert len(results) == 1 and results[0]["status"] == "failed"
    assert results[0]["error"] == "scripted inspection failure"
    assert json.loads((goal / "answer.json").read_text()) is None
    record = json.loads((goal / "record.json").read_text())
    assert record["execution_status"] == "crashed" and record["verifier"]["outcome"] == "unavailable"
    assert not json.loads((goal / "diagnostic-acceptance.json").read_text())["passed"]


@pytest.mark.parametrize("response_case", ["preserved_zero", "scripted_correct_guess"])
def test_premature_answer_is_not_repaired_or_accepted_as_diagnostic_success(tmp_path, monkeypatch, response_case):
    """A scripted guess can pass arithmetic, but cannot satisfy real inspection."""
    text = (ROOT / "tests/fixtures/v100_zero_answer.txt").read_text()
    if response_case == "scripted_correct_guess":
        value = json.loads(text)
        value["answer"].update(total_units="10", total_revenue="50.00")
        text = json.dumps(value)
    fixture = local_run.FixtureAPI(scripted_responses=[text])
    monkeypatch.setattr(local_run, "FixtureAPI", lambda case: fixture)
    output = tmp_path / response_case
    local_run.main(["--mode", "fixture", "--task", "data-units-v2", "--diagnostic-variant",
                    local_run.STAGED_INSPECTION, "--output", str(output)])
    goal = next((output / "goals").iterdir())
    assert len(fixture.requests) == 1
    assert json.loads((goal / "answer.json").read_text()) == json.loads(text)["answer"]
    assert json.loads((goal / "tool-results.json").read_text()) == []
    assert json.loads((goal / "events.json").read_text()) == []
    calls = json.loads((goal / "model-calls.json").read_text())
    assert calls[0]["response"]["text"] == text
    record = json.loads((goal / "record.json").read_text())
    assert record["execution_status"] == "completed"
    assert record["verifier"]["outcome"] == ("fail" if response_case == "preserved_zero" else "pass")
    diagnostic = json.loads((goal / "diagnostic-acceptance.json").read_text())
    assert not diagnostic["passed"] and not diagnostic["inspection_completed"]
    report = json.loads((output / "exports/campaign-validation.json").read_text())
    assert report["valid"] and not report["observations"][0]["analysis_eligible"]


def test_diagnostic_configuration_changes_preparation_identity_only_when_selected(tmp_path):
    for variant in (None, local_run.STAGED_INSPECTION):
        output = tmp_path / (variant or "legacy")
        command(output, "--task", "data-units-v2", *(["--diagnostic-variant", variant] if variant else []))
        manifest = json.loads((output / "environment.json").read_text())
        if variant:
            assert manifest["preparation_sha256"] != legacy["preparation_sha256"]
            assert manifest["diagnostic_variant"] == variant
        else:
            legacy = manifest
            assert "diagnostic_variant" not in manifest
            goal = next((output / "goals").iterdir())
            assert not list(goal.glob("provider-response-*"))
            assert not (goal / "diagnostic-acceptance.json").exists()
