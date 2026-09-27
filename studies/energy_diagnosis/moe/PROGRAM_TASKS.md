# Python transformation tasks: implementation contract

`python-transform-v1` adds complete read/write/test/submit workflows through the
existing task-pack runtime. It does not launch a campaign or select model settings.

## Task contracts

- **conditional-dedup:** keep the first occurrence of each URL and every record
  marked `keep=true`; preserve input order. Return record IDs. Mixed flags on the
  same URL are explicitly defined, not left to interpretation.
- **user-histogram:** count each user's observations in intervals `(a,b]`. Return
  every observed user, including users with no in-range observations. Repeated
  records count separately. The first bin edge is excluded, the last included.

The agent reads the source and sample, writes `solve(data)`, runs the visible
check, and submits `{done:true}`. A final string assertion is not enough: the
verifier executes the submitted program on original and unseen inputs. Test calls
are available for debugging; passing depends on the resulting program, not on
requiring a particular sequence of tool calls. No hidden expected answers are
copied into the model workspace.

The tool deliberately provides a bounded Python subset: loops, comprehensions,
arithmetic, container operations and documented builtins. It has no imports,
filesystem, network, annotations, helper definitions or input mutation. This is
an explicit task condition; it is not a general Python or Pandas benchmark. The
AST filter is not an OS security boundary. Do not run untrusted third-party code
outside the controlled task environment.

## Provenance and changes

These contracts adapt problem semantics from **DS-1000**, by the DS-1000 authors,
repository `xlang-ai/DS-1000`, commit
`b39aab71da6d23ef8d3cac59a7c5f834516ab334`, problem IDs **7** and **229**:
https://github.com/xlang-ai/DS-1000/tree/b39aab71da6d23ef8d3cac59a7c5f834516ab334

The upstream dataset is licensed **CC BY-SA 4.0**; the license is reproduced in
`licenses/DS-1000-CC-BY-SA-4.0.txt`. The adapted task descriptions and task data
are shared under that license. Attribution does not imply upstream endorsement.

Changes: replace DataFrame snippets with complete tool-mediated JSON-input
functions; clarify mixed duplicate flags, zero-count users and bin edges;
regenerate data at explicit sizes/seeds; replace upstream checks with independently
implemented references, edge cases and adversarial tests. These are **adapted
workloads**, not unmodified DS-1000 tasks and not an official DS-1000 score.
Original source records are identified by SHA-256:

- ID 7: `1344165c422a3cb5b319137500b94de641f837af1265b3792f43b8a8a4b53be0`.
- ID 229: `cbd819e1bcfa6697d185ac28e192e8d317c9eff97ba788e260112f519f38a297`.

## Checks and resource bounds

The reference uses reverse-position selection for deduplication and binary-search
bin lookup for histograms. The fixture solutions use forward sets and nested bin
comparisons. Hand-calculated tests check both references separately. The verifier
uses three additional generated inputs and small edge cases, not only the visible
input. Mutants exercise dropped first records, all-record retention, wrong order,
wrong bin closure, missing zero-count users, collapsed multiplicities and constant
answers. Booleans do not pass as integer counts or IDs.

Each execution gets a separate process, an empty temporary working directory,
JSON inputs, a ten-second wall limit and only the declared builtins. Unix also
uses CPU/file limits; Linux uses a 512 MiB address-space limit. macOS and Windows
local checks do not establish Linux memory-limit qualification. The outer goal
executor remains responsible for the whole-task deadline, including verification.
Timeouts and runtime errors are reported separately from incorrect results.
Correct fixtures pass at 32, 8,192 and 100,000 rows in the local qualification;
live-model timing and budgets must be checked separately before using these tasks.

`task-pack.json` freezes specifications and component hashes. Existing changed
assets are rejected. Use a new output directory after any task, verifier or input
change; do not pool records from changed versions without explicit separation.
