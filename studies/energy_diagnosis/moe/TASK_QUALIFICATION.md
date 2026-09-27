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

When model arms use separate output directories, supply both `--task-pack
SPECIFICATIONS.json` and `--task-pack-assets /absolute/path/prepared/assets` to
the run command. Prepare that source once, then reuse it for both arms. The
runner copies and fingerprints the immutable source, checks verifier/helper
identities and refuses changed assets on resume. Preparing each arm independently
would generate different private challenge seeds; equal visible seeds alone do
not establish matched correctness checks.

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
  Installed pristine NetworkX sources are also excluded. Pytest logs go to the
  disposable scratch directory. SciPy's HiGHS scheduler is initialized with one
  thread before candidate process creation is prohibited. Qualify the exact SciPy
  version: this initialization uses its bundled `_highspy` interface, and older
  SciPy releases may not provide it. The checked Linux environment used Python
  3.12.3, pytest 9.1.1, NumPy 2.5.3, SciPy 1.18.1 and NetworkX 3.4.2.
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

## Saved-stage check for each family

`python -m studies.energy_diagnosis.moe.pretest CONTRACT.json REPORT.json` checks
completed guarded stages; it does not launch runs. For the extended contract,
each stage supplies its `kind`, the complete prepared `task_pack` envelope and
the selected `task_catalog_entry`, in addition to the existing arm, task ID,
model path, revision and budget fields. Copy these identities from the frozen
preparation artifacts before execution; do not derive expected values from the
run being checked. Both arms must cover the same task/replicate slots.

The check validates task assets and helper identities against that contract,
expects SQL or Python files where appropriate, and hashes changed repository
files. Structured-answer tasks do not need a source file. `record_valid` is
separate from successful smoke completion: a genuine model failure can have
valid measurements, and must remain in the data. Passing a successful smoke
check still does not authorize the full campaign. The original implementation-
only contract remains supported for archived checks.

## Frozen inputs in batch plans

For campaigns generated with `diagnostics.campaign_plan`, set
`task_pack_assets` on each task entry to the same prepared asset directory used
for qualification. The launcher passes it to every arm and repetition. It
rejects an empty path or a conflicting override in base, family or arm
arguments. The runner validates the copied manifest and helper identities.
Legacy plans without this field remain readable, but do not establish identical
private challenges across independently prepared runs. New collection plans
must include it and explicitly specify the qualified turn, tool, token and
whole-goal budgets; runner defaults are not budget qualification evidence.
