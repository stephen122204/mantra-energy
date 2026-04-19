-- queries/methodology_for_run.sql
-- =============================================================================
-- Full methodology audit for one run — every metric with formula and method
-- =============================================================================
-- Parameters: :run_id
-- Returns: rows
-- Used by: UI DrillDown panel, research audit, PhD reproducibility export
-- =============================================================================

SELECT
    mm.metric_id,
    mm.value_raw,
    mm.value_unit,
    mm.provenance,
    mm.confidence,
    mm.parameters_used,
    mm.captured_at,
    mmr.id              AS method_id,
    mmr.name            AS method_name,
    mmr.formula_latex,
    mmr.description     AS method_description,
    mmr.code_snapshot,
    mmr.layer,
    mmr.parameters      AS method_default_params,
    COALESCE(mdr.label,    mm.metric_id)      AS display_label,
    COALESCE(mdr.category, mmr.layer)         AS category,
    COALESCE(mdr.unit_default, mm.value_unit) AS unit,
    COALESCE(mdr.color_token, 'accent.silicon') AS color_token,
    COALESCE(mdr.direction, 'lower_is_better')  AS direction,
    COALESCE(mdr.display_precision, 2)          AS display_precision
FROM measurement_methodology mm
JOIN measurement_method_registry mmr
    ON mm.method_id = mmr.id
LEFT JOIN metric_display_registry mdr
    ON mm.metric_id = mdr.id
WHERE mm.run_id = :run_id
ORDER BY mmr.layer, mm.metric_id
