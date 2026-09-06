# Turn summary: Stephen — 20260906-dependencies-hardware

## Task and current understanding

Stephen asked whether the named tasks are independent or depend on other people, and wanted beginning/end expectations, workflow and hardware made very clear. The initial fixture tasks are mostly parallel, but the real integration and scientific evaluation have explicit dependencies. Common interfaces are the first enabling shared deliverable.

## Ideas and hypotheses

Separating component, pipeline and scientific completion should prevent an agent from treating a local passing test as a completed experiment or publication result. A small agreed contract plus synthetic example enables local progress without waiting for all runtime/hardware work. The later gate still requires actual inference, tools, verification and valid measurements in the same experiment.

## Decisions and rationale

Kept the established proposed named split. Alex begins locally on runtime fixtures and later uses assigned Grace A100 sessions for live model/energy validation. Aldric begins locally on tasks/verifiers and later joins the Grace environment for real controls. Nitheesh begins locally on a fixture ledger and later runs the pilot using the validated components. Stephen establishes contracts/design now and later makes empirical method/evaluation decisions. No new machine purchase, H100 requirement or platform-per-student assignment was introduced.

## Changes and artifacts

Updated existing PR #14 rather than opening another PR for the same kickoff task. Commit ec7b29fe535fdac363fd7e09744a18dd632056c9 adds agent context md/DEPENDENCIES_AND_HARDWARE.md and updates the four name.txt prompts, human message, index and entry points. Rebuilt portable prompts and ALEMS_Named_Kickoff_Prompts.zip. PR URL: https://github.com/stephen122204/alems-energy-diagnosis/pull/14. It remains unmerged.

## Tests and evidence

Portable prompts match repository copies. python3 scripts/check_energy_diagnosis_setup.py and git diff --check passed. GitHub CI for this update is https://github.com/stephen122204/alems-energy-diagnosis/actions/runs/34052125863; inspect its actual status. Changes are documentation only. No model, hardware run or new resource allocation occurred.

## Open questions and disagreements

Actual accounts and sessions remain an operational dependency. ED-01's precise interfaces remain to be agreed. ED-07 depends on ED-02/05 runtime/measurement, ED-03/06 task/controls and ED-04 ledger; ED-09 additionally needs ED-08's pilot assets. ED-10 requires usable pilot/development evidence, though method design can start now. Software completion does not establish a SIGMETRICS-level result, and missing host energy cannot be replaced by GPU-only readings for CPU-tool claims.

## Next actions and handoff

Stephen reviews updated PR #14 and shares the revised kickoff materials. Students start their independent fixture tasks and explicitly state provisional interfaces. Plan one integration session after the required components and individual access are ready, then the bounded pilot. Each person hands off tested interfaces/artifacts and evidence, not only a status message. Continue separate tasks while PR review is pending; coordinate energy sessions and exact tested versions. Publish this summary through the shared context helper.
