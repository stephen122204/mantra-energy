# Prefill/decode energy tests: exact runs

`bench.py` starts a stock `llama-server` per (precision, concurrency) cell, sends fixed-length requests from
P concurrent clients (greedy, `ignore_eos`, `cache_prompt: false`) and reads the NVML cumulative energy counter
of one GPU board around each repetition. One warm-up batch per cell is discarded. Each cell = 32 requests,
3 repetitions. CPU and DRAM energy are not included.

`bench.py` and `setup.sh` are the exact files that produced `../results/v100-20261016/`.

## Hardware and software (16 Oct 2026)

| item | value |
|---|---|
| node | Chameleon CHI@UC `alems-v100-explore`, 4× Tesla V100-SXM2-32GB, image CC-Ubuntu22.04-CUDA |
| engine | llama.cpp `f12aaa344c971556ec35be054d7aac1d901fd510`, CUDA arch 70, `-ngl 99`, `-c P×2048`, `-np P` |
| models | `Qwen/Qwen3-8B-GGUF` Q4_K_M and Q8_0 (hashes in `../results/v100-20261016/models_sha256.txt`) |
| energy | `nvmlDeviceGetTotalEnergyConsumption`, GPU board only; idle power recorded per cell (`idle_w`), not subtracted |

## Commands (run as `cc` from `~` after `bash setup.sh`)

| test | command | GPU |
|---|---|---|
| p0 mixed | `python bench.py --gpu 3` | 3 |
| p0b mixed, order swapped | `python bench.py --gpu 3 --port 8099 --order q8,q4 --tag p0b` | 3 |
| p0c decode-heavy | `python bench.py --gpu 2 --port 8098 --order q4,q8 --short-prompt --n-predict 512 --tag p0c` | 2 |
| p0d prefill-only | `python bench.py --gpu 3 --port 8099 --order q8,q4 --n-predict 1 --tag p0d` | 3 |

p0b and p0c ran at the same time on different GPUs of the same node. Each reads only its own board's counter;
the host CPU was shared. No other user's job was on the node (checked).

Summary: `python3 summarize.py ../results/v100-20261016` (output saved as `summary.csv` there).
