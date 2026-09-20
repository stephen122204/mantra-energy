"""Snapshot wire compatibility, live placement and planning-stage boundaries."""
from dataclasses import asdict
import json

import pytest

from studies.energy_diagnosis.moe.control import Expert, Lifecycle, Policy
from studies.energy_diagnosis.moe.native_backend import NativeDevice


def test_scalar_snapshot_preserves_wire_format_and_rereads_live_placement():
    class Native:
        inflight = 0
        placement = "cpu"

        def __init__(self):
            self.reads = []

        def get_inflight_prefetch_bytes(self):
            return self.inflight

        def alems_expert_info(self, tensor):
            self.reads.append(tensor)
            return (tensor + 70000, 64 + tensor % 3, self.placement)

    device = NativeDevice.__new__(NativeDevice)
    device.native = Native()
    device.mapping = {(l, e): 1 + 128*l + e for l in reversed(range(48)) for e in reversed(range(128))}
    expected = [asdict(Expert(l, e, t, t+70000, 64+t%3, "cpu"))
                for (l,e),t in sorted(device.mapping.items())]
    first = device.snapshot(None)
    assert json.dumps(first) == json.dumps(expected)  # Preserve field/order protocol.
    assert device.native.reads == list(range(1, 6145))
    device.native.placement = "cuda:0"
    device.native.reads.clear()
    second = device.snapshot(None)
    assert all(row["device"] == "cuda:0" for row in second)
    assert all(row["device"] == "cpu" for row in first)
    assert len(device.native.reads) == 6144  # Never substitute cached residency.
    device.native.inflight = 64
    with pytest.raises(RuntimeError, match="settled"):
        device.snapshot(None)
    assert len(device.native.reads) == 6144


def test_planning_separates_snapshot_rpc_from_unchanged_selection():
    class Backend:
        def snapshot_experts(self):
            return [Expert(0, 1, 10, 11, 64, "cpu"), Expert(0, 2, 20, 22, 64, "cuda:0")]

    clock = iter(range(10, 100, 10)).__next__
    lifecycle = Lifecycle(Backend(), Policy("fixed", 64), clock=clock)
    lifecycle.goal = "g"
    lifecycle.history.update({(0, 1): 2, (0, 2): 3})
    lifecycle.plan_pause()
    begin, end = lifecycle.events
    assert begin["monotonic_ns"] == 10 and end["monotonic_ns"] == 50
    assert end["stages"] == {
        "snapshot_rpc": {"start_ns": 20, "end_ns": 30},
        "policy_select": {"start_ns": 30, "end_ns": 40},
    }
    assert end["selected_experts"] == 1 and end["reason"] == "ranked_history"
    assert lifecycle._pause_plan.experts == (Expert(0, 1, 10, 11, 64, "cpu"),)


def test_demand_does_not_invent_snapshot_or_selection_stages():
    lifecycle = Lifecycle(object(), Policy("demand"), clock=lambda: 0)
    lifecycle.goal = "g"
    lifecycle.plan_pause()
    assert lifecycle.events[-1]["stages"] == {}
    assert lifecycle.events[-1]["monotonic_ns"] == 0
