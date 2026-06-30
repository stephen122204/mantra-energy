#!/usr/bin/env python3
"""
scripts/migrations/v80_outlier_v2_views.py

Generates 12 purpose-scoped views (6 domains x 2 tiers) after migration
v80's schema and seed files have run. Run order:
    sqlite3 "$DB" < v80_outlier_v2_schema.sql
    sqlite3 "$DB" < v80_outlier_v2_seed.sql
    python3 v80_outlier_v2_views.py --db "$DB"

Two tiers per domain, decided after v1 review surfaced two distinct
cases that needed different treatment:

    clean    excludes runs with a CONFIRMED outlier of EITHER
             outlier_class (data_quality_failure OR statistical_anomaly).
             Use for population statistics: mean, CV, EpG averages.
             This is the representative, conservative dataset.

    measured excludes runs with a CONFIRMED data_quality_failure only.
             Keeps confirmed statistical_anomaly rows, because those
             values are real measurements, just unusual ones. Use for
             distribution analysis, tail behavior, worst-case/best-case
             arguments, robustness claims. A run that genuinely consumed
             100M uJ while its peers consumed 7M belongs here even
             though it would distort a mean.

This script does not open its own DB connection logic beyond a plain
sqlite3.connect, matching the convention established in
scripts/etl/compute_outliers.py for batch/migration scripts (as opposed
to the DatabaseManager/Repository facade used by the harness write path).
"""

import argparse
import logging
import sqlite3

logger = logging.getLogger(__name__)

# (tier_name, SQL fragment appended to the WHERE clause). Empty string
# for 'clean' means no additional filter beyond confirmed status, since
# 'clean' excludes both outlier_class values.
TIERS = [
    ("clean", ""),
    ("measured", "AND ro.outlier_class = 'data_quality_failure'"),
]

# Domain-scoped view name suffixes. Matches the view_name values seeded
# into analysis_view_config by v80_outlier_v2_seed.sql.
VIEW_DOMAINS = [
    "energy",
    "cpu",
    "thermal",
    "llm",
    "orchestration",
    "system",
]


def _has_foundation(cursor, view_name):
    # type: (sqlite3.Cursor, str) -> bool
    """
    Whether this view_name's rows in analysis_view_config all carry
    include_foundation=1. By convention (documented in
    v80_outlier_v2_seed.sql) every row for a given view_name shares the
    same include_foundation value, so MAX() across the group is
    equivalent to checking any single row, and is simpler than asserting
    uniformity with a separate query.
    """
    cursor.execute(
        "SELECT MAX(include_foundation) FROM analysis_view_config WHERE view_name = ?",
        (view_name,),
    )
    row = cursor.fetchone()
    return bool(row[0]) if row and row[0] is not None else False


def _build_view_sql(view_name, tier_name, class_filter, has_foundation):
    # type: (str, str, str, bool) -> str
    """
    Construct the CREATE VIEW statement for one (domain, tier) pair.

    Structurally identical to v_runs_clean (migration v79) and to
    v_runs_clean_<domain> from SPEC_OUTLIER_V2.md Section 3.6/3.7, with
    one addition: class_filter, which is empty for the clean tier and
    restricts to data_quality_failure only for the measured tier.
    """
    full_view_name = "v_runs_{}_{}".format(tier_name, view_name)

    if has_foundation:
        foundation_clause = """
                  OR mad.domain_name IN (
                      SELECT domain_name FROM analysis_domain_config
                      WHERE is_foundation = 1
                  )"""
    else:
        foundation_clause = ""

    return """
CREATE VIEW IF NOT EXISTS {full_view_name} AS
SELECT r.*
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
LEFT JOIN run_quality rq ON r.run_id = rq.run_id
WHERE
    e.is_valid = 1
    AND COALESCE(rq.experiment_valid, 1) = 1
    AND r.run_id NOT IN (
        SELECT DISTINCT ro.run_id
        FROM run_outliers ro
        JOIN metric_analysis_domains mad
            ON ro.metric_name = mad.metric_name
        WHERE ro.review_status = 'confirmed'
          {class_filter}
          AND (
              mad.domain_name IN (
                  SELECT avc.domain_name FROM analysis_view_config avc
                  WHERE avc.view_name = '{view_name}'
              )
              {foundation_clause}
          )
    );
""".format(
        full_view_name=full_view_name,
        class_filter=class_filter,
        view_name=view_name,
        foundation_clause=foundation_clause,
    )


def create_purpose_views(conn):
    # type: (sqlite3.Connection) -> int
    """
    Generate all 12 domain-scoped views (6 domains x 2 tiers). Returns
    the count of views created, for the caller to log/validate against.
    """
    cursor = conn.cursor()
    created = 0

    for view_name in VIEW_DOMAINS:
        has_foundation = _has_foundation(cursor, view_name)

        for tier_name, class_filter in TIERS:
            sql = _build_view_sql(view_name, tier_name, class_filter, has_foundation)
            try:
                cursor.executescript(sql)
                created += 1
                logger.info("Created v_runs_%s_%s", tier_name, view_name)
            except sqlite3.OperationalError as e:
                # Surfaced explicitly rather than swallowed (DC-3): a
                # CREATE VIEW failure here means analysis_view_config or
                # metric_analysis_domains seed data is missing or
                # malformed, and the caller needs to know which view
                # failed and why, not just that "something" failed.
                logger.error(
                    "Failed to create v_runs_%s_%s: %s", tier_name, view_name, e
                )
                raise

    conn.commit()
    return created


def validate_v80(conn):
    # type: (sqlite3.Connection) -> list
    """
    Post-migration checks. Returns a list of (description, passed) tuples
    so the caller can print a clear pass/fail summary rather than a raw
    traceback on the first failed assertion.
    """
    cursor = conn.cursor()
    checks = []

    for table in ("analysis_domain_config", "metric_analysis_domains", "analysis_view_config"):
        count = cursor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
        checks.append(("{} exists".format(table), count == 1))

    domain_count = cursor.execute("SELECT COUNT(*) FROM analysis_domain_config").fetchone()[0]
    checks.append(("Domains seeded ({})".format(domain_count), domain_count == 10))

    foundation_count = cursor.execute(
        "SELECT COUNT(*) FROM analysis_domain_config WHERE is_foundation = 1"
    ).fetchone()[0]
    checks.append(("Foundation domain exists", foundation_count == 1))

    mapping_count = cursor.execute("SELECT COUNT(*) FROM metric_analysis_domains").fetchone()[0]
    checks.append(("Metric mappings seeded ({})".format(mapping_count), mapping_count == 132))

    view_config_count = cursor.execute("SELECT COUNT(*) FROM analysis_view_config").fetchone()[0]
    checks.append(("View config seeded ({})".format(view_config_count), view_config_count >= 8))

    expected_views = []
    for domain in VIEW_DOMAINS:
        for tier_name, _ in TIERS:
            expected_views.append("v_runs_{}_{}".format(tier_name, domain))

    for view in expected_views:
        exists = cursor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name=?", (view,)
        ).fetchone()[0]
        checks.append(("{} exists".format(view), exists == 1))

    checks.append(("Total domain-scoped views = 12", len(expected_views) == 12))

    clean_exists = cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name='v_runs_clean'"
    ).fetchone()[0]
    checks.append(("v_runs_clean (v1, unchanged) still exists", clean_exists == 1))

    cols = [row[1] for row in cursor.execute("PRAGMA table_info(run_outliers)").fetchall()]
    checks.append(("run_outliers.outlier_class column exists", "outlier_class" in cols))

    dq_count = cursor.execute(
        "SELECT COUNT(*) FROM run_outliers WHERE outlier_class = 'data_quality_failure'"
    ).fetchone()[0]
    checks.append(("Existing 22 rows classified data_quality_failure ({})".format(dq_count), dq_count >= 22))

    runs_count = cursor.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    for view in expected_views:
        vcount = cursor.execute("SELECT COUNT(*) FROM {}".format(view)).fetchone()[0]
        checks.append(("{} ({}) <= runs ({})".format(view, vcount, runs_count), vcount <= runs_count))

    # The defining tier-separation property: for any domain, the
    # measured tier must be at least as permissive as the clean tier,
    # since measured excludes a strict subset of what clean excludes.
    for domain in VIEW_DOMAINS:
        clean_count = cursor.execute(
            "SELECT COUNT(*) FROM v_runs_clean_{}".format(domain)
        ).fetchone()[0]
        measured_count = cursor.execute(
            "SELECT COUNT(*) FROM v_runs_measured_{}".format(domain)
        ).fetchone()[0]
        checks.append((
            "v_runs_measured_{} ({}) >= v_runs_clean_{} ({})".format(
                domain, measured_count, domain, clean_count
            ),
            measured_count >= clean_count,
        ))

    return checks


def main():
    # type: () -> None
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to experiments.db")
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if "sigmetrics_paper1" in args.db:
        raise SystemExit(
            "Refusing to run against {}: filename matches a frozen "
            "snapshot marker. Frozen Paper 1 snapshots are read only "
            "references, not migration targets.".format(args.db)
        )

    conn = sqlite3.connect(args.db)
    try:
        created = create_purpose_views(conn)
        logger.info("Created %d views", created)

        if not args.skip_validation:
            checks = validate_v80(conn)
            failed = [desc for desc, passed in checks if not passed]
            for desc, passed in checks:
                print("{} {}".format("PASS" if passed else "FAIL", desc))
            if failed:
                raise SystemExit(
                    "{} validation check(s) failed: {}".format(len(failed), failed)
                )
            print("All {} validation checks passed.".format(len(checks)))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
