-- v081: Add cpu_active_ratio column to runs table
-- Captures fraction of measurement window during which the primary compute
-- cluster was actively executing. Apple Silicon only (IOReport active residency
-- / wall_ns * num_p_cores). NULL on all other platforms.
-- Companion to frequency_mhz: together they describe active frequency AND
-- utilization, which are independent on Apple Silicon.
ALTER TABLE runs ADD COLUMN cpu_active_ratio REAL;
