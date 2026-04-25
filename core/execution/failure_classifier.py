"""
failure_classifier.py — Maps exceptions and run outcomes to canonical failure types.

Called by RetryCoordinator after each failed attempt to determine:
  1. What type of failure occurred
  2. Whether it is retryable under the active policy

Canonical types must stay in sync with goal_attempt.failure_type column.
Never raises — always returns a valid string from FAILURE_TYPES.
"""

import logging

logger = logging.getLogger(__name__)

# Canonical failure type set — mirrors goal_attempt.failure_type values.
# Any new type here requires a DB migration to add it to the column docs.
FAILURE_TYPES = frozenset({
    "timeout",
    "api_error",
    "tool_error",
    "wrong_answer",
    "context_overflow",
    "rate_limit",
    "crashed",
})

# Quality score below this threshold is classified as wrong_answer.
# Tied to output_quality_normalization_v1 — bump version if threshold changes.
WRONG_ANSWER_THRESHOLD = 0.5


class FailureClassifier:
    """
    Maps exceptions and harness result dicts to canonical failure type strings.

    Priority order: exception type > run_result fields > 'crashed' fallback.
    This ordering ensures infrastructure failures are never masked by quality checks.
    """

    def classify(
        self,
        exception: Exception = None,
        run_result: dict = None,
    ) -> str:
        """
        Classify a failure into one canonical type.

        Args:
            exception:  Exception raised during execution, if any.
            run_result: Harness result dict, used when no exception was raised
                        but the run produced a bad outcome (e.g. wrong answer).

        Returns:
            Canonical failure type string from FAILURE_TYPES.
        """
        if exception is not None:
            return self._classify_exception(exception)

        if run_result is not None:
            return self._classify_result(run_result)

        # Both None — caller has no information; treat as crashed
        logger.warning("FailureClassifier: called with no exception and no result")
        return "crashed"

    def _classify_exception(self, exc: Exception) -> str:
        """
        Map exception type to canonical failure string.
        Checks class name strings to avoid hard imports of provider SDKs.
        """
        exc_type  = type(exc).__name__
        exc_bases = {t.__name__ for t in type(exc).__mro__}

        # Timeout family — covers stdlib, concurrent.futures, httpx
        if exc_type in ("TimeoutError", "TimeoutExpired") or "Timeout" in exc_type:
            return "timeout"

        # Rate limit — provider SDKs use RateLimitError or 429-based names
        if "RateLimit" in exc_type or "rate_limit" in str(exc).lower():
            return "rate_limit"

        # Context length exceeded — varies across providers
        if "ContextLength" in exc_type or "context_length" in str(exc).lower():
            return "context_overflow"

        # Connection / API infrastructure failures
        if exc_type in ("ConnectionError", "ConnectError", "APIError"):
            return "api_error"

        # Catch-all for any unrecognised exception type
        logger.debug("FailureClassifier: unrecognised exception %s — classifying as crashed", exc_type)
        return "crashed"

    def _classify_result(self, run_result: dict) -> str:
        """
        Classify from harness result dict when no exception was raised.
        Checks explicit tool_error flag first, then quality score.
        """
        # Explicit tool failure flag set by harness tool execution block
        if run_result.get("tool_error"):
            return "tool_error"

        # Quality score below threshold means model produced a wrong answer
        score = run_result.get("quality_score")
        if score is not None and score < WRONG_ANSWER_THRESHOLD:
            return "wrong_answer"

        # Result dict present but no classifiable signal — treat as crashed
        logger.debug("FailureClassifier: result has no classifiable failure signal")
        return "crashed"
