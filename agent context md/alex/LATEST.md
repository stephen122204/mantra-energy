# Latest published context: alex

[Immutable turn record](turns/20260912T-ed05-final-review.md)

# Turn summary: Alex — 20260912T-ed05-final-review

## Task and current understanding

Finish existing ED-05 PR #27 for human review using final exact-head Grace evidence. The existing branch is `alex/ed-05-measurement-session`; current and validated head is `0c6b68a127c0fdc68d10d22c5ce50ea9cf76da17`.

## Ideas and hypotheses

Acceptance evidence must distinguish the preliminary nonexclusive `g092` smoke run from the authoritative exclusive-node `g041` run. The primary GPU correctness evidence is equality between the direct NVML cumulative delta and the sum of complete in-goal collector intervals.

## Decisions and rationale

- Audited the complete 18-file ED-05 diff against current integration and found it limited to measurement/session, GPU/RAPL, schema/migration, detection, dependency, documentation, and tests.
- Verified neither ED-02 head `462e904` nor ED-07 head `7d17a50` is an ancestor of the ED-05 branch.
- Retained separate package and DRAM domain reporting and did not infer a whole-machine total.
- Documented Grace localhost proxy bypass (`NO_PROXY`, `no_proxy`, and `requests.Session(trust_env=False)`) as reproducibility context.
- Did not commit the raw hardware artifact or change branch files.

## Changes and artifacts

Updated only PR #27's description and marked it Ready for Stephen. The description records the GPU/NVML and Grace RAPL repairs, focused and broader tests, preliminary nonexclusive evidence, and final exclusive validation.

Authoritative artifact: `$SCRATCH/alems/artifacts/ed05/exclusive-19734683/ed05-exclusive-vllm-measured-run.json`.

## Tests and evidence

- Focused local exact-head rerun: 9 passed.
- Broader ED-05 regression set: 67 passed, 5 subtests passed.
- Setup check, focused compilation, and diff check passed.
- GitHub Actions run `34558496017`: `handoff-and-plan` and `windows-ledger` passed at exact head.
- Grace node `g041`, job `19734683`, exclusive whole-node: real vLLM 0.21.0 with Llama-3.1-8B-Instruct; NVML cumulative delta and 15 contained interval sum both `311649000 µJ`; all four socket-qualified package/DRAM RAPL domains had positive deltas.

## Open questions and disagreements

None blocking bounded ED-05 review. Portable CI does not replace the recorded Grace hardware evidence.

## Next actions and handoff

Stephen reviews Ready PR #27 and retains merge authority. No Copilot review was requested. ED-02 and ED-07 were untouched.
