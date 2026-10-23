"""Stock engines declare no expert controls; the lifecycle then issues no expert RPCs."""
import json

import pytest

from studies.energy_diagnosis.moe.backend import CONTROLS, ProcessBackend, expected_controls
from studies.energy_diagnosis.moe.control import Lifecycle, Policy
from studies.energy_diagnosis.moe import stock_engine


class StockBackend:
    """Implements only the engine-neutral protocol: reset, drain, end."""

    def __init__(self):
        self.calls = []
        self.reset_evidence = {}
        self.process = None

    def capabilities(self):
        return dict(controls=[], expert_controls=False, engine="llamacpp", mode="native")

    def reset_goal_state(self):
        self.calls.append("reset")

    def drain_owned_work(self, timeout):
        self.calls.append("drain")
        return {"inflight_bytes": 0}

    def end_goal(self):
        self.calls.append("end")

    def __getattr__(self, name):
        if name in {"drain_demands", "drain_transfers", "cancel_pending_preparation", "snapshot_experts",
                    "prepare_experts"}:
            raise AssertionError(f"expert RPC {name} issued to a stock engine")
        raise AttributeError(name)


def test_expected_controls_by_engine():
    assert expected_controls({"engine": "vllm"}) == []
    assert expected_controls({"engine": "llamacpp"}) == []
    assert expected_controls({}) == list(CONTROLS)
    b = ProcessBackend({"engine": "llamacpp"}, python="python", mode="native", log_path="/tmp/x.log")
    caps = b.capabilities()
    assert caps["controls"] == [] and caps["expert_controls"] is False and caps["engine"] == "llamacpp"


def test_demand_lifecycle_on_stock_engine_issues_no_expert_rpcs():
    backend = StockBackend()
    life = Lifecycle(backend, Policy("demand", 0))
    life.begin_goal("g1", task_id="t")
    assert life.expert_controls is False
    life.before_model("r1")
    life.after_model()
    life.plan_pause()
    token = life.start_pause()
    life.end_pause(token)
    life.settle_work()
    life.end_goal()
    assert backend.calls == ["reset", "drain", "drain", "end"]
    assert [e["event"] for e in life.events][-2:] == ["preparation_drained", "goal_end"]


@pytest.mark.parametrize("policy", ["fixed", "history", "builtin"])
def test_preparing_policies_are_refused_on_stock_engines(policy):
    life = Lifecycle(StockBackend(), Policy(policy, 0 if policy == "builtin" else 128))
    with pytest.raises(RuntimeError, match="lacks required expert controls"):
        life.begin_goal("g1")


def test_undeclared_missing_controls_are_refused():
    class Silent(StockBackend):
        def capabilities(self):
            return dict(controls=[], mode="native")

    with pytest.raises(RuntimeError, match="lacks required expert controls"):
        Lifecycle(Silent(), Policy("demand", 0)).begin_goal("g1")


def test_preflight_verification(tmp_path):
    weights = tmp_path / "w.bin"
    weights.write_bytes(b"x" * 1000)
    record = tmp_path / "preflight.json"
    stock_engine.preflight([weights], record)
    ok = stock_engine.verify([weights], dict(checkpoint_verification="preflight", checkpoint_preflight=str(record)))
    assert ok["mode"] == "preflight" and ok["files"] == [str(weights.resolve())]
    weights.write_bytes(b"x" * 999)
    with pytest.raises(ValueError, match="changed size"):
        stock_engine.verify([weights], dict(checkpoint_verification="preflight", checkpoint_preflight=str(record)))
    other = tmp_path / "other.bin"
    other.write_bytes(b"y")
    with pytest.raises(ValueError, match="not covered"):
        stock_engine.verify([other], dict(checkpoint_verification="preflight", checkpoint_preflight=str(record)))
    assert json.loads(record.read_text())["version"] == "stock-engine-preflight-v1"


def test_numa_placement_reports_own_process():
    import os
    import sys

    info = stock_engine.numa_placement(os.getpid())
    if sys.platform != "linux":
        assert "error" in info
    else:
        assert info["resident_mib_by_node"] and info["cpus_allowed"]
