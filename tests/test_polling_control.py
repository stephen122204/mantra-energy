"""Per-step counter sampling period and telemetry polling (polling-overhead control); no hardware or model."""
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from studies.energy_diagnosis.runtime.node_measurement import FixtureCounterReader, NodeMeasurement
from studies.energy_diagnosis.runtime.measurement import EnvironmentIdentity
from studies.paper2.cohort import pilot
from studies.paper2.cohort.pilot import MAX_SAMPLE_PERIOD_S, measurement_mode

ENVIRONMENT = EnvironmentIdentity("fixture-commit", "fixture-host", "fixture-boot", "fixture-allocation",
                                  "fixture-cpus", ("fixture-gpu",), "simulated")
TEKKEN = os.environ.get("PAPER2_TEKKEN")


@pytest.mark.parametrize("period", [0.1, 20.0])
def test_sampler_waits_the_configured_period(period):
    measured = NodeMeasurement(FixtureCounterReader(), ENVIRONMENT, session_id="fixture", sample_period_s=period)
    measured.stop = Mock(wraps=measured.stop)
    waits = []

    def wait(timeout):
        waits.append(timeout)
        return True  # stop at once

    measured.stop.wait.side_effect = wait
    measured.start_goal()
    measured.finish_goal()
    assert waits == [period]


def test_sampler_rejects_a_non_positive_period():
    with pytest.raises(ValueError):
        NodeMeasurement(FixtureCounterReader(), ENVIRONMENT, sample_period_s=0)


def test_measurement_mode_defaults_plan_and_step_overrides():
    assert measurement_mode({}, {}) == dict(sample_period_s=0.1, telemetry=True)
    plan = dict(sample_period_s=1.0, telemetry=False)
    assert measurement_mode(plan, {}) == dict(sample_period_s=1.0, telemetry=False)
    assert measurement_mode(plan, dict(sample_period_s=20, telemetry=True)) == dict(sample_period_s=20.0, telemetry=True)


@pytest.mark.parametrize("step", [dict(sample_period_s=MAX_SAMPLE_PERIOD_S + 1), dict(sample_period_s=0),
                                  dict(telemetry="no")])
def test_measurement_mode_rejects_gaps_beyond_the_integrator_limit(step):
    with pytest.raises(ValueError):
        measurement_mode({}, dict(step, name="bad"))


def test_driver_rejects_an_invalid_mode_before_anything_runs(tmp_path):
    plan = dict(passes=[dict(blocks={"arm": dict(steps=[{"live": dict(name="ok")},
                                                        {"live": dict(name="sparse", sample_period_s=60)}])})])
    path = tmp_path / "plan.json"; path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="sparse"):
        pilot.main(["--plan", str(path), "--out", str(tmp_path / "out"), "--budget-s", "60",
                    "--cutoff-utc", "2099-01-01T00:00:00Z", "--fixture-server"])
    assert not (tmp_path / "out").exists()


@pytest.mark.skipif(not (TEKKEN and Path(TEKKEN).exists()), reason="PAPER2_TEKKEN not set")
def test_driver_records_each_step_measurement_mode(tmp_path, monkeypatch):
    calls = []

    def cohort(spec, out_root, *, measurement=None, poller=None, **kwargs):
        calls.append((spec.cohort_id, poller))
        return dict(infra_invalid=False, infrastructure_fault=None, drain={"drained": True}, container_cleanup=None,
                    outcomes={"completed": 1}, verified_pass=0)

    monkeypatch.setattr(pilot, "run_cohort", cohort)
    task_id = "business-segments-v2-n64-s7"
    steps = [{"live": dict(name="dense", admission_limit=1, task_ids=[task_id], seed=3, est_s=60)},
             {"live": dict(name="sparse", admission_limit=1, task_ids=[task_id], seed=3, est_s=60,
                           sample_period_s=20, telemetry=False)}]
    plan = dict(gpu_uuid="fixture", allocation="fixture", isolation="fixture", block_seed=1,
                configs=[dict(name="arm", model="/nonexistent/arm", revision="fixture", weight_precision="int4",
                              activation_precision="bf16", max_model_len=32768)],
                blocks={"arm": dict(steps=steps)}, tekken={"arm": TEKKEN},
                task_specs=[dict(kind="business", rows=64, seed=7)],
                limits=dict(max_turns=3, max_tool_calls=10, max_total_output_tokens=2048, max_tokens=256,
                            deadline_s=60, verify_timeout_s=120),
                sampling=dict(mode="sampled", temperature=0.15, top_p=1.0, top_k=-1, min_p=0.0, seed=0),
                load_est_s=1, export_reserve_s=0)
    path = tmp_path / "plan.json"; path.write_text(json.dumps(plan))
    out = tmp_path / "out"
    pilot.main(["--plan", str(path), "--out", str(out), "--budget-s", "3600",
                "--cutoff-utc", "2099-01-01T00:00:00Z", "--fixture-server"])
    events = [json.loads(line) for line in (out / "driver-events.jsonl").read_text().splitlines()]
    modes = {e["step"]: (e["sample_period_s"], e["telemetry"]) for e in events if e["kind"] == "measurement_mode"}
    assert modes == {"arm-dense": (0.1, True), "arm-sparse": (20.0, False)}
    rows = {r["step"]: r["measurement"] for r in json.loads((out / "pilot-results.json").read_text())}
    assert rows == {"arm-dense": dict(sample_period_s=0.1, telemetry=True),
                    "arm-sparse": dict(sample_period_s=20.0, telemetry=False)}
    assert [c[0] for c in calls] == ["arm-dense", "arm-sparse"]
