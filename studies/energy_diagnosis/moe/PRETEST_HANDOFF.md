# Implementation pre-test handoff

This is an implementation qualification procedure. It does not select a research task suite or authorize a campaign. Use the exact reviewed execution commit, a new output directory, and the session's approved node/time budget.

## Supported execution path

Use `kind: impl` task specifications with explicit versioned `prompt` (`v2` or `v3`), `--agent-protocol chat-tools-v2`, and the supplied llama.cpp configurations. The two configurations must refer to different qualified model files. Keep the same tasks, context, tool access, decoding policy and agent limits in both arms. Never select the historical BF16-only NativeDevice for GGUF execution.

Prompt v3 adds a literal submit_answer call example after a live v2 attempt repeated plain answer text despite feedback. It changes prompt tokens and task identity; never pool the versions. It does not relax parsing or grading. Apply the same version to both arms.

The current smoke contract uses the submit_answer tool to finish and grades the saved solution.py. It does not interpret arbitrary plain text as success. The v2 parser permits an otherwise valid final tool call missing its closing tag; malformed JSON, duplicate keys and mixed submission/tool responses are still rejected. Explicit feedback names the repair. Existing frozen v1 runs stay unchanged.

Before changing tasks, prepare an independently checked bundle. Calibration requires every reference to finish correctly; a timeout establishes no correctness. Invalid numeric budgets/tolerances and empty hidden suites are rejected. Expected results remain outside submitted-code access. Linux Landlock tests are required on the node; portable tests cannot certify that boundary.

## Before using the node

Coordinate exclusive execution. Check the allocation and stop time, GPU/process occupancy, counter permissions, model integrity and free space. Do not download/build/test or create new SSH sessions during guarded measurements. Keep CPU-package and GPU-board counters separate from claims about wall electricity. A previously recorded model load or unit-test pass is not live qualification of a new commit.

Run these implementation tests before the measured smoke:

```sh
python -m pytest -q tests/test_agent_protocol.py tests/test_impl_workload.py tests/test_impl_calibration.py tests/test_implementation_pretest.py tests/test_sandbox_linux.py tests/test_stock_engine_controls.py
```

## Running and checking the smoke

Use the existing guarded stage launcher supplied for the allocation. Each stage executes one goal using the ordinary `studies.energy_diagnosis.moe.run` entrypoint. Pass every limit explicitly: `--max-turns`, `--max-tool-calls`, `--max-total-output-tokens`, `--max-tokens`, and `--deadline`. Never reuse the output directory of a different commit, prompt, bundle or configuration.

Build a private JSON execution contract containing:

- `revision`: exact execution commit;
- `limits`: `context`, `max_turns`, `max_tool_calls`, `max_total_output_tokens`, `max_output_tokens_per_turn`, `goal_seconds`;
- `stages`: objects with `path` (guarded stage output), `arm`, `task_id`, `gguf_path`, `prompt` (defaults to `v2`), and optional `replicate`.

Every task/replicate slot must occur in both arms, with a distinct stage directory. Then run:

```sh
python -m studies.energy_diagnosis.moe.pretest execution-contract.json pretest-report.json
```

The command reads saved records only and refuses to overwrite its output. It verifies guard/cleanup evidence, successful independent grading, exact protocol/settings/task identity, the saved program, and valid energy for model startup, task work and grading in both CPU packages and the GPU. Missing energy never becomes zero. It reports completion-protocol slips and fails the clean-smoke gate if any occurred. This clean-smoke requirement does not authorize excluding failures from an evaluation campaign.

Preserve every attempt, including failed smokes. Copy the raw output off-node, verify the archive hash, and rerun acceptance against restored paths. Record the exact commit and pass/fail/unrun status. Run no full campaign based solely on `implementation_pretest_passed`.

## Task paths not qualified by this smoke

Repository tasks remain blocked by the exit-code-based verifier and the mismatch between requested and enforced regression coverage. Old ETL/program tasks have outstanding answer-isolation findings. None can be substituted for an impl task and receive this pre-test certificate. Repair and adversarially test the relevant boundary before including those paths. Keep correctness, performance-budget failures, program errors, infrastructure failures and protocol completion failures separate.

## Handoff endpoint

Supply the tested commit/branch, approved commands/settings, complete stage dispositions, acceptance JSON, raw archive and hash, and verified restore. Hand off data collection only for the approved task/configuration set. A functioning harness and a scientifically informative task set are separate requirements; the former does not certify the latter.
