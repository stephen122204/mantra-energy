# Starting prompts for students' models

Replace the bracketed fields before use. Supply only the relevant files and let the agent inspect the checkout. These prompts ask for concrete work, not an unbounded research redesign. Students remain responsible for understanding and reviewing their agent's changes.

## Common opening

```text
You are helping implement the A-LEMS energy-diagnosis study in this repository.
Read the repository's existing instructions and docs/agent-context/AGENTS.md,
README.md, 01-project-brief.md, 03-code-map.md, 04-interfaces-and-data.md,
and my role file: [ROLE FILE]. My assigned issue is [ISSUE ID].
The intended branch is [BRANCH]. The agreed baseline is [COMMIT].

First inspect the actual checkout, working changes, active configuration and
relevant existing interfaces. Summarize what already works, what is only a
source-review concern and what this issue must add. Then implement the smallest
reviewable change with meaningful local tests. Preserve other people's work.
Do not invent APIs, hardware access, observed results or scientific novelty.
Continue independent local work if hardware is unavailable. Do not start a
cluster campaign or push to a remote unless this task explicitly authorizes it.
Finish with the evidence-based progress template and precise remaining work.
```

## Student 1 first task

```text
Use role 06-student-runtime-measurement.md and start ED-02. Inspect the active
models.yaml loader and common HTTP adapter. Reproduce the reported Ollama
stream/response mismatch with representative small fixtures if it still exists.
Repair the actual defect, preserve the OpenAI-compatible path, and correctly
label token/timing metadata and partial failures. Do not download a model or
change the cluster environment for this fixture task. State the exact live
check still needed, or perform it if my task supplies an available local runtime.
```

## Student 2 first task

```text
Use role 07-student-workloads-verifiers.md and start ED-03. Build one immutable
local data-analysis goal and an independent correctness verifier in the agreed
study namespace. Inspect existing tools before choosing an engine. Include
correct, incorrect, missing-evidence and malformed-output fixtures. Specify
candidate eligibility and how real tool worker controls will be observed.
Do not claim energy savings or build a broad benchmark/framework. Leave a
portable task contract that Student 3 can execute through the agreed interface.
```

## Student 3 first task

```text
Use role 08-student-campaign-reproducibility.md and start ED-04. Read the bundled
planner and complete data contract. Implement a separate fixture-driven run
ledger with stable identities, terminal outcomes and resumability. Test restart,
failure and missing-energy cases. Keep planned and executed states distinct.
Do not add hidden model execution to the planner or start a GPU job. Provide
a small export and a validation report for the other students to inspect.
```

## Stephen's method task

```text
Read role 09-stephen-method-integration.md and the current development evidence
[ARTIFACTS]. Propose and implement one bounded diagnostic rule using only
permitted features/profiling results. Define its information cost, budget,
eligibility and abstention behavior. Compare it fairly with simple screening.
Keep hidden reference outcomes out of selection. Distinguish an engineering
prototype from an experimentally supported contribution and report negative
results. Do not enlarge the search space solely to make baselines look costly.
```

## Independent review prompt

```text
Review [PR/DIFF] against its assigned issue and docs/agent-context contracts.
Check correctness, actual configuration routing, measurement boundaries, null
semantics, replay/live distinction, data joins and held-out leakage as relevant.
Verify the reported tests support the claimed evidence level. Identify concrete
defects with file/line references; distinguish observations from suspicions.
Do not change unrelated code or declare SIGMETRICS readiness from passing tests.
```
