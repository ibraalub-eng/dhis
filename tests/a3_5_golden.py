"""P0 deterministic reference harness for A3.5 (Rules snapshot integration).

Captures the configuration-sensitive analytical outputs for three reference
cases over two hospitals and four months:

* ``default``  — no stored rule settings (documented defaults only),
* ``stored``   — all five rule settings stored with non-default values,
* ``partial``  — only ``eq_tolerance`` stored, the other four missing.

The outputs cover Rules (stored ValidationResult rows), Quality Score, Trends,
Confidence, the Dashboard completeness KPI, Diagnostics coverage, and the
Alert run gate. Every case records the effective resolved settings, so a
reviewer can see which values produced which numbers.

Fixtures live in ``tests/fixtures/``; no production database, file or record is
read or written. The harness is import-safe for pytest: it only defines
helpers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from app.engine import pipeline
from app.engine.anomaly import trends as trends_engine
from app.engine.quality import compute_covered_codes
from app.models import (
    AppConfig,
    ConfidenceScore,
    Hospital,
    Indicator,
    IndicatorValue,
    QualityAlert,
    QualityScore,
    ValidationResult,
)

FIXTURE = Path(__file__).with_name("fixtures") / "a3_5_golden_master.json"

MONTHS = ("2032-10", "2032-11", "2032-12", "2033-01")
LATEST = MONTHS[-1]

HOSPITAL_A = "General Hospital"
HOSPITAL_B = "Central Medical"

#: Hospital A: a stable series, then a >2x jump in the latest month (R051) and
#: a perfectly reconciling total (R002 PASS).
A_SERIES = {
    "2032-10": {"2": 200, "2.a": 90, "2.b": 110, "3": 140, "4": 20, "5": 40,
                "6": 195, "7": 4, "10": 6, "10.a": 3, "11": 1, "16": 5, "17": 2},
    "2032-11": {"2": 210, "2.a": 95, "2.b": 115, "3": 145, "4": 20, "5": 45,
                "6": 200, "7": 4, "10": 6, "10.a": 3, "11": 0, "16": 5, "17": 2},
    "2032-12": {"2": 205, "2.a": 100, "2.b": 105, "3": 140, "4": 25, "5": 40,
                "6": 198, "7": 5, "10": 7, "10.a": 4, "11": 1, "16": 6, "17": 2},
    "2033-01": {"2": 430, "2.a": 200, "2.b": 230, "3": 280, "4": 40, "5": 110,
                "6": 400, "7": 8, "10": 12, "10.a": 6, "11": 1, "16": 10, "17": 3},
}

#: Hospital B: latest month total is off by 5 (R002), so the stored
#: ``eq_tolerance`` changes the outcome.
B_SERIES = {
    "2032-10": {"2": 100, "2.a": 50, "2.b": 50, "3": 70, "4": 10, "5": 20,
                "6": 96, "7": 3, "10": 5, "10.a": 2, "11": 0, "16": 4, "17": 1},
    "2032-11": {"2": 102, "2.a": 52, "2.b": 50, "3": 72, "4": 10, "5": 20,
                "6": 98, "7": 3, "10": 5, "10.a": 2, "11": 0, "16": 4, "17": 1},
    "2032-12": {"2": 101, "2.a": 51, "2.b": 50, "3": 71, "4": 10, "5": 20,
                "6": 97, "7": 3, "10": 5, "10.a": 2, "11": 0, "16": 4, "17": 1},
    "2033-01": {"2": 105, "2.a": 60, "2.b": 40, "3": 74, "4": 11, "5": 20,
                "6": 99, "7": 4, "10": 5, "10.a": 2, "11": 0, "16": 4, "17": 1},
}

CASES: Dict[str, Dict[str, str]] = {
    "default": {},
    "stored": {
        "eq_tolerance": "10.0",
        "month_over_factor": "3.0",
        "month_under_factor": "0.4",
        "maternal_over_factor": "5.0",
        "neonatal_over_factor": "3.5",
    },
    "partial": {"eq_tolerance": "10.0"},
}


# ── seeding ────────────────────────────────────────────────────────────────


def seed(db) -> List[Hospital]:
    """Two hospitals, four months of values, no analysis rows yet."""
    hospitals = (
        db.query(Hospital).filter(Hospital.name.in_([HOSPITAL_A, HOSPITAL_B]))
        .order_by(Hospital.id).all()
    )
    assert len(hospitals) == 2, "the shared fixture must seed both hospitals"
    indicator_ids = {
        code: iid for iid, code in db.query(Indicator.id, Indicator.code).all()
    }
    for hospital, series in ((hospitals[0], A_SERIES), (hospitals[1], B_SERIES)):
        for month, values in series.items():
            for code, value in values.items():
                iid = indicator_ids.get(code)
                if iid is None:
                    continue
                db.add(IndicatorValue(hospital_id=hospital.id, indicator_id=iid,
                                      month=month, value=float(value)))
    db.commit()
    return list(hospitals)


def _clear_analysis(db, hospitals: List[Hospital]) -> None:
    ids = [h.id for h in hospitals]
    for model in (ValidationResult, QualityScore, ConfidenceScore, QualityAlert):
        db.query(model).filter(model.hospital_id.in_(ids)).delete(
            synchronize_session=False)
    db.commit()


def _apply_case(db, name: str) -> None:
    """Reset stored settings, then apply this case's rows (and only its rows)."""
    db.query(AppConfig).filter(AppConfig.category == "rules").delete(
        synchronize_session=False)
    for key, value in CASES[name].items():
        db.add(AppConfig(key=key, value=value, category="rules", label=key))
    # Deterministic: the auto-scan is A3.4's run gate, not a rules input.
    row = db.query(AppConfig).filter(AppConfig.key == "alerts_auto_scan").first()
    if row is None:
        db.add(AppConfig(key="alerts_auto_scan", value="0",
                         category="alerts", label="auto-scan"))
    else:
        row.value = "0"
    db.commit()


# ── capture ────────────────────────────────────────────────────────────────


def _effective_settings(db) -> Dict[str, float]:
    from app.engine.config_resolver import load_policy_snapshot

    snapshot = load_policy_snapshot(db)
    keep = [key for key in snapshot.values
            if key.startswith("rules.")
            or key in ("trend_finding_deviation", "severity.zscore_threshold",
                       "confidence.high", "confidence.medium",
                       "confidence.low")
            or key.startswith("confidence.weight.")]
    return {key: snapshot.values[key] for key in sorted(keep)}


def _rules(db, hospital_id: int, month: str) -> Dict[str, list]:
    rows = (db.query(ValidationResult)
            .filter(ValidationResult.hospital_id == hospital_id,
                    ValidationResult.month == month)
            .order_by(ValidationResult.rule_code).all())
    return {r.rule_code: [r.status, r.details or ""] for r in rows}


def _quality(db, hospital_id: int, month: str) -> dict:
    row = (db.query(QualityScore)
           .filter(QualityScore.hospital_id == hospital_id,
                   QualityScore.month == month)
           .order_by(QualityScore.id.desc()).first())
    if row is None:
        return {}
    return {
        "score": round(float(row.score), 6),
        "rule_compliance": None if row.rule_compliance is None else round(float(row.rule_compliance), 6),
        "completeness": None if row.completeness is None else round(float(row.completeness), 6),
        "consistency": None if row.consistency is None else round(float(row.consistency), 6),
        "outlier_penalty": None if row.outlier_penalty is None else round(float(row.outlier_penalty), 6),
        "issues": row.issues or "",
    }


def _confidence(db, hospital_id: int, month: str) -> dict:
    row = (db.query(ConfidenceScore)
           .filter(ConfidenceScore.hospital_id == hospital_id,
                   ConfidenceScore.month == month)
           .order_by(ConfidenceScore.id.desc()).first())
    if row is None:
        return {}
    return {
        "overall": round(float(row.overall_confidence), 6),
        "level": row.level,
        "counts": [row.indicator_count, row.high_count, row.medium_count,
                   row.low_count, row.critical_count],
    }


def _monthly_data(db, hospital_id: int) -> Dict[str, Dict[str, float]]:
    rows = (db.query(Indicator.code, IndicatorValue.month, IndicatorValue.value)
            .join(Indicator, Indicator.id == IndicatorValue.indicator_id)
            .filter(IndicatorValue.hospital_id == hospital_id,
                    IndicatorValue.month.in_(MONTHS))
            .all())
    data: Dict[str, Dict[str, float]] = {}
    for code, month, value in rows:
        if value is not None:
            data.setdefault(month, {})[code] = float(value)
    return data


def _trends(db, hospital: Hospital) -> list:
    from app.config_utils import get_config_dict

    results = trends_engine.analyze_historical_trends(
        hospital.name, _monthly_data(db, hospital.id),
        config=get_config_dict(db, "trends"))
    return [
        [r.indicator_code, r.trend_direction, r.trend_severity,
         bool(r.is_significant), int(r.consecutive_count), len(r.findings)]
        for r in sorted(results, key=lambda x: (x.indicator_code, x.rate_name))
    ]


def _rules_policy_if_supported(db):
    """Pre-P1 code has no *rules* argument; post-P1 passes the stored policy."""
    try:
        from app.engine.config_resolver import load_display_policy
        from app.engine.policy_view import rules_policy_from_snapshot
    except ImportError:  # pragma: no cover - only while capturing the baseline
        return None
    return rules_policy_from_snapshot(load_display_policy(db))


def _coverage(db, hospital_id: int, month: str) -> list:
    from app.engine.pipeline import get_enabled_values_for_hospital_month

    values = get_enabled_values_for_hospital_month(db, hospital_id, month)
    policy = _rules_policy_if_supported(db)
    if policy is None:  # pragma: no cover
        covered = compute_covered_codes(values, set(), db)
    else:
        covered = compute_covered_codes(values, set(), db, rules=policy)
    return sorted(covered)


def _completeness(db, hospital_id: int, month: str) -> float:
    policy = _rules_policy_if_supported(db)
    try:
        value = pipeline.compute_hospital_completeness(
            db, hospital_id, month, auto_disable_null=False, rules=policy)
    except TypeError:  # pragma: no cover - only while capturing the baseline
        value = pipeline.compute_hospital_completeness(
            db, hospital_id, month, auto_disable_null=False)
    return round(float(value), 6)


def capture_case(db, name: str, hospitals: List[Hospital]) -> dict:
    _apply_case(db, name)
    out: dict = {"settings": _effective_settings(db), "hospitals": {}}
    for hospital in hospitals:
        result = pipeline.run_full_analysis(db, hospital.id, LATEST, force=True)
        out["hospitals"][hospital.name] = {
            "run": {
                "score": result.get("data_quality_score"),
                "issues": sorted(result.get("issues") or []),
            },
            "rules": _rules(db, hospital.id, LATEST),
            "quality": _quality(db, hospital.id, LATEST),
            "confidence": _confidence(db, hospital.id, LATEST),
            "coverage": _coverage(db, hospital.id, LATEST),
            "completeness": _completeness(db, hospital.id, LATEST),
            "trends": _trends(db, hospital),
            "alert_rows": db.query(QualityAlert).filter(
                QualityAlert.hospital_id == hospital.id,
                QualityAlert.month == LATEST).count(),
        }
    return out


def capture_all(db) -> dict:
    hospitals = seed(db)
    _clear_analysis(db, hospitals)
    return {name: capture_case(db, name, hospitals) for name in CASES}


def dump(capture: dict) -> str:
    return json.dumps(capture, indent=2, sort_keys=True, ensure_ascii=False)
