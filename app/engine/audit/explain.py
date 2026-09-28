"""Unified explanation engine — every derived number explains itself.

The drilldown "Why?" popup (static/js/explain.js) is fed by the single
dispatcher :func:`build_explanation` exposed through ``GET /audit/explain``.
Every explanation answers the same six questions:

1. **what**   — plain-language finding.
2. **where**  — hospital, indicator/rate, month, source dataset(s).
3. **why**    — the exact rule/threshold that fired (thresholds read LIVE
                from AppConfig so explanations never quote stale config).
4. **how**    — readable formula + the inputs used (inputs table).
5. **reproduce** — recompute the result from the stored inputs and compare
                with the persisted value (``verified`` flag). A user can
                independently reproduce every number (requirement ⑥).
6. **chain**  — Source Data → Validation → Calculation → Finding, with
                pointers into the existing audit endpoints (requirement ⑦).

Every explanation carries a **classification** (requirement ⑧):
``data_problem`` | ``statistical_finding`` | ``clinical_finding`` — so
poor-quality INPUT data is never presented as a performance finding, and
``data_problems`` lists the concrete issues found in the raw values.

All payloads are computed on demand from the database — no new cache and
no schema changes (consistent with the ghost doctrine: derived tables are
never trusted beyond their own persisted columns).
"""

from collections import Counter
from typing import Optional


def _data_epoch() -> Optional[str]:
    """Snapshot stamp carried on every explanation. Two responses with the
    same epoch were derived from exactly the same data — this is how the UI
    tells "stale view" from "stale analysis"."""
    try:
        from app.cache import get_data_epoch
        return get_data_epoch()
    except Exception:
        return None

from sqlalchemy.orm import Session

from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    IndicatorValue,
    QualityScore,
    Rule,
    ValidationResult,
)

CLASS_DATA = "data_problem"
CLASS_STAT = "statistical_finding"
CLASS_CLIN = "clinical_finding"

CLASS_BADGES = {
    CLASS_DATA: {"icon": "\U0001f527", "label": "Data problem"},
    CLASS_STAT: {"icon": "\U0001f4ca", "label": "Statistical finding"},
    CLASS_CLIN: {"icon": "\U0001f3e5", "label": "Clinical finding"},
}


# Component key → (QualityScore column, invert). outlier_score is stored as
# a penalty, so its inverted value (100−penalty) is what the detector and
# the sparkline plot — "worse" is always a lower value.
COMPONENT_COLUMNS = {
    "quality_score": ("score", False),
    "rule_compliance": ("rule_compliance", False),
    "completeness": ("completeness", False),
    "consistency": ("consistency", False),
    "outlier_score": ("outlier_penalty", True),
}


def _score_trend(db: Session, hospital_id: int, month: str, n: int = 6, component: str = "quality_score") -> list:
    """This hospital's last ≤n analyzed values of ONE quality component up to
    `month`, oldest first — rendered as a sparkline in the Why popup so
    anomaly rows are visible in context (drop vs drift vs stable). Same
    ghost doctrine: only months that actually have raw values behind them
    are included."""
    attr, invert = COMPONENT_COLUMNS.get(component, ("score", False))
    col = getattr(QualityScore, attr)
    try:
        from app.models import IndicatorValue as _IV
        rows = (
            db.query(QualityScore.month, col)
            .filter(
                QualityScore.hospital_id == hospital_id,
                QualityScore.month <= month,
                db.query(_IV.id).filter(
                    _IV.hospital_id == QualityScore.hospital_id,
                    _IV.month == QualityScore.month,
                ).exists(),
            )
            .order_by(QualityScore.month.desc())
            .limit(n)
            .all()
        )
        return [
            {"month": m, "score": round(100.0 - float(s) if invert else float(s), 1)}
            for m, s in reversed(rows)
            if s is not None
        ]
    except Exception:
        return []


def _indicator_name_map(db: Session) -> dict:
    return {i.id: i for i in db.query(Indicator).all()}


def _hospital(db: Session, hospital_id: int) -> Optional[Hospital]:
    return db.query(Hospital).filter(Hospital.id == hospital_id).first()


def _quality_config(db: Session) -> dict:
    from app.config_utils import get_config_dict
    cfg = get_config_dict(db, "quality")
    return {
        "weights": {
            "rule_compliance": float(cfg.get("quality_rule_compliance", 0.35)),
            "completeness": float(cfg.get("quality_completeness", 0.25)),
            "consistency": float(cfg.get("quality_consistency", 0.25)),
            "outlier_score": float(cfg.get("quality_outlier_penalty", 0.15)),
        },
        # Same targets the KPI cards and component-diagnostics use.
        "targets": {"rule_compliance": 85, "completeness": 90, "consistency": 85, "outlier_score": 90},
    }


def _zscore_threshold(db: Session) -> float:
    """Live z-score threshold — same resolution chain as the pipeline."""
    from app.config_utils import get_config_dict
    trends_cfg = get_config_dict(db, "trends")
    if "zscore_threshold" in trends_cfg:
        return float(trends_cfg["zscore_threshold"])
    rates_cfg = get_config_dict(db, "rates")
    if "zscore_threshold" in rates_cfg:
        return float(rates_cfg["zscore_threshold"])
    return float(get_config_dict(db, "thresholds").get("zscore_threshold", 2.5))


def _raw_values(db: Session, hospital_id: int, month: str):
    """All raw indicator values for one hospital-month, with provenance."""
    inds = _indicator_name_map(db)
    out = []
    for v in (
        db.query(IndicatorValue)
        .filter(IndicatorValue.hospital_id == hospital_id, IndicatorValue.month == month)
        .all()
    ):
        ind = inds.get(v.indicator_id)
        out.append({
            "indicator_id": v.indicator_id,
            "code": ind.code if ind else str(v.indicator_id),
            "name": ind.name if ind else None,
            "value": v.value,
            "source_file": v.source_file,
        })
    return out


def find_data_problems(values: list, db: Session = None) -> list:
    """Concrete problems in the raw values (requirement ①⑧).

    - negative or physically impossible values (counts < 0)
    - duplicate (code, value, source_file) rows — the same indicator
      uploaded twice for the same month
    - missing value (None) rows persisted for the month — EXCEPT indicators
      whose absence is already explained by a reported total (the sum-rule
      "covered" doctrine used by completeness: when the reported children
      already add up to the parent, an unreported sibling is "covered" and
      must NOT be flagged nor penalize completeness). Pass ``db`` to enable
      that gate; a None db keeps the legacy unconditional behaviour for
      callers that cannot reach the config tables.
    """
    # Resolve the human-readable name for each indicator code so the messages
    # answer "what is indicator 5?" without a lookup elsewhere. Codes are
    # unique per indicator, so the first name seen for a code is its name.
    names_by_code = {}
    for v in values:
        if v.get("name") and v.get("code") not in names_by_code:
            names_by_code[v["code"]] = v["name"]

    def _label(code: str) -> str:
        name = names_by_code.get(code)
        return f"{code} ({name})" if name else code

    # Covered-code gate (same doctrine as completeness): an indicator with a
    # persisted None row whose absence is explained by a reported total is a
    # non-event, not a data problem. Computed once for the whole batch.
    covered_codes: set = set()
    if db is not None:
        try:
            from app.engine.quality.rules import compute_covered_codes
            present = {
                v["code"]: v["value"]
                for v in values
                if v.get("value") is not None
            }
            if present:
                covered_codes = compute_covered_codes(present, set(), db) or set()
        except Exception:
            covered_codes = set()  # fail open: keep legacy behaviour

    problems = []
    seen = Counter()
    for v in values:
        val = v.get("value")
        if val is None:
            if v["code"] in covered_codes:
                continue  # absence explained by a reported total — not a problem
            problems.append({
                "kind": "missing_value",
                "severity": "high",
                "message": f"Indicator {_label(v['code'])} has no value for this month",
                "indicator_code": v["code"],
                "indicator_name": v.get("name"),
            })
            continue
        if val < 0:
            problems.append({
                "kind": "negative_value",
                "severity": "critical",
                "message": f"Indicator {_label(v['code'])} has a negative value ({val})",
                "indicator_code": v["code"],
                "indicator_name": v.get("name"),
            })
        seen[(v["code"], val, v.get("source_file"))] += 1
    for (code, val, src), n in seen.items():
        if n > 1:
            problems.append({
                "kind": "duplicate_row",
                "severity": "high",
                "message": f"Indicator {_label(code)} = {val} from '{src}' appears {n} times (uploaded more than once)",
                "indicator_code": code,
                "indicator_name": names_by_code.get(code),
            })
    return problems


# ─────────────────────────── quality score ───────────────────────────

def explain_quality_score(db: Session, hospital_id: int, month: str, component: str = "quality_score") -> dict:
    qs = (
        db.query(QualityScore)
        .filter(QualityScore.hospital_id == hospital_id, QualityScore.month == month)
        .first()
    )
    if not qs:
        return {"error": f"No quality score stored for hospital {hospital_id} / {month}"}
    hosp = _hospital(db, hospital_id)
    values = _raw_values(db, hospital_id, month)
    problems = find_data_problems(values, db)

    # Ghost gate: a QualityScore row without any raw values is a sentinel
    # for a month that was never analyzed — it must explain itself as a
    # data problem, never as "the hospital scored 0".
    if not values:
        return {
            "error": f"No indicator values stored for hospital {hospital_id} / {month}",
            "classification": CLASS_DATA,
            "what": "This month has a score row but no raw data behind it "
                    "(never analyzed or data was removed). The score is a placeholder, not a performance result.",
        }

    cfg = _quality_config(db)
    w = cfg["weights"]
    rc = float(qs.rule_compliance or 0)
    cp = float(qs.completeness or 0)
    co = float(qs.consistency or 0)
    op_inv = 100.0 - float(qs.outlier_penalty or 0)
    expected = round(rc * w["rule_compliance"] + cp * w["completeness"] + co * w["consistency"] + op_inv * w["outlier_score"], 2)
    stored = round(float(qs.score), 2)
    verified = abs(expected - stored) <= 0.05

    t = cfg["targets"]
    low_components = [
        {"component": name, "value": val, "target": t[key]}
        for name, key, val in (
            ("Rule compliance", "rule_compliance", rc),
            ("Completeness", "completeness", cp),
            ("Consistency", "consistency", co),
            ("Outlier score", "outlier_score", op_inv),
        ) if val < t[key]
    ]

    worst_comp = min(low_components, key=lambda c: c["value"] - c["target"]) if low_components else None
    inputs = [
        {"input": "Rule compliance", "value": rc, "role": "component (0-100)"},
        {"input": "Completeness", "value": cp, "role": "component (0-100)"},
        {"input": "Consistency", "value": co, "role": "component (0-100)"},
        {"input": "Outlier penalty (stored)", "value": float(qs.outlier_penalty or 0), "role": "component (0-100)"},
        {"input": "Weight: rule_compliance", "value": w["rule_compliance"], "role": "AppConfig quality.quality_rule_compliance"},
        {"input": "Weight: completeness", "value": w["completeness"], "role": "AppConfig quality.quality_completeness"},
        {"input": "Weight: consistency", "value": w["consistency"], "role": "AppConfig quality.quality_consistency"},
        {"input": "Weight: outlier_score", "value": w["outlier_score"], "role": "AppConfig quality.quality_outlier_penalty"},
    ]

    sources = sorted({v["source_file"] for v in values if v.get("source_file")})
    why = (
        f"{len(low_components)} component(s) below target; weakest: {worst_comp['component']} "
        f"({worst_comp['value']}% vs {worst_comp['target']}% target)" if worst_comp
        else "All components meet their targets — the score reflects good data quality"
    )
    if problems:
        why = f"{len(problems)} raw-data problem(s) detected; " + why

    payload = {
        "kind": "quality_score",
        "data_epoch": _data_epoch(),
        "hospital_id": hospital_id,
        "hospital": hosp.name if hosp else str(hospital_id),
        "month": month,
        "what": f"Data quality score {stored} for {month} — weighted mix of rule compliance, completeness, consistency and outlier score",
        "where": {
            "hospital_id": hospital_id,
            "hospital": hosp.name if hosp else str(hospital_id),
            "month": month,
            "source_files": sources,
            "raw_value_count": len(values),
        },
        "why": why,
        "how": {
            "formula": "score = rule_compliance×w_rc + completeness×w_cp + consistency×w_co + (100−outlier_penalty)×w_op",
            "formula_readable": "Weighted average of the four quality components; weights come from Settings (quality config)",
            "thresholds": cfg["targets"],
            "inputs": inputs,
        },
        "reproduce": {
            "formula_values": {
                "rule_compliance×w": round(rc * w["rule_compliance"], 4),
                "completeness×w": round(cp * w["completeness"], 4),
                "consistency×w": round(co * w["consistency"], 4),
                "outlier_inverted×w": round(op_inv * w["outlier_score"], 4),
            },
            "expected": expected,
            "stored": stored,
            "verified": verified,
        },
        "components_below_target": low_components,
        "classification": CLASS_DATA if problems else CLASS_STAT,
        "data_problems": problems,
        "component": component if component in COMPONENT_COLUMNS else "quality_score",
        "score_trend": _score_trend(db, hospital_id, month, component=component),
        "chain": [
            {"step": "Source Data", "detail": f"{len(values)} indicator values" + (f" from {len(sources)} file(s)" if sources else ""),
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Validation", "detail": "Business rules evaluated on the raw values",
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Calculation", "detail": "Four components scored 0-100 and weighted (formula above)",
             "endpoint": f"/audit/calculation-steps/{hospital_id}?month={month}"},
            {"step": "Finding", "detail": f"Score {stored} stored in quality_scores (row #{qs.id})"},
        ],
    }
    return payload


# ───────────────────────────── anomaly ───────────────────────────────

def explain_anomaly(
    db: Session,
    hospital_id: int,
    month: str,
    rate_name: Optional[str] = None,
    indicator_code: Optional[str] = None,
    anomaly_id: Optional[int] = None,
) -> dict:
    q = db.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == hospital_id, AnomalyResult.month == month
    )
    if anomaly_id is not None:
        q = q.filter(AnomalyResult.id == anomaly_id)
    if rate_name:
        q = q.filter(AnomalyResult.rate_name == rate_name)
    if indicator_code:
        q = q.filter(AnomalyResult.indicator_code == indicator_code)
    row = q.order_by(AnomalyResult.is_outlier.desc(), AnomalyResult.id.desc()).first()
    if not row:
        return {"error": f"No anomaly result for hospital {hospital_id} / {month}"
                         + (f" / {rate_name}" if rate_name else "")}
    hosp = _hospital(db, hospital_id)
    values = _raw_values(db, hospital_id, month)
    problems = find_data_problems(values, db)
    by_code = {v["code"]: v for v in values}

    z_thresh = _zscore_threshold(db)
    z = row.z_score
    is_peer_row = row.peer_count is not None
    # RATE_DEFINITIONS pairs the rate name with (numerator, denominator).
    from app.engine.anomaly.zscore import RATE_DEFINITIONS
    base_name = row.rate_name.replace(" (trend)", "")
    rate_def = next((d for d in RATE_DEFINITIONS if d[0] == base_name), None)
    num_code = rate_def[1] if rate_def else row.indicator_code
    den_code = rate_def[2] if rate_def else None

    # Indicator NAMES for the codes this anomaly touches (numerator,
    # denominator and the anomaly's own code). Resolved from the raw values
    # already fetched, falling back to the indicator map for codes with no
    # value row this month.
    inds = _indicator_name_map(db)

    def _name_for(code: Optional[str]) -> Optional[str]:
        if not code:
            return None
        v = by_code.get(code)
        if v and v.get("name"):
            return v["name"]
        for ind in inds.values():
            if ind.code == code:
                return ind.name
        return None

    row_name = _name_for(row.indicator_code)
    num_name = _name_for(num_code)
    den_name = _name_for(den_code)

    inputs = [{"input": "Value (rate)", "value": row.value, "role": "current hospital rate"}]
    if row.benchmark is not None:
        inputs.append({"input": "Benchmark", "value": row.benchmark, "role": "reference rate"})
    inputs.append({"input": "Z-score", "value": z, "role": "standard deviations from benchmark"})
    inputs.append({"input": "Z threshold", "value": z_thresh, "role": "AppConfig trends/thresholds.zscore_threshold"})

    if is_peer_row:
        inputs.append({"input": "Peer count", "value": row.peer_count, "role": "other hospitals in the benchmark"})
        inputs.append({"input": "Peer std", "value": row.peer_std, "role": "peer standard deviation"})
        inputs.append({"input": "Peer min / max", "value": f"{row.peer_min} – {row.peer_max}", "role": "peer range"})
        inputs.append({"input": "Peer median", "value": row.peer_median, "role": "peer median"})
        if row.peers_detail:
            for p in row.peers_detail[:10]:
                inputs.append({"input": f"Peer: {p.get('hospital')}", "value": p.get("rate"), "role": "peer rate"})
        formula = "rate = numerator/denominator×100;  z = (rate − peer_mean) / peer_std  (hospital excluded from its own benchmark)"
    else:
        formula = "rate = numerator/denominator×100;  z = (rate − historical_mean) / historical_std  (trend anomaly)"

    num_v = by_code.get(num_code, {}).get("value")
    den_v = by_code.get(den_code, {}).get("value") if den_code else None
    if den_code:
        inputs.append({"input": f"Raw numerator ({num_code} — {num_name})" if num_name else f"Raw numerator ({num_code})",
                       "value": num_v, "role": "from uploaded data"})
        inputs.append({"input": f"Raw denominator ({den_code} — {den_name})" if den_name else f"Raw denominator ({den_code})",
                       "value": den_v, "role": "from uploaded data"})

    if is_peer_row and row.peer_count is not None and row.peer_count < 3:
        problems.append({
            "kind": "small_peer_group",
            "severity": "medium",
            "message": f"Only {row.peer_count} peer hospital(s) — the benchmark is statistically fragile",
        })

    data_problem_flags = [p for p in problems]
    if row.value is not None and num_v is not None and den_v is not None and den_v:
        expected_rate = round(num_v / den_v * 100, 2)
    else:
        expected_rate = None

    if row.value is not None and z is not None and is_peer_row and row.peer_std not in (None, 0) and row.benchmark is not None:
        # Reproduce the z from the FULL-PRECISION benchmark the pipeline used.
        # The stored benchmark/std columns are rounded to 2dp; recomputing
        # z = (value − rounded_benchmark) / rounded_std from them produced
        # false "Not verified" verdicts (e.g. Neonatal mortality rate: stored
        # z 20.82 vs 20.35 from rounded inputs). peers_detail carries the
        # unrounded peer rates, so recompute mean/std from it; fall back to
        # the rounded columns only when the detail list is missing.
        peer_rates_full = [float(p.get("rate")) for p in (row.peers_detail or []) if p.get("rate") is not None]
        if len(peer_rates_full) >= 2:
            mean_full = sum(peer_rates_full) / len(peer_rates_full)
            variance = sum((x - mean_full) ** 2 for x in peer_rates_full) / (len(peer_rates_full) - 1)  # ddof=1 like the pipeline
            std_full = variance ** 0.5
            if std_full:
                expected_z = round((float(row.value) - mean_full) / std_full, 2)
            else:
                expected_z = None
        else:
            expected_z = round((float(row.value) - float(row.benchmark)) / float(row.peer_std), 2)
        # z_verified=True requires BOTH the value-rate check and the z check to
        # reproduce; a rounded-rate mismatch must not poison the z verdict
        # (see value_verified below).
        z_verified = expected_z is not None and abs(expected_z - float(z)) <= 0.05
    else:
        expected_z = None
        z_verified = None

    # Independent check of the RATE itself from the raw numerator/denominator.
    # Rounded peers rates can legitimately shift the 2nd decimal, so allow a
    # small display-rounding tolerance rather than the exact-match used for z.
    if expected_rate is not None and row.value is not None:
        value_verified = abs(expected_rate - float(row.value)) <= 0.05
    else:
        value_verified = None

    classification = CLASS_DATA if data_problem_flags else CLASS_CLIN
    what = (
        f"{row.rate_name} is {'an outlier' if row.is_outlier else 'within normal range'}: "
        f"value {row.value} vs benchmark {row.benchmark} (z={z})"
    )
    if row.is_outlier and z is not None:
        direction = "above" if float(z) > 0 else "below"
        why = f"|z| = {abs(float(z)):.2f} exceeds the {z_thresh} threshold → flagged as outlier (rate {direction} the benchmark)"
    elif row.is_outlier:
        why = f"Flagged by the anomaly detection pipeline (trend/regression rule) with z={z}, threshold {z_thresh}"
    else:
        why = f"|z| = {abs(float(z)):.2f} is within the {z_thresh} threshold → not an outlier"

    return {
        "kind": "anomaly",
        "anomaly_id": row.id,
        "data_epoch": _data_epoch(),
        "hospital_id": hospital_id,
        "hospital": hosp.name if hosp else str(hospital_id),
        "month": month,
        "what": what,
        "where": {
            "hospital_id": hospital_id,
            "hospital": hosp.name if hosp else str(hospital_id),
            "month": month,
            "rate_name": row.rate_name,
            "indicator_code": row.indicator_code,
            "indicator_name": row_name,
            "source_files": sorted({v["source_file"] for v in values if v.get("source_file")}),
        },
        "why": why,
        "how": {
            "formula": formula,
            "formula_readable": (
                f"{base_name} = ({num_code} — {num_name}) / ({den_code} — {den_name}) × 100"
                if den_code and num_name and den_name else
                f"{base_name} = ({num_code}) / ({den_code}) × 100" if den_code else row.rate_name
            ),
            "thresholds": {"zscore_threshold": z_thresh},
            "inputs": inputs,
        },
        "reproduce": {
            "expected_rate": expected_rate,
            "expected_z": expected_z,
            "stored_z": z,
            "value_verified": value_verified,
            "verified": z_verified,
            "note": None if expected_rate is not None
            else "Raw numerator/denominator missing — rate cannot be reproduced from stored values",
        },
        "is_outlier": bool(row.is_outlier),
        "classification": classification,
        "data_problems": data_problem_flags,
        "chain": [
            {"step": "Source Data", "detail": (
                f"{num_code} ({num_name}) and {den_code} ({den_name}) raw values from uploaded files"
                if num_name and den_name else
                f"{num_code} and {den_code} raw values from uploaded files"),
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Validation", "detail": "Zero-denominator and range checks run before rate computation",
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Calculation", "detail": formula,
             "endpoint": f"/audit/benchmark/{hospital_id}?month={month}"},
            {"step": "Finding", "detail": f"Anomaly row #{row.id} (outlier={row.is_outlier})",
             "endpoint": f"/analysis/outliers?hospital_id={hospital_id}&month={month}"},
        ],
    }


# ───────────────────────── heatmap cell ──────────────────────────────

def explain_heatmap_cell(db: Session, hospital_id: int, month: str) -> dict:
    """Heatmap cell = hospital-month quality score + data-problem sweep."""
    result = explain_quality_score(db, hospital_id, month)
    if result.get("kind") == "quality_score":
        result["kind"] = "heatmap_cell"
    return result


# ──────────────────────────── rule ───────────────────────────────────

def explain_rule(db: Session, hospital_id: int, month: str, rule_code: str) -> dict:
    vr = (
        db.query(ValidationResult)
        .filter(
            ValidationResult.hospital_id == hospital_id,
            ValidationResult.month == month,
            ValidationResult.rule_code == rule_code,
        )
        .order_by(ValidationResult.id.desc())
        .first()
    )
    if not vr:
        return {"error": f"No validation result for rule {rule_code} / hospital {hospital_id} / {month}"}
    rule = db.query(Rule).filter(Rule.code == rule_code).first()
    hosp = _hospital(db, hospital_id)
    values = _raw_values(db, hospital_id, month)
    problems = find_data_problems(values, db)

    return {
        "kind": "rule",
        "rule_code": rule_code,
        "data_epoch": _data_epoch(),
        "hospital_id": hospital_id,
        "hospital": hosp.name if hosp else str(hospital_id),
        "month": month,
        "what": f"Rule {rule_code} {'FAILED' if vr.status == 'FAIL' else 'passed'}: {vr.rule_description}",
        "where": {
            "hospital_id": hospital_id,
            "hospital": hosp.name if hosp else str(hospital_id),
            "month": month,
            "rule_code": rule_code,
            "source_files": sorted({v["source_file"] for v in values if v.get("source_file")}),
        },
        "why": vr.details or f"Rule evaluated to {vr.status}",
        "how": {
            "formula": rule.name if rule else rule_code,
            "formula_readable": rule.description if rule else vr.rule_description,
            "thresholds": {
                "severity": vr.severity,
                "rule_type": vr.rule_type,
                "params": (rule.params if rule else None),
            },
            "inputs": [
                {"input": "Rule status", "value": vr.status, "role": "evaluation outcome"},
                {"input": "Severity", "value": vr.severity, "role": "impact weight in the score"},
                {"input": "Details", "value": vr.details, "role": "rule message"},
            ],
        },
        "reproduce": {
            "note": "Open the Rules Manager → Rule Test to re-run this rule against the month's raw values.",
            "verified": None,
        },
        "classification": CLASS_DATA if vr.rule_type == "LOGIC" and problems else CLASS_CLIN,
        "data_problems": problems,
        "chain": [
            {"step": "Source Data", "detail": f"{len(values)} raw values",
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Validation", "detail": f"Rule {rule_code} ({vr.rule_type}) evaluated → {vr.status}",
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Finding", "detail": vr.rule_description},
        ],
    }


# ───────────────────── month-level aggregate ─────────────────────

def explain_month_overview(db: Session, month: str) -> dict:
    """Aggregate explanation for a trend point / month column where no single
    hospital is selected: what the month looks like across hospitals, which
    hospitals drag it down, and the data problems driving that."""
    from collections import defaultdict
    scores = (
        db.query(QualityScore)
        .filter(QualityScore.month == month)
        .all()
    )
    active = {h.id: h for h in db.query(Hospital).filter(Hospital.is_active.is_(True)).all()}
    scored = [s for s in scores if s.hospital_id in active]
    analyzed_hids = {
        r[0] for r in db.query(IndicatorValue.hospital_id).filter(IndicatorValue.month == month).distinct().all()
    }
    real = [s for s in scored if s.hospital_id in analyzed_hids]
    if not real:
        return {"error": f"No analyzed hospitals for {month}"}

    values = sorted(float(s.score) for s in real)
    avg = round(sum(values) / len(values), 1)
    weakest = sorted(real, key=lambda s: float(s.score))[:5]
    problems = []
    for s in weakest:
        hv = _raw_values(db, s.hospital_id, month)
        for p in find_data_problems(hv, db):
            problems.append({**p, "hospital": active[s.hospital_id].name})

    return {
        "kind": "month_overview",
        "data_epoch": _data_epoch(),
        "month": month,
        "what": f"Average quality score {avg} across {len(real)} analyzed hospitals for {month}",
        "where": {"month": month, "hospitals_count": len(real)},
        "why": (
            f"Range {values[0]}–{values[-1]}; weakest: "
            + ", ".join(f"{active[s.hospital_id].name} ({float(s.score)})" for s in weakest[:3])
        ),
        "how": {
            "formula": "average(quality_scores.score for analyzed hospitals of the month)",
            "formula_readable": "Simple average of the stored quality scores of hospitals with real data this month (ghost months excluded)",
            "thresholds": {},
            "inputs": [
                {"input": active[s.hospital_id].name, "value": float(s.score), "role": "hospital quality score"}
                for s in sorted(real, key=lambda s: float(s.score))[:10]
            ],
        },
        "reproduce": {
            "expected": avg,
            "stored": avg,
            "verified": True,
            "note": "Recomputed live from the stored per-hospital scores — identical by construction.",
        },
        "weakest_hospitals": [
            {"hospital_id": s.hospital_id, "hospital": active[s.hospital_id].name,
             "score": float(s.score),
             "why_query": {"kind": "quality_score", "hospital_id": s.hospital_id, "month": month}}
            for s in weakest
        ],
        "classification": CLASS_DATA if problems else CLASS_STAT,
        "data_problems": problems,
        "chain": [
            {"step": "Source Data", "detail": f"{len(analyzed_hids)} hospitals with raw values in {month}",
             "endpoint": f"/audit/data-auditor/{weakest[0].hospital_id}?month={month}"},
            {"step": "Calculation", "detail": "Per-hospital quality scores averaged", "endpoint": None},
            {"step": "Finding", "detail": f"Month average {avg}"},
        ],
    }


# ─────────────────────────── dispatcher ──────────────────────────────

def build_explanation(
    db: Session,
    kind: str,
    hospital_id: Optional[int],
    month: str,
    rate_name: Optional[str] = None,
    indicator_code: Optional[str] = None,
    rule_code: Optional[str] = None,
    component: Optional[str] = None,
) -> dict:
    # Aggregate month explanation — no hospital selected (trend point with
    # "All Hospitals", or the month column itself).
    if kind in ("quality_score", "heatmap_cell") and hospital_id is None:
        return explain_month_overview(db, month)
    if hospital_id is None:
        return {"error": "hospital_id is required for this explanation kind"}
    if kind == "quality_score":
        return explain_quality_score(db, hospital_id, month, component=component or "quality_score")
    if kind == "anomaly":
        return explain_anomaly(db, hospital_id, month, rate_name=rate_name, indicator_code=indicator_code)
    if kind == "heatmap_cell":
        return explain_heatmap_cell(db, hospital_id, month)
    if kind == "rule":
        if not rule_code:
            return {"error": "kind=rule requires rule_code"}
        return explain_rule(db, hospital_id, month, rule_code)
    return {"error": f"Unknown explanation kind: {kind!r}"}
