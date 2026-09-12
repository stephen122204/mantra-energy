"""Cross-component checks through the actual CLI, HTTP adapter, tools and ledger."""

import json
from pathlib import Path
import subprocess
import sys

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
