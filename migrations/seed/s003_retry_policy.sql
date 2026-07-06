-- s003_retry_policy.sql
-- Retry policy definitions. Universal, all platforms.
-- Source of truth: GN100 live DB, 2026-07-05.
-- See SPEC_SEED_DATA_COMPLETE.md for classification rules.

INSERT OR IGNORE INTO retry_policy
    (policy_name, max_retries, retry_on_timeout, retry_on_tool_error,
     retry_on_api_error, retry_on_wrong_answer, backoff_seconds) VALUES
('aggressive', 5, 1, 1, 1, 0, 1.0),
('default',    1, 1, 1, 0, 0, 0.0),
('no_retry',   0, 0, 0, 0, 0, 0.0);
