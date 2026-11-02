"""Read-only severity audit: count every source of severity and reconcile it.

Nothing here writes: the script only SELECTs, so it can be run against a live
database while investigating a reported mismatch. It prints, per table and per
API surface, the severity distribution next to the total it should partition,
and flags any surface where the two disagree.

Usage:
    python scripts/audit_severity_counts.py [--month YYYY-MM]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

sys.path.insert(0, ".")

from sqlalchemy import func, or_  # noqa: E402

from app.api import quality_alerts as qa  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.eligibility import exclude_disabled  # noqa: E402
from app.engine.quality_alerts import (  # noqa: E402
    CLOSED_STATUSES,
    effective_severity,
    stored_series,
)
from app.models import (  # noqa: E402
    ConfidenceScore,
    LayeredOutlierResult,
    QualityAlert,
    Rule,
    ValidationResult,
)

RULE_BANDS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
OUTLIER_BANDS = ("NONE", "LOW", "MODERATE", "HIGH", "VERY_HIGH")


def _say(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def _dist(counter: Counter, bands) -> str:
    return " · ".join(f"{b}={counter.get(b, 0)}" for b in bands)


def _policy_band(row) -> str:
    """The band the approved caps assign to a stored alert (as the API reads it)."""
    evidence = row.evidence or {}
    return effective_severity(
        row.severity, stats=evidence.get("stats"), method=row.method,
        peer_count=row.peer_count,
        series=stored_series(evidence)) or row.severity


def quality_alerts(db, month=None) -> None:
    q = db.query(QualityAlert)
    if month:
        q = q.filter(QualityAlert.month == month)
    rows = q.all()
    open_rows = [r for r in rows if r.status not in CLOSED_STATUSES]
    # Retired rows are records of findings a later scan no longer detects: every
    # screen and every count reads active rows only, so they are reconciled
    # apart — a retired row keeps the band it was written with, it is not a
    # live row that disagrees with the policy.
    live = [r for r in open_rows if r.active]
    retired = [r for r in open_rows if not r.active]

    stored = Counter(r.severity for r in live)
    policy = Counter(_policy_band(r) for r in live)
    drift = sum(1 for r in live if _policy_band(r) != r.severity)

    _say("quality_alerts (perspective ROWS, open & active)")
    print(f"  live / retired rows       : {len(live)} / {len(retired)}")
    print(f"  stored severity           : {_dist(stored, OUTLIER_BANDS)}")
    print(f"  policy severity           : {_dist(policy, OUTLIER_BANDS)}")
    print(f"  stored  sum == total      : {sum(stored.values()) == len(live)}")
    print(f"  policy  sum == total      : {sum(policy.values()) == len(live)}")
    print(f"  stored != policy (live)   : {drift}"
          + ("  (the scan writes the capped band)" if drift == 0
             else "  !! live rows disagree with the cap policy"))
    if retired:
        retired_stored = Counter(r.severity for r in retired)
        retired_drift = sum(1 for r in retired if _policy_band(r) != r.severity)
        print(f"  retired stored severity   : {_dist(retired_stored, OUTLIER_BANDS)}")
        print(f"  retired lower under policy: {retired_drift} (historical records;"
              " not counted by any screen)")

    issues = qa._group_alerts(live, {}) if live else []
    by_issue = Counter(i["primary_severity"] for i in issues)
    _say("quality_alerts (grouped ISSUES, open)")
    print(f"  total issues              : {len(issues)}")
    print(f"  policy severity           : {_dist(by_issue, OUTLIER_BANDS)}")
    print(f"  sum == total              : {sum(by_issue.values()) == len(issues)}")
    print("  NOTE: ROW counts and ISSUE counts are different units and are"
          " expected to differ.")


def validation_results(db, month=None) -> None:
    q = (db.query(ValidationResult)
         .join(Rule, Rule.code == ValidationResult.rule_code)
         .filter(ValidationResult.status == "FAIL"))
    q = exclude_disabled(db, q, ValidationResult)
    if month:
        q = q.filter(ValidationResult.month == month)
    rows = q.all()
    dist = Counter(r.severity for r in rows)
    _say("validation_results (FAIL, rule exists, eligible)")
    print(f"  total rows                : {len(rows)}")
    print(f"  severity                  : {_dist(dist, RULE_BANDS)}")
    print(f"  sum == total              : {sum(dist.values()) == len(rows)}")
    unknown = {k: v for k, v in dist.items() if k not in RULE_BANDS}
    if unknown:
        print(f"  !! levels outside the rule vocabulary: {unknown}")


def layered(db, month=None) -> None:
    q = db.query(LayeredOutlierResult)
    if month:
        q = q.filter(LayeredOutlierResult.month == month)
    rows = q.all()
    dist = Counter(r.outlier_level for r in rows)
    _say("layered_outlier_results (Outlier Diagnostics)")
    print(f"  total rows                : {len(rows)}")
    print(f"  outlier_level             : {_dist(dist, OUTLIER_BANDS)}")
    print(f"  sum == total              : {sum(dist.values()) == len(rows)}")
    unknown = {k: v for k, v in dist.items() if k not in OUTLIER_BANDS}
    if unknown:
        print(f"  !! levels outside the outlier vocabulary: {unknown}")


def api_surfaces(db, month=None) -> None:
    kw = dict(month=month, hospital_id=None, indicator=None, perspective=None,
              status=None, ownership_id=None, governorate_id=None,
              hospital_type_id=None, confidence=None, indicator_type=None,
              q=None, include_closed=False)
    s_all = qa.get_summary(severity=None, db=db, **kw)
    s_vh = qa.get_summary(severity="VERY_HIGH", db=db, **kw)
    i_vh = qa.list_issues(severity="VERY_HIGH", sort="severity", order="desc",
                          page=1, page_size=0, db=db, **kw)

    _say("/quality-alerts/summary")
    print(f"  total_issues (all bands)  : {s_all['total_issues']}")
    print(f"  very_high_issues          : {s_all['very_high_issues']}")
    print(f"  very_high_only + mixed    : "
          f"{s_all['very_high_only_issues'] + s_all['mixed_severity_issues']}")
    print(f"  very_high_rows (evidence) : {s_all['very_high_rows']}")
    print(f"  very_high_only            : {s_all['very_high_only_issues']}"
          f"  (one comparison only {s_all['very_high_single_perspective_issues']},"
          f" corroborated by 2+ {s_all['very_high_only_corroborated_issues']})")
    print(f"  mixed_severity_issues     : {s_all['mixed_severity_issues']}")
    print(f"  only + mixed == VH issues : "
          f"{s_all['very_high_only_issues'] + s_all['mixed_severity_issues']}"
          f" == {s_all['very_high_issues']}")
    # "Every perspective is Very High" is vacuous when only one fired, so the
    # bucket is printed by the SET of comparisons behind each issue: one
    # comparison alone cannot corroborate anything, two or more can.
    for entry in s_all["very_high_only_by_perspectives"][:8]:
        print("    " + " + ".join(entry["perspectives"]) +
              f" -> {entry['issues']}" +
              ("  (corroborated)" if entry["corroborated"] else ""))
    print(f"  total_active (rows)       : {s_all['total_active']}")
    print(f"  by_severity (ROWS)        : {s_all['by_severity']}")
    print("  !! by_severity counts ROWS while total_issues counts ISSUES;"
          f" VH rows {s_all['by_severity'].get('VERY_HIGH', 0)} >"
          f" VH issues {s_all['very_high_issues']} is expected, not an error.")
    print(f"  Very-High filter total    : {s_vh['total_issues']}"
          f"  (== /issues total {i_vh['total']})")


def rule_variants(db, month=None) -> None:
    """The SAME validation table read under four different scopes.

    Every one of these totals is defensible; side by side they explain why the
    validation failure count differs between screens without any record being
    wrong.
    """
    def _count(query):
        if month:
            query = query.filter(ValidationResult.month == month)
        return query.count()

    base = db.query(ValidationResult).filter(ValidationResult.status == "FAIL")
    joined = base.join(Rule, Rule.code == ValidationResult.rule_code)
    non_bench = joined.filter(or_(
        ValidationResult.rule_type.is_(None),
        func.upper(ValidationResult.rule_type) != "BENCHMARK",
    ))
    eligible = exclude_disabled(db, non_bench, ValidationResult)

    _say("validation_results — four scopes of one table")
    print(f"  FAIL rows (raw)                 : {_count(base)}")
    print(f"  + rule still exists             : {_count(joined)}")
    print(f"  + not a benchmark rule          : {_count(non_bench)}")
    print(f"  + hospital/month eligible       : {_count(eligible)}")


def layered_classification(db, month=None) -> None:
    q = db.query(LayeredOutlierResult)
    if month:
        q = q.filter(LayeredOutlierResult.month == month)
    rows = q.all()
    dist = Counter(r.outlier_type for r in rows)
    _say("layered_outlier_results — classification")
    print(f"  total rows                : {len(rows)}")
    print("  outlier_type              : " +
          " · ".join(f"{k}={v}" for k, v in dist.most_common(8)))
    print(f"  sum == total              : {sum(dist.values()) == len(rows)}")
    # Classification is a VERDICT vocabulary (NORMAL / PEER_ANOMALY / …), not a
    # severity band: one row has one verdict and one band, and neither is
    # derivable from the other.
    assessed = Counter(bool(r.history_provenance) for r in rows)
    print(f"  rows with history provenance: {assessed.get(True, 0)}")
    print(f"  rows without (pre-policy)   : {assessed.get(False, 0)}")


def duplicates_and_staleness(db) -> None:
    """How many stored ROWS collapse into one issue, and how many bands moved.

    Both are legitimate — a formula registered under several codes is one
    finding, and a cap lowers a stored band — but they are the two reasons a
    row count and an issue count cannot be compared directly.
    """
    rows = [a for a in db.query(QualityAlert).all()
            if a.status not in CLOSED_STATUSES and a.active]
    codes_per_issue: dict = {}
    for a in rows:
        key = qa._issue_key(a)
        codes_per_issue.setdefault(key, set()).add(a.indicator_code)
    multi = sum(1 for v in codes_per_issue.values() if len(v) > 1)
    stored_vh = [a for a in rows if a.severity == "VERY_HIGH"]
    lowered = sum(1 for a in stored_vh if _policy_band(a) != "VERY_HIGH")
    _say("quality_alerts — duplicates and stored-vs-policy drift (live rows)")
    print(f"  issues with >1 registered code : {multi}")
    print(f"  stored VERY_HIGH rows          : {len(stored_vh)}")
    print(f"  ...lowered by the cap policy   : {lowered}")


def _conf_scope(db):
    q = db.query(ConfidenceScore.level, func.count(ConfidenceScore.id))
    q = exclude_disabled(db, q, ConfidenceScore)
    return q.group_by(ConfidenceScore.level).all()


def confidence_levels(db) -> None:
    """Confidence vocabulary: the same four words as rule severity, other meaning."""
    dist = dict(_conf_scope(db))
    total = sum(dist.values())
    _say("confidence_scores (per hospital-month, NOT a severity)")
    print(f"  total rows                : {total}")
    print("  level                     : " +
          " · ".join(f"{k}={v}" for k, v in sorted(dist.items())))
    print(f"  sum == total              : {sum(dist.values()) == total}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", default=None)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        quality_alerts(db, args.month)
        duplicates_and_staleness(db)
        validation_results(db, args.month)
        rule_variants(db, args.month)
        layered(db, args.month)
        layered_classification(db, args.month)
        confidence_levels(db)
        api_surfaces(db, args.month)
    finally:
        db.close()


if __name__ == "__main__":
    main()
