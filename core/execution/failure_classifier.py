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
VALID_FAILURE_TYPES = frozenset({
    "rate_limit", "timeout", "api_error", "context_overflow",
    "tool_error", "wrong_answer", "crashed", "other",
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
        if "RateLimit" in exc_type or "rate_limit" in str(exc).lower() \
                or "429" in str(exc) or "too many requests" in str(exc).lower():
            return "rate_limit"

        # Context length exceeded — varies across providers
        if "ContextLength" in exc_type or "context_length" in str(exc).lower() \
                or "exceed context window" in str(exc).lower() \
                or "context window" in str(exc).lower():
            return "context_overflow"

        # Connection / API infrastructure failures
        if exc_type in ("ConnectionError", "ConnectError", "APIError"):
            return "api_error"

        # Catch-all for any unrecognised exception type
        logger.debug("FailureClassifier: unrecognised exception %s — classifying as crashed", exc_type)
        return "crashed"

    def _classify_result(self, run_result: dict) -> str:
        """
        4-layer structured failure detection.
        Layer 1: explicit tool_error flag.
        Layer 2: execution.error_type — set by agentic structured detection.
        Layer 3: execution.error_message — set by linear harness or exception path.
        Layer 4: scan step results for error strings — fallback for legacy results.
        Conservative default: unknown errors → api_error not None.
        """
        if run_result.get("tool_error"):
            return "tool_error"
 
        exec_dict = run_result.get("execution", {}) or {}
 
        # Layer 2 — structured error_type from agentic.py (most reliable)
        error_type = exec_dict.get("error_type")
        if error_type and error_type in VALID_FAILURE_TYPES:
            return error_type
 
        # Layer 3 — error_message from linear harness or exception path
        error_msg = str(exec_dict.get("error_message", "") or "").lower()
        if error_msg:
            if "429" in error_msg or "too many requests" in error_msg or "rate_limit" in error_msg:
                return "rate_limit"
            if "context window" in error_msg or "exceed context" in error_msg or "context_length" in error_msg:
                return "context_overflow"
            if "timeout" in error_msg:
                return "timeout"
            if "connection" in error_msg or "api error" in error_msg:
                return "api_error"
 
        # Layer 4 — scan step results for error strings (legacy/fallback)
        steps = run_result.get("step_results", []) or []
        for step in steps:
            content = str(step.get("result", "") or "").lower()
            # Specific checks BEFORE generic "error:" — order matters
            if "429" in content or "too many requests" in content or "rate_limit" in content:
                return "rate_limit"
            if "context window" in content or "context_length" in content or "exceed context" in content:
                return "context_overflow"
            if "timeout" in content or "timed out" in content:
                return "timeout"
            if "tool_error" in content or "tool failed" in content:
                return "tool_error"
            if content.startswith("error:"):
                return "api_error"
 
        # Quality score fallback
        # Quality score fallback
        score = run_result.get("quality_score")
        if score is not None and score < 0.3:
            return "wrong_answer"

        # Status fallback — execution failed but no specific error type detected.
        # Returns api_error rather than None so goal_attempt.failure_type is always
        # populated for failed outcomes. Never returns None for failed executions.
        exec_dict = run_result.get("execution", {}) or {}
        if exec_dict.get("status") in ("failure", "failed", "partial_failure"):
            return "api_error"

        return None
 

