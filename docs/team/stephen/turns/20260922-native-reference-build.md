# Native arithmetic qualification and execution ownership

## Task and current understanding

Stephen is completing integration and bounded native qualification. PR43 and PR44 are merged; PR45 is a draft candidate, not accepted for campaign execution. Current integration includes the complete task pack and explicit longer goal deadlines.

## Ideas and hypotheses

The pinned backend and standard framework use different router precision, expert activation rounding and accumulation order. These can change model scores even when repeated backend runs and preparation comparisons agree. CPU probes support this diagnosis but do not prove full-model agreement.

## Decisions and rationale

Keep the fixed-input reference tolerance unchanged. Preserve earlier failed qualification and pilot outputs. Use a separate source checkout, copied backend environment and build manifest for the compatibility candidate. Do not install packages into the original fingerprinted environment. Physical jobs, builds and bulk copies must use the shared GPU lock.

## Changes and artifacts

PR44 records explicit runtime limits and permits a supplied goal deadline up to 1800 seconds without changing the default. PR45 adds an explicit Transformers 5.3 BF16 arithmetic compatibility mode and actual patched-router CPU tests. Its native build and qualification are queued separately behind the existing pilot. Exact paths and connection information are supplied privately.

## Tests and evidence

All 15 Linux/Windows CI checks pass for PR45 head 67473a577372a46fb9ca1e959412dd1c63742de5. Nineteen focused CPU routing/diagnostic tests pass. Native compilation and unchanged fixed-input reference qualification remain pending. No full campaign readiness claim follows from this CI result.

## Open questions and disagreements

The previous reference qualification failed. The expanded task-pack queue is paused and has not started. A separate operator's older-catalog pilot is running; it is preserved and must not be mistaken for qualification of the expanded pack or new arithmetic build. Do not launch another competing pilot or modify the original backend environment.

## Next actions and handoff

Stephen owns the candidate native build, reference recheck, PR review/merge and subsequent expanded task-pack run. Other agents should fetch this context before hardware work and report their current job/output paths privately. Continue independent local tests. Keep all raw outputs, research plans and private conversations off GitHub. Only resume the expanded queue after its configuration, build and exact execution revision match successful qualification; verify off-node copies afterwards.
