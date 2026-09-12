# Turn summary: Alex — 20260912T-ed02-copilot-fixes

## Task and current understanding

Address four correctness findings on ED-02 PR #24 without changing ED-05/ED-07 or unrelated code. The requested Grace checkout path was unavailable in this execution environment, so work used a fresh temporary clone attached to the existing `alex/ed-02-local-runtime` tracking branch. Old head was `d0d4e85b0e75d53e97fa934c455cf561358e2f6a`; fetched integration was `8869321859a0c794d1d940c7f5ec4accc0ec7682`.

Alex milestone status: AX1/ED-02 remains hardware-tested and Ready for review with this correctness follow-up; AX2/ED-05 and AX3/ED-05/12 retain their separate fixture/hardware evidence; AX4/ED-07/09 remains integration-dependent; AX5 remains conditional on Stephen's pilot/freeze. Only AX1 files were changed.

## Ideas and hypotheses

Protocol shape and execution locality are independent. `_is_ollama` must select endpoint/response parsing, while `_is_cloud` must select local versus non-local timing and throughput windows. Provider counts received before a later parse failure remain valid observations but cannot become successful final token accounting.

## Decisions and rationale

Capture JSON token fields into `_http_call`'s existing local count variables before returning so its `finally` block retains valid observations. Preserve failure semantics: final `tokens` remains empty and provenance unknown.

Normalize only `None` stream content to empty text. Validate every other value as a string before truthiness filtering, so falsy malformed values cannot bypass validation.

Use `_is_cloud` for success and failure timing attribution. Remote endpoints use `non_local_ms` and their network-time throughput window; local endpoints use `local_compute_ms` and the local total-time throughput window.

## Changes and artifacts

Commit `00769dc41eba0e1f2418028fc9fd1d6ef7238a43` (`Fix adapter failure observations and locality timing`) was pushed normally to `origin/alex/ed-02-local-runtime`.

Changed only:

- `core/execution/adapters/openai_compat.py`
- `tests/test_openai_compat_adapter.py`

PR #24 description was updated with the correctness follow-up and exact validation. It remains Ready and unmerged. No ED-05 or ED-07 files changed.

## Tests and evidence

- `python3 -m pytest -q tests/test_openai_compat_adapter.py` — 44 passed.
- `python3 -m pytest -q tests/test_openai_compat_adapter.py tests/test_study_contracts.py tests/test_campaign_ledger.py tests/test_data_analysis_workload.py tests/test_db_config.py tests/test_energy_collector.py scripts/tests/test_publish_agent_context.py` — 97 passed, 5 subtests passed, one pre-existing `test_db_config` return-value warning.
- `python3 -m compileall -q core/execution/adapters/openai_compat.py` — passed.
- `git diff --check` — passed.
- GitHub Actions run `34669955722` — all four jobs passed on Linux/Windows.

Focused tests cover Ollama and OpenAI-compatible JSON failure observations, `0`/`False`/`[]` streamed content rejection for Ollama NDJSON and OpenAI SSE, and remote-Ollama/local-vLLM success/failure timing plus throughput locality.

## Open questions and disagreements

No code blocker remains. GitHub's requested-reviewer REST endpoint was tried with both `Copilot` and the observed bot login `copilot-pull-request-reviewer[bot]`, but the PR still reports no requested reviewers; a fresh Copilot review could not be confirmed through the API.

## Next actions and handoff

Stephen and Copilot review commit `00769dc`. Stephen retains the merge decision. Nothing was merged, and ED-05/ED-07 remain untouched.
