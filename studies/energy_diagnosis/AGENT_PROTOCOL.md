# Agent protocol

`moe/run.py --agent-protocol` selects how the model and tools interact.

## chat-tools-v1 (default)

Implemented in `agent_protocol.py` and `GoalExecutor._chat` (`local_run.py`).

- The model's own chat template renders a normal conversation: system rules,
  the goal with the turn budget, then each assistant turn with its tool calls
  (name and arguments) and one tool message per call.
- Tools are passed as function definitions (`tools=` in the template). The
  answer is submitted with a `submit_answer` tool; it must be the only call in
  its turn.
- Tool results carry `status`, `result` or `error`, and `turns_remaining`.
  Execution metadata (`tool_accounting`, timings, worker counts) is removed
  before the model sees a result and kept in `tool-results.json`.
- Responses are parsed strictly: duplicate JSON keys, non-finite numbers,
  unbalanced tags, extra call fields, more than eight calls, and
  `submit_answer` mixed with other calls are malformed.
- A malformed response, a response without a tool call, an invalid tool call,
  and a failing tool (for example a SQL error) are returned to the model and
  cost a turn. They do not end the attempt.
- Calls in one turn run in order unless the setting enables tool concurrency.
  The model cannot declare dependencies.

Each completed model response and tool phase is saved immediately under
`goals/<execution>/turns/` and checkpointed in the ledger. These immutable
partial records survive process interruption; they do not constitute a final
answer, completed measurement, or successful attempt. Logging overhead is part
of the measured execution window and uses the same path for both settings.

Each finalized attempt writes `agent-trace.json` with one outcome:

| outcome | execution_status | meaning |
|---|---|---|
| passed | completed | verifier passed within the deadline |
| wrong_answer | completed | verifier failed |
| output_truncated | incomplete | a response reached the per-turn output limit |
| turn_budget_exhausted | incomplete | no answer within the turn limit |
| tool_call_budget_exhausted | incomplete | `--max-tool-calls` reached |
| output_budget_exhausted | incomplete | `--max-total-output-tokens` reached |
| context_exhausted | incomplete | prompt plus output allowance exceeded the context; nothing generated |
| deadline_exceeded | timed_out | goal deadline reached in a model call, tool or verification |
| infrastructure_failure | crashed | backend or harness failure |

All outcomes are attempts with their measured energy.

Per-turn records in the trace include the finish reason, token counts, the
sampling seed, the per-call output allowance, the parse result and repeated identical calls.
Each model request is capped by the smaller of its per-turn limit and remaining
whole-goal output budget. A final answer cannot bypass that cap; inconsistent
backend token counts are infrastructure failures.

## Decoding

`--decoding greedy` (default) or `--decoding sampled` with `--temperature`,
`--top-p`, `--top-k`, `--min-p` (defaults are the model card values 0.7, 0.8,
20, 0) and `--sampling-seed`. Each turn's seed is derived from the base seed,
the planned run without its setting suffix, and the turn index, so both arms
of a pair use the same seed at the same turn.

## Deadline

`--deadline` is one absolute limit from goal start. It bounds model calls,
backend control requests, every tool call in a turn (dependent calls share it rather than each receiving
a fresh allowance), and verification. Verification runs in an owned, bounded subprocess; a stuck
verifier is terminated at the remaining deadline. Late results cannot pass, and
`verification.json` records the timeout when no verdict is available. Process
startup is included in verification time. Cleanup is bounded separately. The deadline rules also
apply to `legacy-json-v1`.

## legacy-json-v1

Reproduces V6: one user message per step with a static instruction and tool
results, greedy decoding only. Kept for comparison with V6 records; do not use
it for new evaluations.

## Token audit

`moe/audit_token_budget.py` replays chat requests with the same template call.
Truncation and context exhaustion that the harness recorded are reported as
`budget_outcome`, not audit errors; an unrecorded truncation or an
inconsistent replay is still an error.
