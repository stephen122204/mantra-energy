"""
failure_injector.py — Deterministic failure injection for controlled experiments.

Three modes with clean separation:

    deterministic_validation:
        Exact N failures at evenly-spaced draw positions.
        No probabilistic draws. Same schedule every run.
        Used for CI, regression tests, architecture validation.
        Rates ignored — only min_failures and total draws matter.
        Summary reports: planned_failures, realized_failures, schedule.

    deterministic_stress:
        Every attempt fails. Used to verify full retry exhaustion path.
        Rates ignored.

    statistical:
        SHA-256-seeded Bernoulli draws against configured rates.
        Requires many repetitions for meaningful confidence intervals.
        Summary reports: configured_rate, achieved_rate, draws.

Seeding (statistical mode only):
    SHA-256(scenario_id, rep_num, attempt_num, kind:tool_name)
    scenario_id can be shared across providers for fair comparisons.
    Stable across Python versions, platforms, process restarts.

Audit log:
    Every injection decision recorded with full context.
    get_audit_log() returns list of dicts for paper results section.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

INJECTION_ALLOWED_TYPES = frozenset({"failure_injection", "retry_study"})

MODE_DETERMINISTIC_VALIDATION = "deterministic_validation"
MODE_CONTROLLED_RETRY         = "controlled_retry"
MODE_DETERMINISTIC_STRESS     = "deterministic_stress"
MODE_STATISTICAL              = "statistical"
VALID_MODES = frozenset({
    MODE_DETERMINISTIC_VALIDATION,
    MODE_CONTROLLED_RETRY,
    MODE_DETERMINISTIC_STRESS,
    MODE_STATISTICAL,
})

KIND_TIMEOUT      = "timeout"
KIND_TOOL_FAILURE = "tool_failure"


@dataclass
class InjectionEvent:
    """Single injection audit record."""
    exp_id:      int
    scenario_id: str
    rep_num:     int
    attempt_num: int
    kind:        str
    tool_name:   Optional[str]
    injected:    bool
    seed_value:  float      # 0.0 for deterministic modes
    mode:        str
    draw_index:  int        # position in draw sequence


def _stable_random(scenario_id: str, rep_num: int, attempt_num: int, key: str) -> float:
    """
    SHA-256-based stable float in [0, 1).
    Used only in statistical mode.
    scenario_id enables shared fault schedule across providers.
    """
    raw = f"{scenario_id}:{rep_num}:{attempt_num}:{key}".encode()
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big") / (2 ** 64)


def _evenly_spaced_slots(total_draws: int, n_failures: int) -> frozenset:
    """
    Choose exactly n_failures evenly-spaced positions from total_draws slots.
    Uses integer arithmetic — no floating point, fully deterministic.
    Example: total=6, n=2 → slots {1, 4} (1-indexed, evenly spaced)
    """
    if n_failures <= 0:
        return frozenset()
    if n_failures >= total_draws:
        return frozenset(range(1, total_draws + 1))
    # Evenly distribute n_failures across total_draws
    slots = set()
    for i in range(n_failures):
        # Spread: slot = round((i + 0.5) * total_draws / n_failures)
        slot = round((i + 0.5) * total_draws / n_failures)
        slots.add(max(1, min(total_draws, slot)))
    return frozenset(slots)


class FailureInjector:
    """
    Injects controlled failures into experiment runs for energy accounting.

    Workload-aware:
        Pure LLM tasks  → timeout injection (post-harness result modification)
        Tool graph tasks → tool_failure injection (inside _dispatch_tool)
    """

    def __init__(
        self,
        config: dict,
        experiment_type: str,
        exp_id: int = 0,
    ):
        self._enabled         = config.get("enabled", False)
        self._experiment_type = experiment_type
        self._exp_id          = exp_id
        self._mode            = config.get("mode", MODE_STATISTICAL)
        self._tool_rate       = float(config.get("tool_failure_rate", 0.0))
        self._timeout_rate    = float(config.get("timeout_rate", 0.0))
        self._target_injection_pct = float(config.get("target_injection_pct", 0.0))
        self._min_failures         = int(config.get("min_failures", 1))
        self._target_goal_pct      = float(config.get("target_goal_pct", 0.0))
        self._per_goal_attempts    = int(config.get("per_goal_attempts", 1))
        self._selected_goals: set  = set()
        self._scenario_id     = config.get("scenario_id", None)

        # Estimated total draws — set by caller before experiment starts
        # Used by deterministic_validation to pre-compute injection slots.
        # Default 10 — overridden by set_total_draws() if known.
        self._total_draws_estimate = int(config.get("total_draws_estimate", 10))

        # Per-kind draw counters and injection counts
        self._draw_index: Dict[str, int] = {KIND_TIMEOUT: 0, KIND_TOOL_FAILURE: 0}
        self._counts:     Dict[str, int] = {KIND_TIMEOUT: 0, KIND_TOOL_FAILURE: 0}

        # Pre-computed injection slots for deterministic_validation mode
        # Computed once in set_exp_id() after total draws are known
        self._slots: Dict[str, frozenset] = {}
        self._initialised = False

        # Audit log
        self._audit_log: List[InjectionEvent] = []

        if self._mode not in VALID_MODES:
            logger.warning(
                "FailureInjector: unknown mode=%r — defaulting to statistical",
                self._mode,
            )
            self._mode = MODE_STATISTICAL

        if self._enabled and experiment_type not in INJECTION_ALLOWED_TYPES:
            logger.warning(
                "FailureInjector: experiment_type=%r not in allowed set — disabling",
                experiment_type,
            )
            self._enabled = False

    def set_exp_id(self, exp_id: int, total_draws: int = None) -> None:
        """
        Set exp_id after experiment created in DB.
        Computes deterministic injection slots if mode=deterministic_validation.

        Args:
            exp_id:       DB experiment ID.
            total_draws:  Expected total injection draw calls this experiment.
                          Used to compute evenly-spaced slots.
                          If None, uses total_draws_estimate from config.
        """
        self._exp_id = exp_id
        if self._scenario_id is None:
            self._scenario_id = str(exp_id)
        if self._initialised:
            return
        self._initialised = True
        n = total_draws or self._total_draws_estimate
        if self._target_injection_pct > 0.0 and n > 0:
            self._min_failures = max(1, round(self._target_injection_pct * n))
            logger.info("FailureInjector: target_injection_pct=%.0f%% x n=%d -> min_failures=%d",
                self._target_injection_pct * 100, n, self._min_failures)

        if self._mode == MODE_DETERMINISTIC_VALIDATION:
            # Pre-compute evenly-spaced failure slots — one set per kind
            # Each kind gets independent slot schedule
            self._slots[KIND_TIMEOUT] = _evenly_spaced_slots(n, self._min_failures)
            self._slots[KIND_TOOL_FAILURE] = _evenly_spaced_slots(n, self._min_failures)
            logger.info(
                "FailureInjector: deterministic_validation exp=%d "
                "total_draws=%d min_failures=%d timeout_slots=%s tool_slots=%s",
                exp_id, n, self._min_failures,
                sorted(self._slots[KIND_TIMEOUT]),
                sorted(self._slots[KIND_TOOL_FAILURE]),
            )
        else:
            logger.info(
                "FailureInjector: %s exp=%d scenario=%s "
                "timeout_rate=%.2f tool_rate=%.2f",
                self._mode, exp_id, self._scenario_id,
                self._timeout_rate, self._tool_rate,
            )

    def is_active(self) -> bool:
        """Returns True only when enabled and experiment_type is in allowed set."""
        return self._enabled

    def maybe_inject_timeout(self, rep_num: int, attempt_num: int) -> bool:
        """
        Decide whether to inject a timeout for this attempt.
        Post-harness — RAPL energy always captured before this is applied.
        """
        if not self._enabled or (
            self._mode == MODE_STATISTICAL and self._timeout_rate <= 0.0
        ):
            return False
        return self._decide(KIND_TIMEOUT, rep_num, attempt_num, tool_name=None)

    def maybe_inject_tool_failure(
        self, tool_name: str, rep_num: int, attempt_num: int
    ) -> bool:
        """
        Decide whether to inject a tool failure for this tool call.
        Called inside _dispatch_tool() after harness has started.
        """
        if not self._enabled or (
            self._mode == MODE_STATISTICAL and self._tool_rate <= 0.0
        ):
            return False
        return self._decide(KIND_TOOL_FAILURE, rep_num, attempt_num, tool_name=tool_name)

    def injection_summary(self) -> dict:
        """
        Return mode-appropriate summary for paper results section.
        Deterministic modes report schedule. Statistical reports rates.
        """
        total_injected = sum(self._counts.values())
        base = {
            "exp_id":         self._exp_id,
            "scenario_id":    self._scenario_id,
            "mode":           self._mode,
            "total_injected": total_injected,
            "by_kind":        {},
        }

        for kind in (KIND_TIMEOUT, KIND_TOOL_FAILURE):
            draws    = self._draw_index[kind]
            injected = self._counts[kind]
            if self._mode == MODE_DETERMINISTIC_VALIDATION:
                base["by_kind"][kind] = {
                    "planned_failures":  self._min_failures,
                    "realized_failures": injected,
                    "schedule":          sorted(self._slots.get(kind, [])),
                    "draws":             draws,
                }
            elif self._mode == MODE_DETERMINISTIC_STRESS:
                base["by_kind"][kind] = {
                    "realized_failures": injected,
                    "draws":             draws,
                    "stress_mode":       True,
                }
            elif self._mode == MODE_CONTROLLED_RETRY:
                base["by_kind"][kind] = {
                    "target_goal_pct":   self._target_goal_pct,
                    "per_goal_attempts": self._per_goal_attempts,
                    "selected_goals":    sorted(self._selected_goals),
                    "realized_failures": injected,
                    "draws":             draws,
                }
            else:
                rate = self._timeout_rate if kind == KIND_TIMEOUT else self._tool_rate
                base["by_kind"][kind] = {
                    "configured_rate": rate,
                    "achieved_rate":   round(injected / draws, 4) if draws else 0.0,
                    "injected":        injected,
                    "draws":           draws,
                }
        if self._mode == MODE_DETERMINISTIC_VALIDATION:
            base["min_failures"] = self._min_failures
            base["min_met"]      = total_injected >= self._min_failures
        return base

    def get_audit_log(self) -> List[dict]:
        """Full injection audit trail for paper results section."""
        return [
            {
                "exp_id":      e.exp_id,
                "scenario_id": e.scenario_id,
                "rep_num":     e.rep_num,
                "attempt_num": e.attempt_num,
                "kind":        e.kind,
                "tool_name":   e.tool_name,
                "injected":    e.injected,
                "seed_value":  round(e.seed_value, 6),
                "mode":        e.mode,
                "draw_index":  e.draw_index,
            }
            for e in self._audit_log
        ]

    def _decide(
        self,
        kind: str,
        rep_num: int,
        attempt_num: int,
        tool_name: Optional[str],
    ) -> bool:
        """Core injection decision — delegates to mode-specific logic."""
        if self._exp_id <= 0 and self._scenario_id is None:
            raise ValueError(
                "FailureInjector._decide: exp_id not set. "
                "Call set_exp_id() after experiment is created in DB."
            )

        self._draw_index[kind] = self._draw_index.get(kind, 0) + 1
        draw_idx = self._draw_index[kind]

        if self._mode == MODE_DETERMINISTIC_STRESS:
            inject     = True
            seed_value = 0.0

        elif self._mode == MODE_DETERMINISTIC_VALIDATION:
            # Inject only at pre-computed evenly-spaced slots — no randomness
            slots      = self._slots.get(kind, frozenset())
            inject     = draw_idx in slots
            seed_value = 0.0
        elif self._mode == MODE_CONTROLLED_RETRY:
            n_reps     = self._total_draws_estimate or 30
            n_selected = max(1, round(self._target_goal_pct * n_reps))
            if rep_num not in self._selected_goals:
                slot = round((rep_num - 0.5) * n_selected / n_reps)
                if slot < n_selected:
                    self._selected_goals.add(rep_num)
            inject     = (rep_num in self._selected_goals) and (attempt_num <= self._per_goal_attempts)
            seed_value = 0.0
        else:
            # Statistical mode — SHA-256-seeded Bernoulli draw
            key        = f"{kind}:{tool_name or 'none'}"
            scenario   = self._scenario_id or str(self._exp_id)
            seed_value = _stable_random(scenario, rep_num, attempt_num, key)
            rate       = self._timeout_rate if kind == KIND_TIMEOUT else self._tool_rate
            inject     = seed_value < rate

        self._audit_log.append(InjectionEvent(
            exp_id=self._exp_id,
            scenario_id=self._scenario_id or str(self._exp_id),
            rep_num=rep_num,
            attempt_num=attempt_num,
            kind=kind,
            tool_name=tool_name,
            injected=inject,
            seed_value=seed_value,
            mode=self._mode,
            draw_index=draw_idx,
        ))

        if inject:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            logger.info(
                "FailureInjector: %s injected exp=%d rep=%d attempt=%d "
                "tool=%r draw=%d mode=%s",
                kind, self._exp_id, rep_num, attempt_num,
                tool_name, draw_idx, self._mode,
            )

        return inject
