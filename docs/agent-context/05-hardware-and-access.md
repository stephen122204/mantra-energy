# Hardware and access: updated from Alex's message

## Evidence status

Alex's screenshots supplied by Stephen report GPU access on Grace, FASTER and Lonestar; 20,000 SUs each on Grace/FASTER in Alex's student allocation; 200,000 SUs each on Grace/FASTER/Lonestar under Dr. Tyagi; and approved Explore ACCESS. He reports readable CPU/GPU telemetry and suggests Stephen obtain an account with Dr. Tyagi as PI. These are team-reported capabilities and allocation awards, not a measured balance, Stephen's account activation or completed energy validation. No shared credentials or personal remote-machine instructions are included here.

This supersedes the earlier statement that Explore ACCESS was only submitted and no usable team GPU access had been established. It does not yet resolve which CPU energy domains are readable. The older operator correspondence left RAPL/MSR access under investigation; a node-side check is the best next evidence.

## Primary arrangement

| Need | Proposed starting arrangement |
|---|---|
| GPU | One Grace A100 40GB; 80GB is also suitable if another validated platform is selected |
| Host allocation | Target 16 CPU cores and 64GB RAM for the four-candidate workload; adjust from observed requirements and scheduler policy |
| Isolation | Prefer whole-node reservation for main measurements; one GPU allocation alone does not isolate host-package energy |
| Storage | Initially budget approximately 100GB for pilot model/assets/logs; measure growth and revise before campaign |
| Runtime | Pinned local server, model, tokenizer, settings and tools in the same compute allocation as collection |
| Equipment | Existing computers for development; no physical probe or external meter required to start |

Grace documents two A100 40GB GPUs per A100 node, 48 CPU cores and 384GB RAM. Reserve only the computational resources needed, but establish an isolation arrangement for energy measurements; the billing cost of whole-node isolation may be higher. [Grace hardware](https://hprc.tamu.edu/kb/User-Guides/Grace/Hardware/)

Qwen2.5 7B Instruct Q4_K_M is a proposed Ollama pilot model with an approximately 4.7GB weight artifact; context/KV cache and runtime add memory. Start with one model request at a time and explicit 8,192-token context if this model is selected. A working existing vLLM path can be chosen before the freeze instead of building a second runtime. Verify the real model succeeds on the tasks. [Model](https://ollama.com/library/qwen2.5:7b-instruct-q4_K_M), [Ollama configuration](https://docs.ollama.com/faq)

## Preflight deliverable

Student 1 records: hostname/boot and device identities; requested versus actual CPU/GPU allocation; runtime/model revision; GPU residency; CPU/GPU energy APIs, read permissions, units and scope; counter increment/reset/wrap behavior; sensor refresh/duplicate rates; collection overhead; CPU/GPU sharing state; and persistent artifact destination. No elevated privilege is inherently required if operators provide suitable read access.

CPU temperature, utilization or frequency is not CPU energy. If GPU energy works but host energy does not, local integration may proceed, but the planned CPU-tool energy-saving claim cannot pass the main-campaign gate on that evidence alone. Obtain operator-provided host energy or select another capable environment.

## Alex's job example: smoke test only

Alex provided this interactive allocation example, reproduced as evidence rather than an instruction to execute immediately:

```bash
srun --partition=gpu --gres=gpu:a100:1 --time=03:00:00 --mem=128G --ntasks=1 --cpus-per-task=8 --pty bash
```

It requests one A100, eight CPUs and 128GB host memory for up to three hours; it does not guarantee exclusive use of the node or imply the physical node has only one GPU. Adapt the account, CPU/memory request and walltime to the actual cluster policies. The largest proposed candidate uses eight tool workers plus supporting work, motivating more CPU headroom for the controlled comparison. Do not change allocations across candidate settings.

Grace and Lonestar6 use different documented GPU partition conventions. Do not copy one job command unchanged across all clusters. [Grace batch guide](https://hprc.tamu.edu/kb/User-Guides/Grace/Batch/), [Lonestar6](https://docs.tacc.utexas.edu/hpc/lonestar6/)

## Budget and later platforms

Start with a scheduled capability/smoke-test session, then a 12–24 node-hour pilot allowance if resources are assigned. The old 1,432-execution planning matrix assumes five-minute average runs and about 119.3 active execution hours; a 160–220 node-hour allowance includes an illustrative margin, not a quote or reservation. Recompute from actual durations, conditioning and billing rules. SUs are not GPU-hours; check remaining balances and the allocation selected for each job.

Explore ACCESS is approved according to Alex, but exact H100/H200 resource activation remains unverified. ACCESS credits normally need exchange into a specific active resource allocation. It is a secondary option, not a prerequisite for the primary experiment. [ACCESS activation](https://allocations.access-ci.org/get-your-first-project)

A second machine such as GN100 or FASTER is an optional transfer check after a primary finding exists. A locally attached logging power meter or operator-exported chassis reading can independently validate a correctly scoped electrical measurement; chassis readings on externally composed GPU systems may exclude GPU enclosures. No whole-system claim without coverage evidence.

