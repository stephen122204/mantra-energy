# Turn summary: Alex — 20260911T024535Z-grace-capability-preflight

**Publication boundary:** This record contains hardware/runtime capability evidence and implementation handoff details only.

## Task and current understanding

Alex supplied results from a non-model Grace preflight at integration commit `72463d0623b9ce912b02c6ed92dc5f5e068672cb`. The checkout was clean on `research/energy-diagnosis`. No model was downloaded or executed, Ollama was not installed, and no start/end workload energy measurement occurred.

Alex has individual Grace access and independently obtained interactive Slurm job `19728005` on compute node `g002`: partition `gpu`, one A100, eight CPUs, 128 GB memory and one-hour limit. Access itself is no longer treated as blocked. Specific substantial runs still need a named allocation/session and bounded budget, and ED-09 expansion remains gated.

## Ideas and hypotheses

The default CentOS Python 3.6.8 is unsuitable: the repository advertises Python 3.10+ and merged study code uses Python 3.10 syntax. Grace provides newer Python and Anaconda modules, so the next safe step is module/environment discovery rather than installation. An existing vLLM environment for `meta-llama/Llama-3.1-8B-Instruct` could validate the OpenAI-compatible runtime path and support AX3/ED-07, but it cannot exercise the Ollama `/api/chat` response parser.

## Decisions and rationale

Treat the supplied energy values only as raw capability snapshots. On `g002`, Alex directly read both socket package counters and both DRAM counters in microjoules, including their maximum counter ranges. This establishes read permission and declared counter scope, not workload energy. The job allocated only eight of the node's 48 CPUs and one of two A100s; without exclusive-node evidence, socket-wide RAPL includes activity beyond the job and cannot be attributed as isolated job energy.

Use Python 3.11 as the initial compatibility target unless the existing vLLM environment requires another supported Python. Grace's official module inventory lists Python 3.10.8, 3.11.5, 3.12.3 and 3.13.1 plus Anaconda3 releases. No Ollama or vLLM module appears in the published Grace inventory, but live `module spider`/`mla` output is the authority. Grace supports Singularity with NVIDIA passthrough; using a container would still require a reviewed existing image or later authorized download.

Strict evidence for the Ollama-specific ED-02 repair requires one real Ollama-compatible `/api/chat` response through the repaired adapter. A vLLM-only request is useful but does not validate Ollama NDJSON parsing. Native installation is not inherently required if an existing approved Ollama binary, shared environment, container image or reachable loopback service and compatible existing model artifact are available.

## Changes and artifacts

No code changed. No model/runtime/container/package was installed or downloaded. No model request, tool execution, collector session or campaign ran.

Verified hardware facts supplied by Alex:

- Compute host `g002`, Intel Xeon Gold 6248R, x86_64, two sockets, 24 cores/socket, 48 online CPUs, one thread/core.
- Assigned GPU: NVIDIA A100-PCIE-40GB, UUID `GPU-1f093ecc-211c-d69f-29fc-d85007055715`, 40960 MiB, driver `580.126.20`, power management enabled; no GPU process before workload.
- Readable RAPL: package-0 and package-1 counters, each maximum `262143328850` microjoules; DRAM child counter for each package, each maximum `65712999613` microjoules.
- Example raw values were observed for all four domains. They are not deltas and not workload-energy measurements.
- Login node `login5` default Python is 3.6.8. The supplied boot ID belongs to the login node, not compute node `g002`.

## Tests and evidence

Evidence level: **hardware capability-discovered**, not workload-measured, model-validated or campaign-validated.

Satisfied AX3/ED-05 capability elements: individual allocation execution, source revision, compute hostname, requested/assigned resource shape, GPU model/UUID/driver/memory, pre-workload no-process observation, CPU topology, direct read permission for two CPU-package and two DRAM domains, units, example raw values and maximum ranges.

Still open: compute-node boot ID, charged Slurm account, actual CPU affinity, exclusive/sharing state, other node jobs/processes, GPU cumulative-energy API and units, CPU/GPU increment/duplicate/native-refresh characterization, resets/wrap behavior, collector compatibility, raw acquisition brackets, start/end workload deltas, endpoint stability on hardware, enabled/disabled overhead, model/runtime operation, verifier/ledger integration and persistent artifact hashes.

## Open questions and disagreements

The current published Grace module list contains no Ollama or vLLM entry. Live module discovery and Alex's existing vLLM access method must be inspected. It is unknown whether the model is exposed through a shared Conda environment, a module, a container, a local service or a separate workflow. Existing Hugging Face/vLLM weights are not automatically an Ollama model artifact.

RAPL package and DRAM domains overlap by physical hierarchy and span whole sockets. They must be retained separately with parent/coverage metadata; summing package plus DRAM may double count depending on platform semantics. One allocated GPU does not imply the second GPU or host sockets were idle.

## Next actions and handoff

Run only non-destructive discovery next: inspect live Python/Anaconda/Ollama/vLLM/Singularity modules, existing Conda environments, current module state, the existing vLLM command/environment and GPU energy query support. Capture compute-node boot ID, job account, CPU binding and node-sharing evidence in the next allocation. Do not install packages, pull a container, download weights or issue a model request yet.
