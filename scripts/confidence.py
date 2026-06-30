"""
confidence.py — Confidence scoring for energy chain validation checks.

Weighted composite confidence score per conservation check:
  score = 0.4 × sample_score + 0.4 × calibration_score + 0.2 × source_score

Levels: HIGH >= 0.8, MEDIUM >= 0.5, LOW < 0.5

Per spec validator_rewrite_spec_v2.md §4.
"""

from typing import Optional


def sample_score(n_samples):
    # type: (int) -> float
    """
    Score based on number of energy samples for this run.
    At 10Hz SPBM, 100 samples = 10 seconds minimum run duration.
    At 100Hz RAPL, 100 samples = 1 second.

    Args:
        n_samples: Number of energy samples collected for this run.

    Returns:
        Score 0.0 to 1.0.
    """
    if n_samples >= 100:
        return 1.0
    elif n_samples >= 50:
        return 0.8
    elif n_samples >= 20:
        return 0.6
    elif n_samples >= 10:
        return 0.4
    else:
        return 0.2


def calibration_score(residual_pct, historical_mean, historical_std):
    # type: (float, Optional[float], Optional[float]) -> float
    """
    Score based on how consistent this run's residual is with history.
    Uses z-score: how many standard deviations from the historical mean.

    Args:
        residual_pct:    This run's conservation residual as a percentage.
        historical_mean: Mean residual from prior runs (same platform + workflow).
        historical_std:  Std dev of residual from prior runs.

    Returns:
        Score 0.0 to 1.0. Returns 0.5 when no calibration history available.
    """
    if historical_mean is None or historical_std is None or historical_std == 0:
        return 0.5  # no history — neutral score

    z = abs(residual_pct - historical_mean) / historical_std
    if z <= 1.0:
        return 1.0
    elif z <= 2.0:
        return 0.7
    elif z <= 3.0:
        return 0.4
    else:
        return 0.1


def source_score(check_name, platform_config):
    # type: (str, dict) -> Optional[float]
    """
    Static score based on measurement source properties for this check.
    Read from platform config — never hardcoded.

    Args:
        check_name:      Check name e.g. 'ML1-INT', 'ML0-ML1', 'ML1-ML2'.
        platform_config: Platform config dict from platform_config.py.

    Returns:
        Score 0.0 to 1.0, or None if check not applicable on platform.
    """
    scores = platform_config.get('source_scores', {})
    return scores.get(check_name)


def composite_score(n_samples, residual_pct, historical_mean, historical_std,
                    check_name, platform_config):
    # type: (int, float, Optional[float], Optional[float], str, dict) -> dict
    """
    Weighted composite confidence score.

    Formula: 0.4 × sample + 0.4 × calibration + 0.2 × source

    If source score is None (check not applicable on platform),
    redistributes weight: 0.5 × sample + 0.5 × calibration.

    Args:
        n_samples:       Number of energy samples for this run.
        residual_pct:    Conservation residual percentage.
        historical_mean: Historical mean residual for calibration.
        historical_std:  Historical std dev for calibration.
        check_name:      Conservation check name.
        platform_config: Platform config dict.

    Returns:
        dict with score (float), level (str), and component scores.
    """
    s_score = sample_score(n_samples)
    c_score = calibration_score(residual_pct, historical_mean, historical_std)
    src_score = source_score(check_name, platform_config)

    if src_score is None:
        # Check not applicable on platform — redistribute weights
        total = 0.5 * s_score + 0.5 * c_score
        components = {
            'sample':      round(s_score, 2),
            'calibration': round(c_score, 2),
            'source':      None,
        }
    else:
        total = 0.4 * s_score + 0.4 * c_score + 0.2 * src_score
        components = {
            'sample':      round(s_score, 2),
            'calibration': round(c_score, 2),
            'source':      round(src_score, 2),
        }

    score = round(total, 2)
    return {
        'score':      score,
        'level':      confidence_level(score),
        'components': components,
    }


def confidence_level(score):
    # type: (float) -> str
    """
    Map numeric score to level label.

    Args:
        score: Composite confidence score 0.0 to 1.0.

    Returns:
        'HIGH', 'MEDIUM', or 'LOW'.
    """
    if score >= 0.8:
        return 'HIGH'
    elif score >= 0.5:
        return 'MEDIUM'
    else:
        return 'LOW'


def get_historical_stats(conn, platform, workflow_type, check_name):
    # type: (object, str, str, str) -> tuple
    """
    Fetch historical mean and std dev of conservation residual
    from energy_derived_metrics table for this platform + workflow.

    Used to compute calibration_score.

    Args:
        conn:          Open DB connection.
        platform:      Platform string e.g. 'arm_spbm'.
        workflow_type: 'agentic' or 'linear'.
        check_name:    'ML1-INT', 'ML0-ML1', 'ML1-ML2'.

    Returns:
        (mean, std) or (None, None) if insufficient history.
    """
    # Map check name to metric name in energy_derived_metrics
    metric_map = {
        'ML1-INT': 'c1_residual_pct',
        'ML0-ML1': 'c2_board_pct',
        'ML1-ML2': 'c3_ratio',
    }
    metric_name = metric_map.get(check_name)
    if not metric_name:
        return None, None

    try:
        row = conn.execute("""
            SELECT AVG(edm.value_uj) as mean_val,
                   -- SQLite has no STDEV — approximate with variance
                   AVG(edm.value_uj * edm.value_uj) - AVG(edm.value_uj) * AVG(edm.value_uj) as var_val,
                   COUNT(*) as n
            FROM energy_derived_metrics edm
            JOIN runs r ON r.run_id = edm.run_id
            WHERE edm.metric_name = ?
              AND r.workflow_type = ?
              AND r.energy_measurement_mode LIKE ?
              AND r.attributed_energy_uj > 0
        """, (metric_name, workflow_type, '%spbm%' if 'spbm' in platform else '%')).fetchone()

        if not row or row[2] < 5:
            # Fewer than 5 historical runs — no reliable calibration
            return None, None

        mean = row[0]
        var  = row[1]
        std  = var ** 0.5 if var and var > 0 else 0.0
        return mean, std

    except Exception:
        return None, None
