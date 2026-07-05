-- v72_gpu_dcgm_domain.sql
-- Adds GPU_DCGM as its own canonical domain, separate from GPU.
--
-- GPU (domain 7) is SPBM's broad rail on GN100: GPU compute + GPU memory +
-- NVLink-C2C, all folded into one number. gpu_total_energy_uj (the run-level
-- field) was fixed earlier this session to source from DCGM instead, the
-- compute-only signal, because that's the correct total for EpG. But the
-- idle baseline was still being subtracted using the old broad SPBM number,
-- baseline bigger than total on short runs, gpu_dynamic_energy_uj clamped
-- to zero on every single run.
--
-- GPU_DCGM is a parallel leaf, not a child of GPU. These are two different
-- instruments measuring overlapping but not identical physical hardware,
-- not a strict energy-conservation subset relationship, so no parent/child
-- link is implied. GPU (broad SPBM rail) is left completely untouched —
-- still measured, still stored, needed for the NVLink-C2C power paper,
-- where GPU minus GPU_DCGM is the actual signal of interest.

INSERT OR IGNORE INTO energy_domains
    (domain_id, name, description, parent_domain_id, is_leaf, is_cumulative) VALUES
(24, 'GPU_DCGM', 'GPU compute-only energy via DCGM field 156 (GN100) or MSR PP1 (Tiger Lake)', 1, 1, 1);

PRAGMA foreign_key_check;
PRAGMA integrity_check;

INSERT INTO schema_version (version, applied_at, description)
VALUES (72, datetime('now'), 'GPU_DCGM domain: compute-only GPU energy, separate from GPU broad-rail domain, fixes gpu_dynamic_energy_uj baseline mismatch');
