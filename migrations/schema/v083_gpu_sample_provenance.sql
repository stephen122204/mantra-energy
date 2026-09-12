-- Preserve sampled-power integration inputs and interval coverage.
ALTER TABLE gpu_samples ADD COLUMN measurement_kind TEXT NOT NULL DEFAULT 'cumulative_energy';
ALTER TABLE gpu_samples ADD COLUMN monotonic_start_ns BIGINT;
ALTER TABLE gpu_samples ADD COLUMN monotonic_end_ns BIGINT;
ALTER TABLE gpu_samples ADD COLUMN power_start_mw INTEGER;
ALTER TABLE gpu_samples ADD COLUMN power_end_mw INTEGER;
ALTER TABLE gpu_samples ADD COLUMN coverage_complete INTEGER NOT NULL DEFAULT 1;
ALTER TABLE gpu_samples ADD COLUMN unavailable_reason TEXT;
ALTER TABLE gpu_samples ADD COLUMN physical_refresh_note TEXT;
ALTER TABLE gpu_samples ADD COLUMN acquisition_start_ns BIGINT;
ALTER TABLE gpu_samples ADD COLUMN acquisition_end_ns BIGINT;

INSERT OR IGNORE INTO energy_domains
    (domain_id, name, description, parent_domain_id, is_leaf, is_cumulative, unit, reader_keys, legacy_column) VALUES
(30, 'PACKAGE_SOCKET_0', 'Socket 0 package-wide Intel RAPL energy', NULL, 0, 1, 'uj', 'package-0', NULL),
(31, 'DRAM_SOCKET_0', 'Socket 0 DRAM Intel RAPL energy', 30, 1, 1, 'uj', 'dram-0', NULL),
(32, 'PACKAGE_SOCKET_1', 'Socket 1 package-wide Intel RAPL energy', NULL, 0, 1, 'uj', 'package-1', NULL),
(33, 'DRAM_SOCKET_1', 'Socket 1 DRAM Intel RAPL energy', 32, 1, 1, 'uj', 'dram-1', NULL);
