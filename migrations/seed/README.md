# migrations/seed/ README

## Seed file naming

`sNNN_<table_name>.sql` where NNN is a zero-padded sequence number.
All seed files use `INSERT OR IGNORE`, fully idempotent, safe to
re-run at any time on any platform.

## Current seed files

| File | Table | Rows | Classification |
|---|---|---|---|
| s001_energy_sources.sql | energy_sources | 9 | Universal |
| s002_energy_domains.sql | energy_domains | 29 | Universal |
| s003_retry_policy.sql | retry_policy | 3 | Universal |
| s004_outlier_detection_config.sql | outlier_detection_config | 11 | Universal |
| s005_analysis_domain_config.sql | analysis_domain_config | 10 | Universal |
| s006_analysis_view_config.sql | analysis_view_config | 8 | Universal |
| s007_metric_analysis_domains.sql | metric_analysis_domains | 132 | Universal |
| s008_power_limits.sql | power_limits | 4 | Universal |

## Platform-specific seed data

Platform-specific seed files live in `migrations/platform/<platform_name>/`.
Currently only GN100 has platform-specific seed data (power_rails, 10 rows).
See `migrations/platform/README.md`.

## Tables intentionally without seed data

The following tables are created by schema.py but have no seed rows.
They are populated dynamically by future features or at runtime:

    component_registry       (dashboard component catalog, future)
    page_configs             (dashboard page layout, future)
    page_sections            (dashboard page sections, future)
    query_registry           (saved query catalog, future)
    standardization_registry (metric normalization rules, future)
    task_quality_config      (per-task quality thresholds, chunk 8.5-C)

Do not create placeholder seed files for these tables.
