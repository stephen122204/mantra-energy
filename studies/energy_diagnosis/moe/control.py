"""The same tool-pause lifecycle is used by native and deterministic test devices."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import math
import time


@dataclass(frozen=True)
class Expert:
    layer: int
    expert: int
    tensor: int
    node: int
    nbytes: int
    device: str

    @property
    def key(self):
        return (self.layer, self.expert)


@dataclass(frozen=True)
class Policy:
    name: str = "demand"
    byte_budget: int = 0
    max_experts: int = 8
    # Optional previously calibrated throughput. Never guessed from future pauses.
    bytes_per_second: float | None = None
    expected_pause_seconds: float | None = None

    def __post_init__(self):
        if self.name not in {"demand", "history", "fixed", "bounded"}:
            raise ValueError("unknown expert policy")
        if type(self.byte_budget) is not int or not 0 <= self.byte_budget < 2**63:
            raise ValueError("byte budget must fit nonnegative int64")
        if type(self.max_experts) is not int or self.max_experts < 1:
            raise ValueError("max_experts must be positive")
        for x in (self.bytes_per_second, self.expected_pause_seconds):
            if x is not None and (
                isinstance(x, bool) or not math.isfinite(x) or x <= 0
            ):
                raise ValueError("estimates must be finite and positive")

    def select(self, snapshot, history):
        if self.name == "demand":
            return [], "demand_only"
        budget = self.byte_budget
        if self.name == "bounded":
            if self.bytes_per_second is None or self.expected_pause_seconds is None:
                return [], "missing_calibration_demand_only"
            budget = min(
                budget, int(self.bytes_per_second * self.expected_pause_seconds)
            )
        candidates = [
            e
            for e in snapshot
            if history[e.key] > 0 and not e.device.startswith("cuda")
        ]
        candidates.sort(key=lambda e: (-history[e.key], e.layer, e.expert))
        selected, used = [], 0
        for e in candidates:
            if self.name == "history" and len(selected) >= self.max_experts:
                break
            if e.nbytes <= 0:
                raise RuntimeError("backend returned invalid expert size")
            if used + e.nbytes <= budget:
                selected.append(e)
                used += e.nbytes
        return selected, "ranked_history"


class Lifecycle:
    """Only one owned goal and one pause at a time; callbacks cannot cross goals."""

    def __init__(self, backend, policy: Policy, *, clock=time.monotonic_ns):
        self.backend, self.policy, self.clock = backend, policy, clock
        self.events, self.history = [], Counter()
        self.goal = self.pause = None
        self.generation = 0
        self.pending = {}
        self.request_id = ""
        self.pause_index = 0

    def emit(self, kind, **fields):
        self.events.append(
            dict(
                event=kind,
                goal_id=self.goal,
                request_id=self.request_id,
                pause_id=self.pause,
                generation=self.generation,
                monotonic_ns=self.clock(),
                **fields,
            )
        )

    def begin_goal(self, goal_id):
        if self.goal is not None:
            raise RuntimeError("previous goal is still owned")
        caps = self.backend.capabilities()
        required = {
            "acknowledged_preparation",
            "completed_transfers",
            "cancel_queued",
            "drain",
            "expert_snapshot",
        }
        if not required <= set(caps.get("controls", [])):
            raise RuntimeError("backend lacks required expert controls")
        startup_start = self.clock()
        self.backend.reset_goal_state()
        startup_end = self.clock()
        self.goal, self.pause = goal_id, None
        self.generation += 1
        self.events, self.history, self.pending = [], Counter(), {}
        self.pause_index = 0
        self.emit(
            "goal_start",
            policy=asdict(self.policy),
            capabilities=caps,
            reset=self.backend.reset_evidence,
            startup_window=dict(start_ns=startup_start, end_ns=startup_end),
        )

    def before_model(self, request_id):
        if self.goal is None or self.pause is not None:
            raise RuntimeError("generation outside active goal or before pause drain")
        self.request_id = request_id
        self.emit("model_start")

    def after_model(self):
        for event in self.backend.drain_demands():
            key = (event["layer"], event["expert"])
            self.history[key] += event.get("tokens", 1)
            self.emit("expert_demand", observation=event)
            if key in self.pending:
                prior = self.pending.pop(key)
                self.emit(
                    "prepared_expert_requested",
                    expert=list(key),
                    prepared=prior,
                    resident_on_first_dispatch=event.get(
                        "first_dispatch_resident", event.get("resident_at_dispatch")
                    ),
                )
        self._collect_transfers()
        self.emit("model_end")

    def start_pause(self):
        if self.goal is None or self.pause is not None:
            raise RuntimeError("invalid pause start")
        self.pause_index += 1
        self.pause = f"{self.goal}:pause:{self.pause_index}"
        self.emit("tool_pause_start")
        if self.policy.name == "demand":
            # Do not enumerate thousands of experts or issue an empty RPC for
            # the no-preparation control. Goal-end ownership checks still run.
            self.emit("preparation_skipped", reason="demand_only")
            return self.generation, self.pause
        snapshot = self.backend.snapshot_experts()
        selected, reason = self.policy.select(snapshot, self.history)
        ack = self.backend.prepare_experts(
            selected, self.generation, self.policy.byte_budget
        )
        selected_nodes = {e.node: e for e in selected}
        accepted = ack["accepted_nodes"]
        if (
            len(set(accepted)) != len(accepted)
            or not set(accepted) <= selected_nodes.keys()
        ):
            raise RuntimeError("backend accepted unknown or duplicate experts")
        expected_bytes = sum(selected_nodes[n].nbytes for n in accepted)
        if (
            ack["accepted_bytes"] != expected_bytes
            or ack["inflight_bytes"] > self.policy.byte_budget
        ):
            raise RuntimeError("backend byte acknowledgment does not reconcile")
        self.emit(
            "preparation_admitted",
            selected=[asdict(e) for e in selected],
            ack=ack,
            reason=reason,
        )
        return self.generation, self.pause

    def end_pause(self, token, timeout_seconds=10):
        if token != (self.generation, self.pause) or self.pause is None:
            raise RuntimeError("stale pause callback")
        self.emit("tools_finished")
        cancelled = self.backend.cancel_pending_preparation(self.generation)
        # Cancellation is queued-only. Already-issued work must finish before resume.
        self.backend.drain_owned_work(timeout_seconds)
        self._collect_transfers()
        self.emit("model_resume", cancelled_bytes=cancelled)
        self.pause = None

    def _collect_transfers(self):
        records, dropped = self.backend.drain_transfers()
        if dropped:
            raise RuntimeError(f"backend dropped {dropped} expert records")
        for row in records:
            if row["generation"] != self.generation:
                raise RuntimeError("stale transfer from another goal")
            if row.get("kind") == "placement":
                self.emit("expert_placement", placement=row)
                continue
            if not 0 <= row["transferred_bytes"] <= row["bytes"]:
                raise RuntimeError("invalid transfer byte count")
            self.emit("expert_transfer", transfer=row)
            if row["outcome"] == "completed":
                key = (row["layer"], row["expert"])
                # A later preparation replacing unused state remains visible.
                if key in self.pending:
                    self.emit(
                        "prepared_not_used_before_reprepare", prepared=self.pending[key]
                    )
                self.pending[key] = row
            elif row["outcome"] in {"failed", "not_transferred"}:
                raise RuntimeError("native preparation failed")

    def end_goal(self, timeout_seconds=10):
        if self.goal is None:
            return
        try:
            self.backend.cancel_pending_preparation(self.generation)
            self.backend.drain_owned_work(timeout_seconds)
            self._collect_transfers()
            for key, row in self.pending.items():
                self.emit(
                    "prepared_not_used_by_goal_end", expert=list(key), prepared=row
                )
            self.emit("preparation_drained")
        finally:
            # Backend ownership ends even on drain/cancel failure; supervisor reaps it.
            self.backend.end_goal()
            self.emit("goal_end")
            self.goal = self.pause = None
