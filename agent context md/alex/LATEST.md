# Latest published context: alex

[Immutable turn record](turns/20260912T-ed02-executor-failure-accounting.md)

# Turn summary: Alex — 20260912T-ed02-executor-failure-accounting

## Task and current understanding

Address two follow-up correctness findings on ED-02 PR #24: retain Ollama terminal token observations before malformed-content failure, and prevent structured adapter errors from becoming successful executor interactions. Work continued on the existing `alex/ed-02-local-runtime` branch from old head `00769dc41eba0e1f2418028fc9fd1d6ef7238a43`; fetched integration was `8869321859a0c794d1d940c7f5ec4accc0ec7682`.

Inspection confirmed `LinearExecutor._execute_provider` and `AgenticExecutor._call_llm` treated every returned adapter dictionary as successful and only used failure paths for raised exceptions. `_error_result()` itself contained exactly one intended `tokens: {}` key; no duplicate-key defect existed in source.

Alex milestone status: AX1/ED-02 remains hardware-tested and Ready for review with this failure-accounting repair; AX2/AX3 retain separate ED-05 evidence; AX4 remains ED-07/09 integration-dependent; AX5 remains conditional. No ED-05 or ED-07 files changed.

## Ideas and hypotheses

Adapter protocol failures need to remain directly testable as structured results, but executor persistence must reject their error status. A small shared boundary guard can preserve the original diagnostic dictionary on an exception while routing both executor implementations through their existing failure accounting.

## Decisions and rationale

Ollama streamed counts are copied before content type validation. Malformed terminal content still fails; valid provider counts survive only as `observed_tokens`, while final `tokens` remains empty and provenance unknown.

Added a shared `require_adapter_success` boundary used by both executors. Its `AdapterCallError` retains the original result. Linear and agentic failure records now preserve error, partial content, observed tokens, token provenance, phase/timing and network observations. Unknown structured-failure token columns are null rather than measured zero. Successful results remain on their existing paths.

## Changes and artifacts

Commit `c7d087dc3efb445d2079d70619ca21b378f5b9a9` (`Propagate structured adapter failures to executors`) was pushed normally to `origin/alex/ed-02-local-runtime`.

Changed only:

- `core/execution/adapter_result.py`
- `core/execution/adapters/openai_compat.py`
- `core/execution/agentic.py`
- `core/execution/linear.py`
- `tests/test_executor_adapter_failures.py`
- `tests/test_openai_compat_adapter.py`

PR #24 description was updated; it remains Ready and unmerged.

## Tests and evidence

- `python3 -m pytest -q tests/test_openai_compat_adapter.py` — 45 passed.
- `python3 -m pytest -q tests/test_executor_adapter_failures.py` — 4 passed.
- Broader ED-02 set including both suites — 102 passed, 5 subtests passed, one pre-existing `test_db_config` return-value warning.
- `python3 -m compileall -q core/execution` — passed.
- `git diff --check` — passed.
- GitHub Actions run `34673303374` — all four Linux/Windows jobs passed.

## Open questions and disagreements

A fresh Copilot review was requested for exact head `c7d087d` through GitHub's documented REST reviewer endpoint using `copilot-pull-request-reviewer[bot]`, including an explicit JSON retry. The endpoint returned the correct head but an empty requested-reviewer list. Repeated review-list inspections after waiting showed only the earlier reviews on `d0d4e85` and `00769dc`; no review on `c7d087d` materialized, so there is no new Copilot verdict or additional finding to report.

## Next actions and handoff

Stephen reviews `c7d087d` and retains the merge decision. If GitHub later completes a Copilot review, inspect its exact-head findings before merge. Nothing was merged; ED-05 and ED-07 remain untouched.
