# A-LEMS Known Gaps — Fresh Checkout Issues
# These gaps cause silent failures on new machines.
# All are tracked for resolution in the installer script (install.sh).

---

## Gap 1: HuggingFace benchmark cache missing on fresh checkout

**Impact:** `humaneval_t1_*` and `triviaqa_t1_*` tasks fail silently on first run.
**Root cause:** `data/benchmarks/` is not gitignored globally — only specific DB files are.
Benchmark cache is machine-local. Fresh checkout has no cache.
**Symptom:** Task runs but `prompt` is None → LLM gets empty input → wrong answer scored.
**Fix:** `install.sh` must run:
```bash
python scripts/prefetch_benchmarks.py --datasets gsm8k,triviaqa,humaneval
```
**HuggingFace auth:** `gsm8k` and `triviaqa` — public, no token needed.
`humaneval` — requires HF token + license acceptance at https://huggingface.co/datasets/openai_humaneval
```bash
huggingface-cli login   # paste token with read access
```
**Status:** Not documented anywhere. `benchmark_loader.py` has zero auth handling.

---

## Gap 2: `perf_event_paranoid` not set on fresh checkout

**Impact:** `PerfReader.perf_available = False` → all IPC/cache columns NULL.
**Root cause:** Default Linux kernel sets `/proc/sys/kernel/perf_event_paranoid = 3`
(restricted). A-LEMS needs ≤ 1 for process-level perf counters.
**Fix:** `install.sh` must run:
```bash
echo 1 | sudo tee /proc/sys/kernel/perf_event_paranoid
echo 'kernel.perf_event_paranoid = 1' | sudo tee -a /etc/sysctl.d/99-alems.conf
sudo sysctl -p /etc/sysctl.d/99-alems.conf
```
**Status:** Not in any setup doc.

---

## Gap 3: turbostat capabilities not set on fresh checkout

**Impact:** `package_temp = NULL`, C-state residency = NULL for all runs.
**Root cause:** turbostat binary needs `cap_sys_rawio` capability.
Fresh checkout has no systemd unit installed.
**Fix:** `install.sh` must run:
```bash
sudo bash scripts/fix_permissions.sh
sudo systemctl enable alems-turbostat-caps.service
sudo systemctl start alems-turbostat-caps.service
```
**Status:** Documented in admin guide (doc 29) but not in install.sh.

---

## Gap 4: `detect_hardware.py` must run on first boot

**Impact:** `hw_config.json` missing → energy_engine falls back to defaults → wrong thermal zone mapping.
**Fix:** `install.sh` must run:
```bash
python scripts/detect_hardware.py
```
**Note:** `hw_config.json` is machine-generated — never commit to git.
**Status:** Mentioned in admin guide but not enforced by installer.

---

## Gap 5: RAPL permissions not set on fresh checkout

**Impact:** `pkg_energy_uj = NULL` → no energy measurement → all EpG values NULL.
**Fix:** `install.sh` must run:
```bash
sudo systemctl enable alems-rapl-permissions.service
sudo systemctl start alems-rapl-permissions.service
```
**Status:** systemd unit exists but not documented in install flow.

---

## Gap 6: `data/benchmarks/` not pre-seeded

**Impact:** First run of any Tier 1 benchmark task downloads dataset — adds
10-60 seconds to first experiment, pollutes timing measurements.
**Fix:** Prefetch all datasets before first experiment run.
**Status:** No prefetch script exists yet. `benchmark_loader.py` caches on first use.

---

## Resolution Plan

All gaps resolved by `scripts/install.sh` (to be created in installer chunk).
Order of operations:
1. `pip install -r requirements.txt`
2. Set RAPL permissions (Gap 5)
3. Set perf_event_paranoid (Gap 2)
4. Set turbostat capabilities (Gap 3)
5. Run detect_hardware.py (Gap 4)
6. HuggingFace login + prefetch benchmarks (Gaps 1, 6)
7. Run migrations
8. Verify: `bash scripts/test_provenance.sh`
