# Latest published context: alex

[Immutable turn record](turns/20260912T-ed02-holistic-audit.md)

# Turn summary: Alex — 20260912T-ed02-holistic-audit

## Task and current understanding

Stop iterative review-comment fixes, return ED-02 PR #24 to Draft, audit the complete adapter → executor → persistence → CI path, and implement one coherent repair without requesting another Copilot review. Audit began at `c7d087dc3efb445d2079d70619ca21b378f5b9a9`; fetched integration was `ed5ffc72a7621485267c5b88f86893e9f5de4a08`; final branch head is `462e9044b9e0c88d015cc4153479404cb8fbf81b`.

Active text routes were traced through `config/models.yaml` and `ModelFactory`: Ollama local/remote and OpenAI-compatible vLLM/Groq/OpenAI/DeepSeek/NVIDIA NIM use `OpenAICompatAdapter`; Anthropic and Gemini use their SDK adapters; local GGUF uses `LlamaCppAdapter`. Media routes are not consumed as text generation by Linear/Agentic.

OpenAICompat has the ED-02 structured top-level status/provenance/observation contract. Anthropic/Gemini historically return `Error:` content and zero tokens; LlamaCpp adds nested `execution.status=failure`; some SDK post-processing errors can raise. Executors historically treated returned dictionaries as success and exceptions as failure. Expanding ED-02 to infer every legacy error shape would risk false positives and accidental behavior change.

Alex milestone status: AX1/ED-02 is fixture-tested and hardware-tested but Draft pending architecture review; AX2/AX3 retain separate ED-05 evidence; AX4 remains ED-07/09 integration-dependent; AX5 remains conditional. ED-05/ED-07 were untouched.

## Ideas and hypotheses

Failure validation should be polymorphic and adapter-owned. A base no-op preserves historical adapters; OpenAICompat can explicitly reject its own status without string/nested-shape heuristics. A typed exception can carry structured diagnostics into existing executor failure accounting.

The current database schema already supports durable failure status/error text, nullable tokens, timing and network fields. It has no metadata JSON or columns for partial text, observed tokens or provenance. Adding a migration solely for ED-02 is disproportionate; those fields should remain accurately described as in-memory evidence.

## Decisions and rationale

- Converted PR #24 to Draft before audit and kept it Draft.
- Replaced the global `require_adapter_success` shape guard with `TextGenABC.require_success`, whose default passes through, and an OpenAICompat override that raises typed `AdapterCallError` only for its explicit error status.
- Both Linear and Agentic call the same polymorphic hook.
- Linear maps its error to the existing durable `error_message` column. Structured-failure token columns remain null rather than measured zero.
- Retained partial content, observed tokens and provenance in in-memory executor results/interactions, while documenting that fixed-column persistence discards them.
- Added a real in-memory SQLite persistence regression for the supported durable evidence.
- Added executor/persistence tests to both OS variants of the adapter fixture CI job and added source/test path triggers.
- Did not normalize Anthropic/Gemini/LlamaCpp legacy failure returns in ED-02.

## Changes and artifacts

Commits pushed normally:

- `da2821e5b3cc686b32f6d6db9fee76a60c9ef234` — `Narrow adapter failure contract and persist supported evidence`
- `462e9044b9e0c88d015cc4153479404cb8fbf81b` — `Keep executor failure tests dependency-isolated`

Final ED-02 diff contains only:

- `.github/workflows/energy-diagnosis-setup.yml`
- `core/execution/adapters/base.py`
- `core/execution/adapters/openai_compat.py`
- `core/execution/agentic.py`
- `core/execution/linear.py`
- `tests/test_executor_adapter_failures.py`
- `tests/test_openai_compat_adapter.py`

No schema migration, ED-05, or ED-07 file changed. PR #24 description records the audit/durability boundary and remains unmerged.

## Tests and evidence

Final head `462e904`:

- `python3 -m pytest -q tests/test_openai_compat_adapter.py` — 45 passed.
- `python3 -m pytest -q tests/test_executor_adapter_failures.py` — 6 passed.
- Broader ED-02 set including both suites — 104 passed, 5 subtests passed; one pre-existing `test_db_config` return-value warning.
- `python3 -m compileall -q core/execution` — passed.
- `git diff --check` — passed.
- GitHub Actions run `34674359960` — all four jobs passed, including combined adapter/executor tests on Ubuntu and Windows.

The first exact-head CI run at `da2821e` found a Windows test-collection dependency on PyYAML. `462e904` isolated the test imports from unrelated optional runtime dependencies; both OS jobs then passed.

## Open questions and disagreements

Historical Anthropic/Gemini/LlamaCpp returned-error semantics remain inconsistent with the ED-02 structured contract. This is valid cross-repository debt but intentionally not normalized here because string or nested-shape inference can change existing successful behavior and needs a separately reviewed adapter-contract migration.

Partial content, observed tokens and token provenance are not durable in `llm_interactions`; only supported failure evidence is persisted. A future shared schema/version decision may add structured diagnostic metadata, but ED-02 adds no migration.

No Copilot review was requested after the holistic audit/final head, per user instruction.

## Next actions and handoff

Stephen/user inspects the Draft PR architecture and audit results before deciding when to request one final review. Nothing was merged; no ED-05/ED-07 work changed.
