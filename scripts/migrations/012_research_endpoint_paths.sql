-- scripts/migrations/012_research_endpoint_paths.sql
-- Sets endpoint_path for all q01-q30 research insight queries.
-- These exist in query_registry but have NULL endpoint_path
-- so they are never auto-registered by auto_router.py.
-- After applying: curl -X POST http://localhost:8765/internal/reload

-- Energy & attribution queries
UPDATE query_registry SET endpoint_path = '/research/q01_energy_per_query'
  WHERE id LIKE 'q01%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q02_energy_per_token'
  WHERE id LIKE 'q02%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q03_energy_per_llm_call'
  WHERE id LIKE 'q03%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q04_power_profile'
  WHERE id LIKE 'q04%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q05_token_energy_split'
  WHERE id LIKE 'q05%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q06_silicon_attribution'
  WHERE id LIKE 'q06%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q07_dynamic_vs_baseline'
  WHERE id LIKE 'q07%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q08_cstate_residency'
  WHERE id LIKE 'q08%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q09_cache_miss_impact'
  WHERE id LIKE 'q09%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q10_thermal_impact'
  WHERE id LIKE 'q10%' AND endpoint_path IS NULL;

-- Orchestration & tax queries
UPDATE query_registry SET endpoint_path = '/research/q11_phase_attribution'
  WHERE id LIKE 'q11%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q12_orchestration_tax'
  WHERE id LIKE 'q12%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q13_ooi_index'
  WHERE id LIKE 'q13%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q14_llm_efficiency'
  WHERE id LIKE 'q14%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q15_network_wait'
  WHERE id LIKE 'q15%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q16_linear_vs_agentic'
  WHERE id LIKE 'q16%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q17_model_comparison'
  WHERE id LIKE 'q17%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q18_task_domain_profile'
  WHERE id LIKE 'q18%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q19_complexity_scaling'
  WHERE id LIKE 'q19%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q20_provider_comparison'
  WHERE id LIKE 'q20%' AND endpoint_path IS NULL;

-- Statistical & quality queries
UPDATE query_registry SET endpoint_path = '/research/q21_data_coverage'
  WHERE id LIKE 'q21%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q22_outlier_detection'
  WHERE id LIKE 'q22%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q23_statistical_sufficiency'
  WHERE id LIKE 'q23%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q24_reproducibility'
  WHERE id LIKE 'q24%' AND endpoint_path IS NULL;

-- Environmental & sustainability
UPDATE query_registry SET endpoint_path = '/research/q25_carbon_per_query'
  WHERE id LIKE 'q25%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q26_environmental_footprint'
  WHERE id LIKE 'q26%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q27_energy_trend'
  WHERE id LIKE 'q27%' AND endpoint_path IS NULL;

-- Timeseries & drilldown
UPDATE query_registry SET endpoint_path = '/research/q28_run_drilldown'
  WHERE id LIKE 'q28%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q29_llm_breakdown'
  WHERE id LIKE 'q29%' AND endpoint_path IS NULL;

UPDATE query_registry SET endpoint_path = '/research/q30_energy_timeseries'
  WHERE id LIKE 'q30%' AND endpoint_path IS NULL;

-- Also set group_name to 'research' for all q* queries
UPDATE query_registry SET group_name = 'research'
  WHERE id LIKE 'q%' AND (group_name IS NULL OR group_name = 'analytics');

-- Verify
SELECT id, endpoint_path, group_name
FROM query_registry
WHERE id LIKE 'q%'
ORDER BY id;
