-- v16: gpu_samples and gpu_config tables
-- Chunk 15-A GPU energy support
-- Mirrors existing samples table pattern exactly (energy_samples, cpu_samples, etc.)
-- Sampling rate: 10 Hz (configurable). source column identifies backend per sample.
--
-- cp to: scripts/migrations/v16_gpu_samples_config.sql
-- Run:   sqlite3 data/experiments.db < scripts/migrations/v16_gpu_samples_config.sql

-- GPU per-sample energy measurements at 10 Hz
-- start/end counter pattern mirrors energy_samples.pkg_start_uj / pkg_end_uj
CREATE TABLE IF NOT EXISTS gpu_samples (
    sample_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(run_id),
    gpu_index        INTEGER NOT NULL DEFAULT 0,  -- 0-based index, for multi-GPU machines
    sample_start_ns  BIGINT NOT NULL,             -- epoch ns at sample start
    sample_end_ns    BIGINT NOT NULL,             -- epoch ns at sample end
    interval_ns      BIGINT NOT NULL,             -- sample_end_ns - sample_start_ns

    -- Energy counters (cumulative start/end like energy_samples pattern)
    energy_start_uj  BIGINT,   -- raw counter at sample start (µJ)
    energy_end_uj    BIGINT,   -- raw counter at sample end (µJ)
    energy_uj        BIGINT,   -- delta = energy_end_uj - energy_start_uj (denorm for query speed)

    -- Instantaneous power (for backends without cumulative counters, e.g. older NVML)
    power_mw         INTEGER,

    -- GPU activity signals (populated by NVML/DCGM/ROCm; NULL for MSR backend)
    util_gpu_pct     REAL,      -- core utilization %
    util_mem_pct     REAL,      -- memory bandwidth utilization %
    sm_clock_mhz     INTEGER,   -- SM clock frequency
    mem_clock_mhz    INTEGER,   -- memory clock frequency
    mem_used_mb      INTEGER,   -- GPU memory used
    temperature_c    INTEGER,   -- GPU temperature

    -- Provenance: which backend produced this sample (critical for paper methodology)
    source           TEXT NOT NULL  -- 'msr_pp1'|'nvml'|'dcgm'|'rocm_smi'|'iokit'|'estimated'
);

CREATE INDEX IF NOT EXISTS idx_gpu_samples_run
    ON gpu_samples(run_id);
CREATE INDEX IF NOT EXISTS idx_gpu_samples_time
    ON gpu_samples(run_id, sample_start_ns);

-- GPU hardware identity — one row per physical GPU
-- Populated by scripts/chunk15_detect_gpu.py at install or hw change
-- gpu_hash enables tracking energy behavior across driver upgrades
CREATE TABLE IF NOT EXISTS gpu_config (
    gpu_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    gpu_index         INTEGER NOT NULL DEFAULT 0,  -- 0-based, matches gpu_samples.gpu_index
    vendor            TEXT NOT NULL,               -- 'intel'|'nvidia'|'amd'|'apple'
    model             TEXT NOT NULL,               -- e.g. 'Intel Iris Xe', 'RTX 4070 Mobile'
    driver_version    TEXT,
    cuda_version      TEXT,            -- NULL for non-NVIDIA
    rocm_version      TEXT,            -- NULL for non-AMD
    vbios_version     TEXT,
    pci_id            TEXT,            -- e.g. '8086:9a49'
    memory_total_mb   INTEGER,
    energy_supported  INTEGER NOT NULL DEFAULT 0,  -- 1 if energy counters exposed
    backend           TEXT,            -- 'msr_pp1'|'nvml'|'dcgm'|'rocm_smi'|'iokit'|'none'
    gpu_hash          TEXT NOT NULL,   -- SHA256(model||pci_id||driver_version)
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(gpu_index, gpu_hash)        -- idempotent upsert key
);

CREATE INDEX IF NOT EXISTS idx_gpu_config_vendor
    ON gpu_config(vendor);

-- Integrity checks before committing
PRAGMA foreign_key_check;
PRAGMA integrity_check;

INSERT INTO schema_version (version, applied_at, description)
VALUES (47, datetime('now'), 'Chunk 15-A: gpu_samples + gpu_config tables');
