"""
failure_injector.py — Deterministic failure injection for controlled experiments.

Only active when experiment config has failure_injection.enabled = True
AND experiment_type is in the allowed set. Guard prevents accidental activation
in production baseline runs.

Determinism: uses (run_id + attempt_number) as PRNG seed so the same
experiment replay always injects the same failures — essential for reproducibility.
Injected failures are flagged with 'INJECTED:' prefix in error_message so
downstream analysis can separate real vs injected failure rates.
"""

import logging
import random

logger = logging.getLogger(__name__)

# Only these experiment types may activate failure injection.
# Prevents accidental injection in normal or overhead_study runs.
INJECTION_ALLOWED_TYPES = frozenset({"failure_injection", "retry_study"})


class FailureInjector:
    """
    Injects deterministic tool failures and timeouts into experiment runs.

    Each maybe_inject_* call uses a fresh seeded Random instance so injection
    decisions are independent of call order and thread state.
    """

    def __init__(self, config: dict, experiment_type: str):
        """
        Args:
            config:          failure_injection section from experiment config YAML.
                             Expected keys: enabled, tool_failure_rate, timeout_rate.
            experiment_type: Guards against accidental activation outside allowed types.
        """
        self._enabled         = config.get("enabled", False)
        self._experiment_type = experiment_type
        self._tool_rate       = float(config.get("tool_failure_rate", 0.0))
        self._timeout_rate    = float(config.get("timeout_rate", 0.0))

        if self._enabled and experiment_type not in INJECTION_ALLOWED_TYPES:
            # Log and disable rather than raise — keeps experiment alive with a warning
            logger.warning(
                "FailureInjector: injection requested for experiment_type=%r "
                "which is not in allowed set %s — disabling injection",
                experiment_type, INJECTION_ALLOWED_TYPES,
            )
            self._enabled = False

    def is_active(self) -> bool:
        """
        Returns True only when enabled and experiment_type is in allowed set.
        Callers may skip both maybe_inject calls when False for efficiency.
        """
        return self._enabled

    def maybe_inject_tool_failure(
        self,
        tool_name: str,
        run_id: int,
        attempt_number: int,
    ) -> bool:
        """
        Decide whether to inject a tool failure for this call.

        Deterministic: same (tool_name, run_id, attempt_number) always gives
        the same result so experiment replays are reproducible.

        Args:
            tool_name:      Name of the tool being called.
            run_id:         Current run id — part of seed.
            attempt_number: Current attempt number — part of seed.

        Returns:
            True if caller should simulate a tool failure.
        """
        if not self._enabled or self._tool_rate <= 0.0:
            return False

        # Seed incorporates tool_name hash so different tools get independent draws
        seed = hash((tool_name, run_id, attempt_number)) & 0xFFFFFFFF
        rng  = random.Random(seed)
        inject = rng.random() < self._tool_rate

        if inject:
            logger.info(
                "FailureInjector: injecting tool failure for tool=%r run=%d attempt=%d",
                tool_name, run_id, attempt_number,
            )
        return inject

    def maybe_inject_timeout(
        self,
        run_id: int,
        attempt_number: int,
    ) -> bool:
        """
        Decide whether to inject a timeout for this attempt.

        Args:
            run_id:         Current run id — part of seed.
            attempt_number: Current attempt number — part of seed.

        Returns:
            True if caller should simulate a timeout.
        """
        if not self._enabled or self._timeout_rate <= 0.0:
            return False

        seed = hash(("timeout", run_id, attempt_number)) & 0xFFFFFFFF
        rng  = random.Random(seed)
        inject = rng.random() < self._timeout_rate

        if inject:
            logger.info(
                "FailureInjector: injecting timeout for run=%d attempt=%d",
                run_id, attempt_number,
            )
        return inject
