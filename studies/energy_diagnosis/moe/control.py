"""The same tool-pause lifecycle is used by native and deterministic test devices."""
from __future__ import annotations

from contextlib import nullcontext
from collections import Counter
from dataclasses import asdict, dataclass
import math
import random
import time

# Pause policies choose experts at each tool pause. static prepares once before
# the first model call. demand and builtin (MoE-Infinity's own in-generation
# prefetcher, configured in the backend) prepare nothing at pauses.
PAUSE_POLICIES = frozenset({"history", "fixed", "bounded", "random", "future"})
AHEAD_POLICIES = frozenset({"static"})
POLICY_NAMES = PAUSE_POLICIES | AHEAD_POLICIES | {"demand", "builtin"}
# Selection that reads information unavailable to a deployable policy.
DIAGNOSTIC_POLICIES = frozenset({"future"})


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
    seed: int = 0
    # sha256 of the static profile or future trace passed to Lifecycle(data=).
    data_sha256: str | None = None
    # during: admit when the tool body starts (overlap). after: diagnostic
    # control that admits the same batch once the tool returns and waits for
    # it before the model resumes, charging all preparation to the task.
    timing: str = "during"

    def __post_init__(self):
        if self.name not in POLICY_NAMES:
            raise ValueError("unknown expert policy")
        if self.timing not in {"during", "after"} or (self.timing == "after" and self.name not in PAUSE_POLICIES):
            raise ValueError("timing is during, or after for pause policies only")
        if (self.name in {"static", "future"}) != (self.data_sha256 is not None):
            raise ValueError("static and future policies, and only they, require data")
        if type(self.byte_budget) is not int or not 0 <= self.byte_budget < 2**63:
            raise ValueError("byte budget must fit nonnegative int64")
        if type(self.max_experts) is not int or self.max_experts < 1:
            raise ValueError("max_experts must be positive")
        for x in (self.bytes_per_second, self.expected_pause_seconds):
            if x is not None and (
                isinstance(x, bool) or not math.isfinite(x) or x <= 0
            ):
                raise ValueError("estimates must be finite and positive")

    def select(self, snapshot, history, *, pause_index=0, task_id=None, data=None):
        if self.name not in PAUSE_POLICIES:
            return [], f"{self.name}_no_pause_preparation"
        if self.name == "future":
            # Diagnostic only: experts the next model call used in a reference
            # run of the same task (trace from build_future_trace).
            nxt = ((data or {}).get("tasks", {}).get(task_id) or {}).get(str(pause_index))
            if nxt is None:
                raise ValueError("future trace missing for task/pause; diagnostic is unavailable")
            tokens = {(layer, expert): n for layer, expert, n in nxt}
            candidates = [e for e in snapshot if e.key in tokens and not e.device.startswith("cuda")]
            candidates.sort(key=lambda e: (-tokens[e.key], e.layer, e.expert))
            return self._fill(candidates, self.byte_budget), "future_trace_diagnostic"
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
        if self.name == "random":
            # Same candidate pool and budget as fixed; only the ranking differs.
            random.Random(f"{self.seed}:{pause_index}").shuffle(candidates)
            return self._fill(candidates, budget), "random_matched_budget"
        limit = self.max_experts if self.name == "history" else None
        return self._fill(candidates, budget, limit), "ranked_history"

    def select_ahead(self, snapshot, data):
        """static: the development-profile ranking, loaded before the first call."""
        if self.name not in AHEAD_POLICIES:
            return [], f"{self.name}_no_ahead_preparation"
        rank = {(layer, expert): i for i, (layer, expert, _) in enumerate(data["experts"])}
        candidates = [e for e in snapshot if e.key in rank and not e.device.startswith("cuda")]
        candidates.sort(key=lambda e: rank[e.key])
        return self._fill(candidates, self.byte_budget), "static_profile"

    @staticmethod
    def _fill(candidates, budget, limit=None):
        selected, used = [], 0
        for e in candidates:
            if limit is not None and len(selected) >= limit:
                break
            if e.nbytes <= 0:
                raise RuntimeError("backend returned invalid expert size")
            if used + e.nbytes <= budget:
                selected.append(e)
                used += e.nbytes
        return selected


@dataclass(frozen=True)
class _PreparationPlan:
    generation: int
    goal_id: str
    request_id: str
    pause_index: int
    policy: Policy
    experts: tuple[Expert, ...]
    reason: str


class Lifecycle:
    """Only one owned goal and one pause at a time; callbacks cannot cross goals."""

    def __init__(self, backend, policy: Policy, *, data=None, clock=time.monotonic_ns):
        self.backend, self.policy, self.clock = backend, policy, clock
        self.data = data
        self.task_id = None
        self._preparing_ahead = False
        self._ahead_prepared = False
        self._deferred = None
        self.events, self.history = [], Counter()
        self.goal = self.pause = None
        self.generation = 0
        self.pending = {}
        self.request_id = ""
        self.pause_index = 0
        self._pause_plan = None
        self.work_settled = False

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

    def begin_goal(self, goal_id, task_id=None):
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
        self.task_id = task_id
        self.request_id = ""
        self.generation += 1
        self.events, self.history, self.pending = [], Counter(), {}
        self.pause_index = 0
        self._ahead_prepared = False
        self._deferred = None
        self._pause_plan = None
        self.work_settled = False
        self.emit(
            "goal_start",
            policy=asdict(self.policy),
            capabilities=caps,
            reset=self.backend.reset_evidence,
            startup_window=dict(start_ns=startup_start, end_ns=startup_end),
        )
        # Every arm starts each goal from dispatcher accounting reconciled with placement, so the
        # first model call does not run under the constructor's provisional budget.
        self._record_reconciliation(self.backend.drain_owned_work(10), when="goal_start")

    def before_model(self, request_id):
        if self.goal is None or self.pause is not None or self._pause_plan is not None or self.work_settled:
            raise RuntimeError("generation outside active goal or before pause drain")
        self.request_id = request_id
        self.emit("model_start")

    def after_model(self):
        if self.work_settled:
            raise RuntimeError("model observation after work was settled")
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
                    first_use_phase=event.get("phase"),
                    first_use_tokens=event.get("tokens"),
                    resident_on_first_dispatch=event.get(
                        "first_dispatch_resident", event.get("resident_at_dispatch")
                    ),
                )
        self._collect_transfers()
        self.emit("model_end")

    def plan_pause(self):
        """Select before launching tools; this issues no transfer admission."""
        if self.goal is None or self.pause is not None or self._pause_plan is not None or self.work_settled:
            raise RuntimeError("invalid preparation planning state")
        upcoming = f"{self.goal}:pause:{self.pause_index + 1}"
        self.emit("preparation_planning_start", upcoming_pause_id=upcoming)
        stages = {}
        if self.policy.name not in PAUSE_POLICIES:
            selected, reason = [], "demand_only" if self.policy.name == "demand" else f"{self.policy.name}_no_pause_preparation"
        else:
            snapshot_start = self.clock()
            snapshot = self.backend.snapshot_experts()
            snapshot_end = self.clock()
            selected, reason = self.policy.select(
                snapshot, self.history, pause_index=self.pause_index + 1,
                task_id=self.task_id, data=self.data,
            )
            selection_end = self.clock()
            stages = dict(
                snapshot_rpc=dict(start_ns=snapshot_start, end_ns=snapshot_end),
                policy_select=dict(start_ns=snapshot_end, end_ns=selection_end),
            )
        self._pause_plan = _PreparationPlan(
            self.generation, self.goal, self.request_id, self.pause_index + 1,
            self.policy, tuple(selected), reason,
        )
        self.emit(
            "preparation_planning_end", upcoming_pause_id=upcoming,
            selected_experts=len(selected), reason=reason,
            stages=stages,
        )

    def start_pause(self):
        plan = self._pause_plan
        if self.goal is None or self.pause is not None or plan is None or self.work_settled:
            raise RuntimeError("invalid pause start")
        if (
            plan.generation != self.generation or plan.goal_id != self.goal
            or plan.request_id != self.request_id
            or plan.pause_index != self.pause_index + 1 or plan.policy != self.policy
        ):
            raise RuntimeError("stale preparation plan")
        self._pause_plan = None  # A plan is consumed at most once, including failure.
        self.pause_index += 1
        self.pause = f"{self.goal}:pause:{self.pause_index}"
        self.emit("tool_pause_start")
        if self.policy.name not in PAUSE_POLICIES:
            # Do not enumerate thousands of experts or issue an empty RPC for
            # the no-preparation control. Goal-end ownership checks still run.
            self.emit("preparation_skipped", reason=plan.reason)
            return self.generation, self.pause
        selected, reason = plan.experts, plan.reason
        if self.policy.timing == "after":
            self._deferred = (selected, reason)
            self.emit("preparation_deferred", selected_experts=len(selected), reason=reason)
            return self.generation, self.pause
        self._admit(selected, reason)
        return self.generation, self.pause

    def _admit(self, selected, reason, event="preparation_admitted"):
        self.emit("preparation_dispatch_start")
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
            event,
            selected=[asdict(e) for e in selected],
            ack=ack,
            reason=reason,
        )

    def prepare_ahead(self, timeout_seconds=60):
        """static: prepare the profile's experts once, before the first model call.

        Blocks until issued transfers finish; the cost is charged to the goal.
        """
        if self.policy.name not in AHEAD_POLICIES:
            return
        if self.goal is None or self.pause is not None or self._pause_plan is not None or self.request_id or self.work_settled or self._ahead_prepared:
            raise RuntimeError("ahead preparation only between goal start and the first model call")
        self._ahead_prepared = True
        self.emit("ahead_preparation_start")
        snapshot = self.backend.snapshot_experts()
        selected, reason = self.policy.select_ahead(snapshot, self.data)
        ack = self.backend.prepare_experts(selected, self.generation, self.policy.byte_budget)
        selected_nodes = {e.node: e for e in selected}
        accepted = ack["accepted_nodes"]
        if len(set(accepted)) != len(accepted) or not set(accepted) <= selected_nodes.keys():
            raise RuntimeError("backend accepted unknown or duplicate experts")
        if ack["accepted_bytes"] != sum(selected_nodes[n].nbytes for n in accepted):
            raise RuntimeError("backend byte acknowledgment does not reconcile")
        self.emit("ahead_preparation_admitted", selected=[asdict(e) for e in selected], ack=ack, reason=reason)
        self._record_reconciliation(self.backend.drain_owned_work(timeout_seconds))
        self._preparing_ahead = True
        try:
            self._collect_transfers()
        finally:
            self._preparing_ahead = False
        self.emit("ahead_preparation_end")

    def end_pause(self, token, timeout_seconds=10):
        if token != (self.generation, self.pause) or self.pause is None:
            raise RuntimeError("stale pause callback")
        self.emit("tools_finished")
        deferred, self._deferred = self._deferred, None
        if deferred is not None:
            # after-timing control: nothing overlaps the tool; the whole batch
            # is admitted and completed before the model resumes.
            self._admit(*deferred, event="deferred_preparation_admitted")
        cleanup = self.backend.cleanup_scope(timeout_seconds) if hasattr(self.backend, "cleanup_scope") else nullcontext()
        with cleanup:
            cancelled = 0 if deferred is not None else self.backend.cancel_pending_preparation(self.generation)
            # Cancellation is queued-only. Issued work must settle before resume.
            self._record_reconciliation(self.backend.drain_owned_work(timeout_seconds))
            self._collect_transfers()
        self.emit("model_resume", cancelled_bytes=cancelled)
        self.pause = None

    def _record_reconciliation(self, drained, when="resume"):
        rec = (drained or {}).get("cache_reconciliation") if isinstance(drained, dict) else None
        if rec is not None:
            self.emit("cache_reconciled", when=when, **rec)

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
            row = dict(row, prepared_in="ahead" if self._preparing_ahead else self.pause)
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

    def settle_work(self, timeout_seconds=10):
        """Confirm task-owned device work is idle without releasing the model."""
        if self.goal is None:
            raise RuntimeError("no owned goal to settle")
        if self.work_settled:
            return
        if self._pause_plan is not None:
            self.emit("preparation_plan_discarded", reason="no_tool_body_admission")
            self._pause_plan = None
        cleanup = self.backend.cleanup_scope(timeout_seconds) if hasattr(self.backend, "cleanup_scope") else nullcontext()
        with cleanup:
            self.backend.cancel_pending_preparation(self.generation)
            self._record_reconciliation(self.backend.drain_owned_work(timeout_seconds), when="goal_end")
            self._collect_transfers()
        for key, row in self.pending.items():
            self.emit(
                "prepared_not_used_by_goal_end", expert=list(key), prepared=row
            )
        self.work_settled = True
        self.emit("preparation_drained")

    def end_goal(self, timeout_seconds=10):
        if self.goal is None:
            return
        try:
            self.settle_work(timeout_seconds)
        finally:
            # Backend ownership ends even on drain/cancel failure; supervisor reaps it.
            self.backend.end_goal()
            self.emit("goal_end")
            self.goal = self.pause = None
