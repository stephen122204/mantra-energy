# Fall submission timeline and practical work split

Planning date: 6 September 2026. These are internal targets, not evidence that access, implementations or experiments are complete. The [official SIGMETRICS 2027 call](https://www.sigmetrics.org/sigmetrics2027/pages/cfp.html), checked on 6 September, lists **abstract registration on 2 October 2026 and paper submission on 9 October 2026, both at 23:59 Anywhere on Earth (AoE)**. Stephen owns registration and submission. Use earlier internal targets below rather than spending the deadline-day margin.

## Work backward from submission

| Internal target | Required outcome | Main ownership |
|---|---|---|
| **7–8 September** | Confirm repository access, agree minimal ED-01 interfaces/example records, start each local fixture task, and identify a bookable individual Grace account/session. | Stephen coordinates; everyone starts their named issue. |
| **9–10 September** | First reviewable component PRs and meaningful fixtures. Hardware capability check identifies readable CPU/GPU energy domains and resource sharing; report any access blocker immediately. | Alex: provider/telemetry; Aldric: goal/verifier; Nitheesh: ledger. |
| **11–12 September** | One integrated real goal executes on Grace with independent verification, usable linked measurements and recorded configuration/attempt identity. Resolve blocking correctness or measurement defects before repeating runs. | All; Stephen integrates. |
| **13–15 September** | **First round of usable real test data due by 15 September:** bounded four-goal pilot across eligible controls, with repetitions, failures, raw records and initial plots. Target two goals per family, four candidate settings and three repeats (up to 48 planned executions); eligibility and budget must be checked first. | Alex validates measurements, Aldric validates task semantics, Nitheesh runs/exports; Stephen reviews. |
| **16–18 September** | Development-only diagnosis and simple-baseline comparisons; decide whether the proposed method has a defensible opportunity. Estimate full cost from the pilot and secure sufficient sessions. Freeze the method, baseline definitions, task lineage split, verifier, code/configuration and analysis plan before held-out evaluation. | Stephen leads; students/agents resolve specific defects and supply evidence. |
| **19–25 September** | Run and validate the agreed main evaluation; **core data and first complete result figures due 25 September**. Assemble the evidence needed for each claim, including correctness, latency, profiling cost, uncertainty and failure coverage. | Nitheesh coordinates runs; Alex/Aldric validate components; Stephen analyzes and drafts. |
| **26 September–1 October** | **Six-day contingency window** for missing or invalid measurements, specific robustness checks, replication and data reconciliation. Aim for a complete rough paper by 27 September, revised with this evidence. Draft the substantive title/abstract by 30 September. | Stephen directs only checks needed to resolve concrete gaps. |
| **2 October** | Register the substantive abstract by the official deadline; finish a complete draft with the central claims and results in place. | Stephen with team review. |
| **3–7 October** | Final writing, figure/claim/source checks, reproducibility and submission-format review. Only bounded confirmatory checks that resolve a named issue; preserve evaluation separation and record any invalidated results. | Stephen leads writing; everyone verifies their part. |
| **8 October** | Internal submission target: reviewed paper ready to upload and check. | Stephen. |
| **9 October** | Official paper deadline, 23:59 AoE; remaining margin is for submission problems or critical corrections. | Stephen. |

Writing starts alongside engineering: Stephen drafts the question, related work, method and experimental setup during the pilot/development period. We do not leave the first paper draft until the final week. September 26–October 1 is the main experimental buffer; October 3–7 is primarily revision time.

## What counts as the first good data

The September 15 target is an engineering pilot, not proof of a publishable effect. Each included run needs actual model inference and tool computation, immutable task and configuration identity, an independent correctness outcome, valid measurement boundaries, explicit observed energy domains/coverage, preserved failure/retry records, and the exact source/runtime versions. An example trace and derived result must be inspectable back to raw records. A deliberately incorrect answer must be rejected, and missing energy must remain missing.

Use repetitions to inspect repeatability and measurement variation. Sensor samples are not independent experimental replicates. If a candidate is ineligible, record the reason rather than silently substituting another task. The pilot should yield usable energy, latency and success summaries plus observed time/allocation cost; it need not show a positive saving. A GPU-only record cannot support an unqualified CPU-tool energy claim.

## Most implementation work belongs to the agents

Humans should skim the overview and their own assignment enough to understand the objective, inputs, outputs and failure conditions, then start the agent promptly. Reading the entire repository or understanding every implementation detail is not a prerequisite. Concentrate human time on access and hardware behavior, a few consequential logic checks, debugging real failures and verifying the evidence behind the handoff.

Agents inspect the relevant code, create small reproductions, implement scoped fixes, run focused tests, prepare sample artifacts, update PRs and publish context after every completed turn. Ask for the smallest useful next deliverable and exact evidence. Hardware execution can also be agent-driven within an individually authorized account and an assigned session/budget. Humans resolve credentials/access, confirm the actual environment and resource isolation, inspect outputs and escalate unresolved failures. Do not stop fixture work while waiting for a session.

Code confidence comes from testing the failure modes that could invalidate the result: provider compatibility and partial outputs; verifier rejection of wrong answers; task dependency/control semantics; ledger interruptions and retries; missing energy; and endpoint behavior. A repaired defect needs a reproduction that fails before and passes after where feasible. Then test the joined system on hardware at the exact recorded commit. Human spot checks use independent expected values or raw evidence, not only the same agent-generated assertions. Broaden tests when failures or consequential uncertainty justify it; do not spend the schedule on cosmetic refactors or redundant tests.

At each active workday's handoff, provide a PR/commit, tests and example artifact, what remains unverified, and the next bounded action. Raise a blocker that threatens the next milestone on the day it becomes clear. Stephen coordinates same-day contract/review decisions where possible. This is a team workflow, not a newly installed automatic reminder.

The CFP permits generative-AI assistance with author responsibility and requires disclosure of its extent in Methods. Keep a concise record of that assistance. Human authors own the scientific question, method choices, interpretation and accuracy of the paper. [Official policy](https://www.sigmetrics.org/sigmetrics2027/pages/cfp.html)

## Conditions for keeping this schedule

The first integration and pilot dates assume prompt repository access and a usable Grace session by September 10–12. These have not been reserved by this document. If access or CPU-energy validity fails, Stephen decides promptly whether an already authorized alternative supports a narrower defensible claim. Do not expand to several new platforms as a routine deadline response.

The September 18 decision must account for actual measured run time, available allocation, queue behavior and analysis effort. If the full evaluation will not fit, revise scope before freezing and before looking at held-out reference results, with an explicit impact on the claim. Do not reduce samples or choose tasks after observing favorable held-out outcomes. If the method does not improve on simple alternatives or the necessary evidence cannot be obtained, reassess the Fall target rather than describing an incomplete study as ready.

During the contingency window, rerun invalid measurements under documented rules and preserve their original disposition. A substantive method/configuration change needs a new version and reevaluation of affected results; do not tune against held-out results and retain the same generalization claim. The buffer is for resolving evidence gaps, not silently adding a new paper scope.
