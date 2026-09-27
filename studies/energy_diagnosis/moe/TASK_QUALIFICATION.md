# Task preparation and qualification

Prepared assets are not evidence that a task is qualified for collection. Use a
new output directory for changed workload versions or verification dependencies.
Never replace files in an active, frozen run.

## Complete inventory

`prepare_task_screen` prepares all 16 built-in task types by default:

| Family | Types | Shared structure |
| --- | ---: | --- |
| Business SQL | 3 | One generated schema |
| ETL SQL repair | 1 | Latest version of each event |
| Numerical tool use | 1 | Tool performs the regression |
| Python data transformation | 2 | Distinct deduplication and histogram operations |
| Repository repair | 9 | All use NetworkX 3.4.2 |

Pass `--additional-specs /absolute/path/specs.json` to include prepared
implementation problems and explicit larger-input variants. This is a JSON list
in the existing task-pack specification format. No tasks are automatically selected
from a bundle. Six additional implementation problems make 22 candidate task
types; larger inputs increase the case count, not the type count. The emitted
inventory records both counts, family counts, versions, hashes and pending status.
The final collection list must explicitly identify exclusions and their reasons.

## Verification boundaries

- Repository v4: pinned, clean NetworkX source; only public tests enter submitted
  test processes. An external graph oracle compares results in the parent, using
  private challenges prepared once and shared across arms. A zero pytest exit
  cannot pass an unfixed defect. Final verification also runs the public algorithms
  regression suite; its time belongs to final verification and is recorded.
- Repository test execution requires Linux Landlock ABI 4 or later. It can read
  public candidate files and installed dependencies, and write disposable scratch
  files. Adjacent private assets are excluded. Portable tests that explicitly
  disable isolation do not qualify a machine for collection.
- ETL v3 and Python transformation v2 keep private challenge seeds outside the
  model workspace. These seeds are frozen with the asset hash, identical across
  arms and resumes, and different for independently prepared packs. Keep explicit
  edge-case checks in addition to generated challenges.
- Implementation tasks keep private references outside the candidate workspace
  and compare actual outputs in the parent. Their Linux isolation tests remain
  required. None of these boundaries claims exhaustive arbitrary-code security.

## Required evidence before collection

1. Every selected case has immutable assets and verifier/support-component hashes.
2. Known correct implementations pass; deliberately incorrect solutions and known
   shortcuts fail. Record budget, program, infrastructure and wrong-result outcomes
   separately. Do not convert missing counters or incomplete records to zero.
3. Verify filesystem isolation on the collection machine, including attempts to
   read adjacent answer files and fake completion. Missing Linux checks block
   qualification; they are not successful skips.
4. Measure reference execution and verifier time at each intended input size.
   Larger row counts alone do not establish a long or difficult task. Check that
   whole-goal, context, output and tool budgets permit correct completion.
5. Perform bounded live runs for each selected task family and size regime with
   both qualified model configurations. Confirm prompts, tools, inputs, hidden
   checks and completion rules match. Retain all attempts and failure classes.
6. Independently reconcile raw timing/counters to each saved result. Exercise an
   interruption during a batch, restoration, resume without duplication, and a
   checked backup outside the node before unattended collection.

The inventory is a starting record, not a replacement for these per-case and
per-machine checks. A previously qualified small implementation pack does not
automatically qualify the heavier SQL, transformation or repository workloads.
