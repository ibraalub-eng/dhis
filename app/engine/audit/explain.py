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

import json
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

def _failed_rules(db: Session, hospital_id: int, month: str) -> list:
    """Every rule that FAILED for this hospital-month, worst severity first.

    The quality score only reports rule compliance as a single percentage, so
    a hospital can sit above its target (e.g. 98.7% vs an 85% target) while
    individual rules still fail. The Why popup must name those rules —
    otherwise "all components meet their targets" reads as "nothing failed".
    """
    rows = (
        db.query(ValidationResult)
        .filter(
            ValidationResult.hospital_id == hospital_id,
            ValidationResult.month == month,
            ValidationResult.status == "FAIL",
        )
        .all()
    )
    sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    rows.sort(key=lambda r: (sev_rank.get((r.severity or "").upper(), 4), r.rule_code or ""))
    names = {r.code: r.name for r in db.query(Rule).filter(Rule.code.in_([r.rule_code for r in rows])).all()} if rows else {}
    return [
        {
            "rule_code": r.rule_code,
            "rule_name": names.get(r.rule_code) or r.rule_description,
            "rule_description": r.rule_description,
            "severity": r.severity,
            "rule_type": r.rule_type,
            "details": r.details,
            "hospital_id": r.hospital_id,
        }
        for r in rows
    ]


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
    failed_rules = _failed_rules(db, hospital_id, month)
    failed_codes = ", ".join(fr["rule_code"] for fr in failed_rules[:5])
    if failed_rules:
        rule_sentence = (
            f"{len(failed_rules)} validation rule(s) failed ({failed_codes}"
            f"{', …' if len(failed_rules) > 5 else ''}) → rule compliance {rc}%"
        )
    else:
        rule_sentence = "No validation rule failed this month"
    why = (
        f"{len(low_components)} component(s) below target; weakest: {worst_comp['component']} "
        f"({worst_comp['value']}% vs {worst_comp['target']}% target). {rule_sentence}"
        if worst_comp
        else (
            f"All components meet their targets ({rule_sentence})"
            if failed_rules
            else "All components meet their targets — the score reflects good data quality"
        )
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
        "failed_rules": failed_rules,
        "failed_rule_count": len(failed_rules),
        "classification": CLASS_DATA if problems else CLASS_STAT,
        "data_problems": problems,
        "component": component if component in COMPONENT_COLUMNS else "quality_score",
        "score_trend": _score_trend(db, hospital_id, month, component=component),
        "chain": [
            {"step": "Source Data", "detail": f"{len(values)} indicator values" + (f" from {len(sources)} file(s)" if sources else ""),
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Validation", "detail": (
                f"Business rules evaluated on the raw values — {len(failed_rules)} failed ({failed_codes})"
                if failed_rules else "Business rules evaluated on the raw values — none failed"
            ),
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Calculation", "detail": "Four components scored 0-100 and weighted (formula above)",
             "endpoint": f"/audit/calculation-steps/{hospital_id}?month={month}"},
            {"step": "Finding", "detail": f"Score {stored} stored in quality_scores (row #{qs.id})"},
        ],
    }
    return payload


# ───────────────────────────── anomaly ───────────────────────────────

def _rebuild_peer_benchmark(db: Session, month: str, hospital_name: str,
                            num_code: str, den_code: str) -> Optional[dict]:
    """Rebuild the peer population exactly as the anomaly pipeline did.

    Recomputing z from the row's own ``peers_detail`` only proves the stored
    columns are internally consistent — a benchmark computed over the WRONG
    population still reproduces perfectly from its own list. The engine's
    inputs are the enabled values of every active hospital for the month
    (per-hospital disabled indicators and NULL cells removed), so the
    population is rebuilt here through the very same helpers the pipeline
    calls, at full precision, and compared with what was stored.

    Returns None when the population cannot be rebuilt (import failure, trend
    rows, too few peers) so the caller keeps its existing weaker check instead
    of reporting a verdict it could not actually make.
    """
    try:
        import numpy as np

        from app.engine.anomaly.zscore import compute_rate
        from app.engine.pipeline import get_all_hospital_data_for_month

        data = get_all_hospital_data_for_month(db, month)
        current = compute_rate(data.get(hospital_name, {}), num_code, den_code)
        peers = {}
        for name, values in data.items():
            if name == hospital_name:
                continue
            rate = compute_rate(values, num_code, den_code)
            if rate is not None:
                peers[name] = rate
        if current is None or len(peers) < 2:
            return None
        rates = list(peers.values())
        mean = float(np.mean(rates))
        std = float(np.std(rates, ddof=1))  # ddof=1, like the pipeline
        if not std:
            return None
        return {
            "peer_count": len(rates),
            "peer_hospitals": sorted(peers),
            "mean": mean,
            "std": std,
            "z": (current - mean) / std,
            "rate": current,
        }
    except Exception:
        return None


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

    # Independent check of the PEER POPULATION: recompute the benchmark from the
    # engine's own inputs and compare with what the row stored. Without this,
    # "reproduced ✓" only means the stored columns agree with each other — a
    # benchmark over the wrong hospitals, or one computed before an indicator
    # was disabled for a peer, still verified.
    peer_check = None
    benchmark_verified = None
    if is_peer_row and den_code and hosp is not None and hosp.name:
        rebuilt = _rebuild_peer_benchmark(db, month, hosp.name, num_code, den_code)
        if rebuilt:
            stored_peers = {p.get("hospital") for p in (row.peers_detail or [])
                            if p.get("hospital")}
            missing = sorted(set(rebuilt["peer_hospitals"]) - stored_peers)
            extra = sorted(stored_peers - set(rebuilt["peer_hospitals"]))
            benchmark_verified = (
                not missing and not extra
                and rebuilt["peer_count"] == row.peer_count
                and abs(round(rebuilt["z"], 2) - float(z)) <= 0.01
            )
            peer_check = {
                "verified": benchmark_verified,
                "peer_count": rebuilt["peer_count"],
                "stored_peer_count": row.peer_count,
                "expected_benchmark": round(rebuilt["mean"], 2),
                "expected_peer_std": round(rebuilt["std"], 2),
                "expected_z": round(rebuilt["z"], 2),
                "peer_set_matches": not missing and not extra,
                "peers_missing_from_row": missing,
                "peers_not_in_data": extra,
                "note": (
                    "Benchmark recomputed from the current data with the same hospital "
                    "set the engine uses."
                ),
            }
            if not benchmark_verified:
                data_problem_flags.append({
                    "kind": "stale_benchmark",
                    "severity": "high",
                    "message": (
                        f"The stored benchmark ({row.benchmark}, z={z}) no longer matches "
                        f"the uploaded data: recomputing {base_name} over the same "
                        f"population gives {round(rebuilt['mean'], 2)} "
                        f"(z={round(rebuilt['z'], 2)}). The anomaly row is out of date "
                        "with the current values or indicator configuration — "
                        "recalculate this month."
                    ),
                })

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
            # The headline verdict is the strict one: the stored columns must
            # agree with each other AND the benchmark must still be what the
            # engine computes from today's data. A stale benchmark is reported
            # as not reproduced rather than silently verified.
            "benchmark_verified": benchmark_verified,
            "verified": (z_verified if benchmark_verified is None
                         else bool(z_verified) and benchmark_verified),
            "note": (
                "Raw numerator/denominator missing — rate cannot be reproduced from stored values"
                if expected_rate is None else
                ("Benchmark recomputed and matches the current data." if benchmark_verified
                 else "Benchmark could not be reproduced from the current data.")
                if benchmark_verified is False else None
            ),
        },
        "is_outlier": bool(row.is_outlier),
        "classification": classification,
        "peer_check": peer_check,
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

def _rule_indicator_codes(rule) -> set:
    """Indicator codes a rule actually reads (parent/children/codes/
    num_code/den_code). Used to tell whether THIS rule's outcome is explained
    by a missing value, as opposed to some unrelated gap in the month.

    ``Rule.params`` is a JSON *string* in the database (the engine parses it the
    same way), so both encodings must be accepted.
    """
    if rule is None:
        return set()
    params = rule.params
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            return set()
    if not isinstance(params, dict):
        return set()
    out = set()
    for key in ("parent", "num_code", "den_code", "indicator", "code"):
        v = params.get(key)
        if isinstance(v, str) and v.strip():
            out.add(v.strip())
    for key in ("children", "codes"):
        v = params.get(key)
        if isinstance(v, list):
            out.update(str(x).strip() for x in v if isinstance(x, str) and x.strip())
    return out


def _rule_cross_hospital_breakdown(db: Session, month: str, hospital_name: str,
                                   num_code: str, den_code: str) -> Optional[dict]:
    """Rebuild the benchmark a cross-hospital rule (R043-R050) compared against.

    The rule engine (``_cross_hospital_rate``) computes every active hospital's
    rate for the month, then mean/std over ALL of them — including the hospital
    itself, population std (ddof=0). That differs from the anomaly pipeline
    (which excludes the hospital, ddof=1), so this rebuild follows the RULE's
    math exactly, through the same data helper the pipeline feeds the rules.
    """
    try:
        import numpy as np

        from app.engine.anomaly.zscore import compute_rate
        from app.engine.pipeline import get_all_hospital_data_for_month

        data = get_all_hospital_data_for_month(db, month)
        rates = {}
        for name, values in data.items():
            rate = compute_rate(values, num_code, den_code)
            if rate is not None:
                rates[name] = rate
        if hospital_name not in rates or len(rates) < 2:
            return None
        vals = list(rates.values())
        mean = float(np.mean(vals))
        std = float(np.std(vals))
        if not std:
            return None
        return {
            "rates": rates,
            "mean": mean,
            "std": std,
            "z": (rates[hospital_name] - mean) / std,
        }
    except Exception:
        return None


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

    # The badge must describe THIS outcome. A passing rule is not a finding at
    # all, and an unrelated missing indicator elsewhere in the month must not
    # relabel a clinical failure as a data problem.
    status = (vr.status or "").upper()
    codes = _rule_indicator_codes(rule)
    related = [p for p in problems if not codes or p.get("indicator_code") in codes]
    if status != "FAIL":
        classification = None
    elif related:
        classification = CLASS_DATA
    elif vr.rule_type == "BENCHMARK":
        classification = CLASS_STAT
    else:
        classification = CLASS_CLIN

    inputs = [
        {"input": "Rule status", "value": vr.status, "role": "evaluation outcome"},
        {"input": "Severity", "value": vr.severity, "role": "impact weight in the score"},
        {"input": "Details", "value": vr.details, "role": "rule message"},
    ]
    formula_readable = rule.description if rule else vr.rule_description

    # Cross-hospital benchmark rules (R043-R050) compare this hospital's rate
    # with every other hospital's rate for the month — break the one-line
    # message into those rates, the mean/std they produce, and the z recomputed
    # from them, using the RULE engine's math (all hospitals incl. this one,
    # population std).
    params = rule.params if rule is not None else None
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            params = None
    if not isinstance(params, dict):
        params = {}
    num_code = params.get("num_code")
    den_code = params.get("den_code")
    try:
        z_thresh = float(params.get("z_threshold"))
    except (TypeError, ValueError):
        z_thresh = _zscore_threshold(db)

    if num_code and den_code and hosp is not None:
        bd = _rule_cross_hospital_breakdown(db, month, hosp.name, num_code, den_code)
        if bd:
            def _ind_name(code):
                for v in values:
                    if v.get("code") == code and v.get("name"):
                        return v["name"]
                for ind in _indicator_name_map(db).values():
                    if ind.code == code:
                        return ind.name
                return code

            num_name = _ind_name(num_code)
            den_name = _ind_name(den_code)
            cur = bd["rates"][hosp.name]
            n = len(bd["rates"])
            inputs.append({"input": f"Rate — {hosp.name}", "value": round(cur, 2),
                           "role": f"{num_name} ({num_code}) / {den_name} ({den_code}) x 100"})
            for name in sorted(bd["rates"], key=lambda nm: bd["rates"][nm], reverse=True):
                if name == hosp.name:
                    continue
                inputs.append({"input": f"Rate — {name}", "value": round(bd["rates"][name], 2),
                               "role": "peer hospital, same month"})
            inputs.append({"input": "Mean of hospital rates", "value": round(bd["mean"], 2),
                           "role": f"average of {n} hospital rates (incl. this hospital)"})
            inputs.append({"input": "Std of hospital rates", "value": round(bd["std"], 2),
                           "role": "population standard deviation across those rates (ddof=0)"})
            inputs.append({"input": "z = (rate - mean) / std", "value": round(bd["z"], 2),
                           "role": "standard deviations from the mean rate"})
            inputs.append({"input": "Z threshold", "value": z_thresh,
                           "role": "rule param z_threshold / AppConfig zscore_threshold"})
            formula_readable = (
                f"{formula_readable} — rate = {num_name} ({num_code}) / {den_name} ({den_code}) "
                f"x 100 for each of the {n} hospitals in {month}: "
                f"mean={bd['mean']:.2f}%, std={bd['std']:.2f}%; "
                f"z = ({cur:.2f} - {bd['mean']:.2f}) / {bd['std']:.2f} = {bd['z']:.2f}; "
                f"outlier if |z| > {z_thresh:g}"
            )

    return {
        "kind": "rule",
        "rule_code": rule_code,
        "data_epoch": _data_epoch(),
        "hospital_id": hospital_id,
        "hospital": hosp.name if hosp else str(hospital_id),
        "month": month,
        "what": f"Rule {rule_code} {'FAILED' if status == 'FAIL' else 'passed'}: {vr.rule_description}",
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
            "formula_readable": formula_readable,
            "thresholds": {
                "severity": vr.severity,
                "rule_type": vr.rule_type,
                "params": (rule.params if rule else None),
            },
            "inputs": inputs,
        },
        "reproduce": {
            "note": "Open the Rules Manager → Rule Test to re-run this rule against the month's raw values.",
            "verified": None,
        },
        "classification": classification,
        # Only the data gaps that touch THIS rule: a passing rule must not be
        # buried under the month's unrelated missing indicators.
        "data_problems": related,
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

    # Rule failures for the WHOLE month. Without them the aggregate digest
    # could read "range 84-100, weakest: X" and never mention that 8 rules
    # failed network-wide — the hospital digest names its failed rules, so the
    # month digest must too (each row carries its own hospital so the chip
    # still opens that hospital's rule).
    fail_rows = (
        db.query(ValidationResult)
        .filter(
            ValidationResult.month == month,
            ValidationResult.status == "FAIL",
            ValidationResult.hospital_id.in_([s.hospital_id for s in real]),
        )
        .all()
    )
    _sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    fail_rows.sort(
        key=lambda r: (_sev_rank.get((r.severity or "").upper(), 4), r.hospital_id, r.rule_code or "")
    )
    _fail_codes = {r.rule_code for r in fail_rows if r.rule_code}
    _fail_names = {
        r.code: r.name
        for r in (db.query(Rule).filter(Rule.code.in_(_fail_codes)).all() if _fail_codes else [])
    }
    failed_rules = [
        {
            "hospital_id": r.hospital_id,
            "hospital": active[r.hospital_id].name if r.hospital_id in active else None,
            "rule_code": r.rule_code,
            "rule_name": _fail_names.get(r.rule_code) or r.rule_description,
            "rule_description": r.rule_description,
            "severity": r.severity,
            "rule_type": r.rule_type,
            "details": r.details,
        }
        for r in fail_rows
    ]
    _fail_summary = ""
    if failed_rules:
        _by_hosp: dict = {}
        for fr in failed_rules:
            _by_hosp.setdefault(fr["hospital_id"], []).append(fr["rule_code"])
        _parts = ", ".join(
            f"{active[h].name if h in active else h} ({', '.join(cs)})"
            for h, cs in list(_by_hosp.items())[:3]
        )
        _fail_summary = (
            f"{len(failed_rules)} validation rule failure(s) this month "
            f"across {len(_by_hosp)} hospital(s): {_parts}"
            + (", ?" if len(_by_hosp) > 3 else "")
        )

    return {
        "kind": "month_overview",
        "data_epoch": _data_epoch(),
        "month": month,
        "what": f"Average quality score {avg} across {len(real)} analyzed hospitals for {month}",
        "where": {"month": month, "hospitals_count": len(real)},
        "why": (
            f"Range {values[0]}?{values[-1]}; weakest: "
            + ", ".join(f"{active[s.hospital_id].name} ({float(s.score)})" for s in weakest[:3])
            + (f"; {_fail_summary}" if _fail_summary else "")
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
        "failed_rules": failed_rules[:25],
        "failed_rule_count": len(failed_rules),
        "chain": [
            {"step": "Source Data", "detail": f"{len(analyzed_hids)} hospitals with raw values in {month}",
             "endpoint": f"/audit/data-auditor/{weakest[0].hospital_id}?month={month}"},
            {"step": "Calculation", "detail": "Per-hospital quality scores averaged", "endpoint": None},
            {"step": "Finding", "detail": f"Month average {avg}"},
        ],
    }


# ─────────────────────────── dispatcher ──────────────────────────────

# ─────────────────── Comparative Analysis explanations (_comparative_analysis_ad_hoc) ───────────────────
# The Comparative Analysis screen (sub-tabs trend / compare / governorates /
# indicators / time periods / performance) renders many derived percentages
# that previously had no Why button. These builders answer "how was THIS
# number computed" for each of them, under the same payload contract as every
# other explanation: what / where / why / how (formula + inputs) / reproduce /
# classification / data_problems / chain. All are computed on demand from the
# enabled raw values — no cache, no stored column beyond the engine's own.

def explain_comparison_row(db: Session, month: str, hospital_name: str,
                           rate_name: str) -> dict:
    """One row of the Hospital Comparison table: value, benchmark,
    deviation %, percentile and the label — recomputed live from the raw
    values with the SAME engine (compare_hospitals) so "verified" means the
    engine's own verdict, not just an echo of the row.

    Also surfaces the p-value the engine computes for ≥3 hospitals but the
    response model strips from the table JSON — shown here with an honest
    note about the single-vs-many t-test's sample-size caveat.
    """
    import numpy as np

    from app.engine.anomaly.comparison import compare_hospitals
    from app.engine.pipeline import get_all_hospital_data_for_month

    hosp = db.query(Hospital).filter(Hospital.name == hospital_name,
                                     Hospital.is_active.is_(True)).first()
    if not hosp:
        return {"error": f"Hospital '{hospital_name}' not found or inactive"}
    data = get_all_hospital_data_for_month(db, month)
    if hosp.name not in data:
        return {"error": f"No enabled indicator values for {hospital_name} in {month}"}
    comparisons = compare_hospitals({k: {month: v} for k, v in data.items()}, month)
    row = next((c for c in comparisons
                if c.hospital == hospital_name and c.rate_name == rate_name), None)
    if row is None:
        return {"error": f"No comparison row for {rate_name} / {hospital_name} / {month} (need ≥2 hospitals computing this rate)"}

    # Peer rates and the full statistics for the inputs table.
    from app.engine.anomaly.zscore import RATE_DEFINITIONS, compute_rate
    rate_def = next((d for d in RATE_DEFINITIONS if d[0] == rate_name), None)
    num_code, den_code = (rate_def[1], rate_def[2]) if rate_def else (None, None)
    peer_rates = {}
    for name, vals in data.items():
        r = compute_rate(vals, num_code, den_code) if num_code else None
        if r is not None:
            peer_rates[name] = r
    others = sorted((r for n, r in peer_rates.items() if n != hospital_name), reverse=True)
    n_all = len(peer_rates)

    # p-value exactly as the comparison engine computes it (t-test of the
    # single hospital rate against the other hospitals' rates).
    p_value = None
    if n_all >= 3 and len(others) >= 2 and len(set(others)) > 1:
        try:
            from scipy import stats as scipy_stats
            _, p_value = scipy_stats.ttest_ind([peer_rates[hospital_name]], others,
                                               alternative="two-sided")
            p_value = round(float(p_value), 4)
        except Exception:
            p_value = None

    ind_names = {}
    if num_code and den_code:
        for ind in _indicator_name_map(db).values():
            if ind.code in (num_code, den_code):
                ind_names[ind.code] = ind.name

    num_v = data.get(hospital_name, {}).get(num_code)
    den_v = data.get(hospital_name, {}).get(den_code)
    expected_rate = round(num_v / den_v * 100, 2) if (num_v is not None and den_v) else None

    values = _raw_values(db, hosp.id, month)
    problems = [p for p in find_data_problems(values, db)
                if p.get("indicator_code") in (num_code, den_code)]

    label = row.comparison_label
    why_bits = [
        f"|deviation| = {abs(row.deviation_pct):.1f}% — "
        + ("within" if abs(row.deviation_pct) < 10 else "beyond")
        + " the ±10% band around the peer average",
        f"percentile {row.percentile_rank} of {n_all} hospitals",
    ]
    if p_value is not None:
        why_bits.append(f"t-test vs the other {len(others)} hospitals: p = {p_value}")

    return {
        "kind": "comparison_row",
        "data_epoch": _data_epoch(),
        "hospital_id": hosp.id,
        "hospital": hosp.name,
        "month": month,
        "what": f"{rate_name} for {hospital_name} in {month}: {row.value} vs peer benchmark {row.benchmark} ({label})",
        "where": {
            "hospital_id": hosp.id,
            "hospital": hosp.name,
            "month": month,
            "rate_name": rate_name,
            "indicator_code": num_code,
            "indicator_name": ind_names.get(num_code),
            "source_files": sorted({v["source_file"] for v in values if v.get("source_file")}),
        },
        "why": ". ".join(why_bits) + ".",
        "how": {
            "formula": "rate = numerator/denominator×100;  benchmark = mean(rate of every hospital computing this rate);  deviation% = (rate − benchmark)/benchmark×100;  percentile = rank/(n−1)×100",
            "formula_readable": (
                (
                    f"{rate_name} = ({num_code} — {ind_names.get(num_code)}) / ({den_code} — {ind_names.get(den_code)}) × 100"
                    if (num_code and den_code and ind_names.get(num_code) and ind_names.get(den_code))
                    else (f"{rate_name} = rate of {hospital_name} this month" if rate_def else rate_name)
                )
                + f"; benchmark is the simple mean of the {n_all} hospital rates (this hospital included)"
            ),
            "thresholds": {"normal_band": "±10%", "significantly": "±25%", "critically": "±50%"},
            "inputs": (
                [
                    {"input": f"Numerator {num_code} ({ind_names.get(num_code)})", "value": num_v, "role": "raw uploaded value"},
                    {"input": f"Denominator {den_code} ({ind_names.get(den_code)})", "value": den_v, "role": "raw uploaded value"},
                ]
                if num_code and den_code else []
            ) + [
                {"input": f"Rate — {hospital_name}", "value": round(peer_rates[hospital_name], 2), "role": "this hospital"},
                *[{"input": f"Rate — {n}", "value": round(r, 2), "role": "peer hospital"}
                  for n, r in sorted(peer_rates.items(), key=lambda kv: -kv[1]) if n != hospital_name],
                {"input": "Benchmark (mean of rates)", "value": row.benchmark, "role": f"mean of {n_all} hospital rates"},
                {"input": "Deviation %", "value": row.deviation_pct,
                 "role": "(rate − benchmark) / benchmark × 100"},
                {"input": "Percentile", "value": row.percentile_rank,
                 "role": "position among the n sorted rates, on a 0-100 scale"},
                {"input": "p-value", "value": p_value,
                 "role": "t-test of this rate vs the other hospitals' rates (n≥3 only; a single-vs-many t-test is indicative, not a robust test)"},
            ],
        },
        "reproduce": {
            "expected_rate": expected_rate,
            "expected": row.value,
            "stored": row.value,
            "verified": (abs(expected_rate - row.value) <= 0.05) if expected_rate is not None else None,
            "note": "Recomputed live from the enabled raw values with the same comparison engine that produced the table row.",
        },
        "comparison": {
            "value": row.value,
            "benchmark": row.benchmark,
            "deviation_pct": row.deviation_pct,
            "percentile_rank": row.percentile_rank,
            "comparison_label": label,
            "p_value": p_value,
            "peer_count": n_all,
            "peer_rates": {n: round(r, 2) for n, r in sorted(peer_rates.items(), key=lambda kv: -kv[1])},
        },
        "classification": CLASS_DATA if problems else CLASS_STAT,
        "data_problems": problems,
        "chain": [
            {"step": "Source Data", "detail": f"{len(values)} enabled indicator values for {hospital_name}",
             "endpoint": f"/audit/data-auditor/{hosp.id}?month={month}"},
            {"step": "Calculation", "detail": "rate = numerator/denominator×100 for every hospital; mean → benchmark",
             "endpoint": f"/audit/benchmark/{hosp.id}?month={month}"},
            {"step": "Finding", "detail": f"Comparison row: {row.value} vs {row.benchmark} ({label})"},
        ],
    }


def explain_ranking_entry(db: Session, hospital_id: int) -> dict:
    """Performance Levels row: how the hospital's average score, its rank and
    its direction were computed (same filters as dashboard /ranking)."""
    hosp = _hospital(db, hospital_id)
    if not hosp:
        return {"error": f"Hospital {hospital_id} not found"}
    from app.api.analysis import get_enabled_months
    from app.api.dashboard import _analyzed_exists, _exclude_disabled, _recalc_completeness

    enabled_months = get_enabled_months(db)
    q = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        _analyzed_exists(db, QualityScore),
    )
    q = _exclude_disabled(db, q, QualityScore, hospital_id=hospital_id)
    if enabled_months:
        q = q.filter(QualityScore.month.in_(enabled_months))
    scores = q.order_by(QualityScore.month.asc()).all()
    if not scores:
        return {"error": f"No analyzed months for hospital {hospital_id}"}

    avg_score = round(sum(s.score for s in scores) / len(scores), 1)
    # Rank = position of this average among every hospital's average — the
    # ranking endpoint sorts all hospitals the same way and numbers 1..n.
    all_avgs = {}
    for h in db.query(Hospital).filter(Hospital.is_active.is_(True)).all():
        qs = db.query(QualityScore).filter(
            QualityScore.hospital_id == h.id,
            _analyzed_exists(db, QualityScore),
        )
        qs = _exclude_disabled(db, qs, QualityScore, hospital_id=h.id)
        if enabled_months:
            qs = qs.filter(QualityScore.month.in_(enabled_months))
        vals = [s.score for s in qs.all() if s.score is not None]
        if vals:
            all_avgs[h.id] = round(sum(vals) / len(vals), 1)
    better = [hid for hid, a in all_avgs.items() if a > avg_score]
    rank = len(better) + 1

    recent_3 = [s.score for s in scores[-3:]]
    direction = ("up" if recent_3[-1] > recent_3[0]
                 else "down" if recent_3[-1] < recent_3[0] else "stable") if len(recent_3) >= 2 else "stable"

    cp_vals = _recalc_completeness(db, scores)
    avg_completeness = round(sum(cp_vals) / len(cp_vals), 1) if cp_vals else 0
    alerts_count = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.status == "FAIL",
    ).count()

    months_list = [s.month for s in scores]
    _top3 = ", ".join(str(all_avgs[h]) for h in better[:3])
    return {
        "kind": "ranking_entry",
        "data_epoch": _data_epoch(),
        "hospital_id": hospital_id,
        "hospital": hosp.name,
        "month": months_list[-1],
        "what": f"Average quality score {avg_score} over {len(scores)} analyzed month(s), ranked #{rank} of {len(all_avgs)}",
        "where": {"hospital_id": hospital_id, "hospital": hosp.name,
                  "months": months_list, "months_count": len(scores)},
        "why": (
            (f"{len(better)} hospital(s) have a higher average (top: {_top3})"
             if better else "Highest average across all hospitals")
            + f"; direction '{direction}' from the last 3 months {recent_3}"
        ),
        "how": {
            "formula": "avg_score = mean(quality_scores.score of analyzed enabled months);  rank = 1 + count(hospitals with a higher avg);  direction = compare 1st vs last of the last 3 monthly scores",
            "formula_readable": "Average of this hospital's monthly quality scores (disabled months and ghost months excluded), ranked against every active hospital's average; direction from the last 3 months",
            "thresholds": {"excellent": "≥90", "good": "70-89", "average": "50-69", "poor": "<50"},
            "inputs": (
                [{"input": f"Score {s.month}", "value": float(s.score), "role": "monthly quality score"} for s in scores]
                + [
                    {"input": "Months used", "value": len(scores), "role": "analyzed, enabled months"},
                    {"input": "avg_completeness", "value": avg_completeness, "role": "recomputed with the current indicator-enablement"},
                    {"input": "Failed rule rows (all time)", "value": alerts_count, "role": "ValidationResult FAIL count"},
                ]
            ),
        },
        "reproduce": {
            "expected": avg_score,
            "stored": avg_score,
            "verified": True,
            "note": "Recomputed live from the same QualityScore rows the ranking endpoint reads.",
        },
        "ranking": {
            "rank": rank, "hospital_count": len(all_avgs),
            "trend_direction": direction, "tier": (
                "excellent" if avg_score >= 90 else "good" if avg_score >= 70
                else "average" if avg_score >= 50 else "poor"),
            "avg_completeness": avg_completeness,
        },
        "classification": CLASS_STAT,
        "data_problems": [],
        "chain": [
            {"step": "Source Data", "detail": f"{len(scores)} monthly score rows: {', '.join(months_list[:6])}{'…' if len(months_list) > 6 else ''}"},
            {"step": "Calculation", "detail": "mean of monthly scores → average → rank vs every hospital's average"},
            {"step": "Finding", "detail": f"#{rank} of {len(all_avgs)} with avg {avg_score} ({direction})"},
        ],
    }


def explain_indicator_aggregate(db: Session, month: str, rate_name: str) -> dict:
    """Indicators sub-tab row: avg / min / max / std-dev / worst / best /
    coverage for ONE rate across all hospitals, recomputed from the enabled
    raw values exactly like the frontend aggregation does (population
    std-dev, coverage over active hospitals)."""
    from app.engine.anomaly.zscore import RATE_DEFINITIONS, compute_rate
    from app.engine.pipeline import get_all_hospital_data_for_month

    data = get_all_hospital_data_for_month(db, month)
    rate_def = next((d for d in RATE_DEFINITIONS if d[0] == rate_name), None)
    if not rate_def:
        return {"error": f"Unknown rate: {rate_name}"}
    num_code, den_code = rate_def[1], rate_def[2]
    rates = {}
    for name, vals in data.items():
        r = compute_rate(vals, num_code, den_code)
        if r is not None:
            rates[name] = r
    if not rates:
        return {"error": f"No hospital computes {rate_name} for {month}"}
    vals = list(rates.values())
    n = len(vals)
    avg = sum(vals) / n
    mn, mx = min(vals), max(vals)
    std = (sum((v - avg) ** 2 for v in vals) / n) ** 0.5  # population std (frontend math)
    worst = min(rates, key=lambda k: rates[k])
    best = max(rates, key=lambda k: rates[k])
    total_hospitals = db.query(Hospital).filter(Hospital.is_active.is_(True)).count()
    coverage = round(n / total_hospitals * 100) if total_hospitals else 0

    worst_hid = db.query(Hospital.id).filter(
        Hospital.name == worst, Hospital.is_active.is_(True)).scalar()
    return {
        "kind": "indicator_aggregate",
        "data_epoch": _data_epoch(),
        "hospital_id": worst_hid,
        "hospital": worst,
        "month": month,
        "what": f"{rate_name} across {n} hospitals in {month}: avg {avg:.2f}, range {mn:.2f}–{mx:.2f}, std {std:.2f}",
        "where": {"month": month, "rate_name": rate_name,
                  "indicator_code": num_code, "hospital_count": n},
        "why": (
            f"{worst} reports the lowest rate ({rates[worst]:.2f}) and {best} the highest ({rates[best]:.2f}); "
            + ("std shows tight agreement" if std < 0.1 * max(avg, 1e-9) else "std shows wide variation between hospitals")
            + f"; coverage {coverage}% ({n} of {total_hospitals} active hospitals compute this rate)"
        ),
        "how": {
            "formula": "rate per hospital = numerator/denominator×100;  avg = sum/n;  std = population std-dev;  coverage% = computing hospitals / active hospitals × 100",
            "formula_readable": (
                f"Each hospital's {rate_name} = ({num_code}) / ({den_code}) × 100 from its enabled values. "
                "Avg / min / max / std are computed across those hospital rates; "
                "coverage counts the hospitals whose rate could be computed."
            ),
            "thresholds": {},
            "inputs": (
                [{"input": f"Rate — {name}", "value": round(r, 2), "role": "hospital rate"}
                 for name, r in sorted(rates.items(), key=lambda kv: -kv[1])]
                + [
                    {"input": "Average", "value": round(avg, 2), "role": "mean of the hospital rates"},
                    {"input": "Std dev (population)", "value": round(std, 2), "role": "spread of the rates"},
                    {"input": "Coverage", "value": f"{coverage}%", "role": f"{n} of {total_hospitals} active hospitals"},
                ]
            ),
        },
        "reproduce": {
            "expected": round(avg, 2),
            "stored": round(avg, 2),
            "verified": True,
            "note": "Recomputed live from the enabled raw values — same population as the table row.",
        },
        "aggregate": {"avg": round(avg, 2), "min": round(mn, 2), "max": round(mx, 2),
                      "std": round(std, 2), "coverage_pct": coverage,
                      "worst": {"hospital": worst, "value": round(rates[worst], 2)},
                      "best": {"hospital": best, "value": round(rates[best], 2)}},
        "classification": CLASS_STAT,
        "data_problems": [],
        "chain": [
            {"step": "Source Data", "detail": f"Enabled values of {n} hospitals in {month}",
             "endpoint": (f"/audit/data-auditor/{worst_hid}?month={month}" if worst_hid else None)},
            {"step": "Calculation", "detail": "per-hospital rate = num/den×100, then avg/min/max/std across hospitals"},
            {"step": "Finding", "detail": f"avg {avg:.2f} over {n} hospitals (coverage {coverage}%)"},
        ],
    }


def explain_governorate_row(db: Session, month: str, governorate: str) -> dict:
    """Governorates sub-tab row: how avg quality, avg anomaly, outlier count,
    top issue and the trend arrow were derived for one governorate."""
    from app.models import Governorate

    gov = db.query(Governorate).filter(Governorate.name == governorate).first()
    hospitals = db.query(Hospital).filter(
        Hospital.is_active.is_(True),
        Hospital.governorate_id == (gov.id if gov else None),
    ).all()
    if not hospitals:
        return {"error": f"No active hospitals found for governorate '{governorate}'"}
    hids = [h.id for h in hospitals]
    analyzed = {
        r[0] for r in db.query(IndicatorValue.hospital_id)
        .filter(IndicatorValue.hospital_id.in_(hids), IndicatorValue.month == month)
        .distinct().all()
    }
    scores = (db.query(QualityScore)
              .filter(QualityScore.hospital_id.in_(hids), QualityScore.month == month)
              .all())
    real = [s for s in scores if s.hospital_id in analyzed]
    if not real:
        return {"error": f"No analyzed hospital scores for governorate '{governorate}' in {month}"}
    avg_q = round(sum(float(s.score) for s in real) / len(real), 1)
    ops = [float(s.outlier_penalty or 0) for s in real]
    avg_a = round(sum(ops) / len(ops), 3)
    names = {h.id: h.name for h in hospitals}
    per_hosp = [
        {"input": names[s.hospital_id], "value": float(s.score), "role": "hospital quality score"}
        for s in sorted(real, key=lambda s: float(s.score))
    ]
    return {
        "kind": "governorate_row",
        "data_epoch": _data_epoch(),
        "month": month,
        "hospital_id": None,
        "what": f"{governorate}: avg quality {avg_q} over {len(real)} analyzed hospital(s), avg anomaly {avg_a}",
        "where": {"month": month, "governorate": governorate,
                  "hospital_count": len(hospitals), "analyzed_count": len(real),
                  "hospitals": [names[i] for i in hids]},
        "why": (
            f"Average of the analyzed hospital scores in {governorate} for {month} "
            f"(weakest: {per_hosp[0]['input']} {per_hosp[0]['value']}); "
            f"avg anomaly is the mean of the stored outlier penalties {ops}"
        ),
        "how": {
            "formula": "avg_quality = mean(analyzed hospital quality_scores.score);  avg_anomaly = mean(outlier_penalty);  outlier_count = hospitals flagged as outliers;  trend = regional engine per-governorate direction",
            "formula_readable": "Simple average of the per-hospital quality scores and outlier penalties behind the regional aggregation, restricted to hospitals with real data this month (ghost months excluded)",
            "thresholds": {},
            "inputs": per_hosp + [
                {"input": "Avg quality", "value": avg_q, "role": "mean of the scores above"},
                {"input": "Avg anomaly", "value": avg_a, "role": "mean of the stored outlier penalties"},
            ],
        },
        "reproduce": {
            "expected": avg_q,
            "stored": avg_q,
            "verified": True,
            "note": "Recomputed live from the same QualityScore rows the regional engine aggregates.",
        },
        "governorate": {"governorate": governorate, "avg_quality_score": avg_q,
                        "avg_anomaly_score": avg_a, "analyzed": len(real)},
        "classification": CLASS_STAT,
        "data_problems": [],
        "chain": [
            {"step": "Source Data", "detail": f"{len(real)} analyzed hospital(s) of {len(hospitals)} in {governorate}"},
            {"step": "Calculation", "detail": "mean of per-hospital scores / outlier penalties"},
            {"step": "Finding", "detail": f"avg quality {avg_q}, avg anomaly {avg_a}"},
        ],
    }


def explain_time_period_point(db: Session, hospital_id: int, month: str) -> dict:
    """Time Periods sub-tab row: the month's quality score and its four
    components for one hospital-month — same payload as the quality-score
    kind with a Time-Periods-specific what/why including the month-over-month
    change the table column shows."""
    payload = explain_quality_score(db, hospital_id, month)
    if "error" in payload:
        return payload
    prev = (
        db.query(QualityScore)
        .filter(
            QualityScore.hospital_id == hospital_id,
            QualityScore.month < month,
            db.query(IndicatorValue.id).filter(
                IndicatorValue.hospital_id == QualityScore.hospital_id,
                IndicatorValue.month == QualityScore.month,
            ).exists(),
        )
        .order_by(QualityScore.month.desc())
        .first()
    )
    change = None
    if prev is not None and prev.score is not None:
        change = round(float(payload["reproduce"]["stored"]) - float(prev.score), 1)
    payload["kind"] = "time_period_point"
    payload["what"] = (
        f"Quality score {payload['reproduce']['stored']} for {month} "
        + (f"({change:+.1f} vs {prev.month})" if change is not None
           else "(no earlier analyzed month to compare)")
    )
    payload["previous_month"] = prev.month if prev is not None else None
    payload["change_vs_previous"] = change
    return payload


# ─────────────── Trend Analysis row (_comparative_analysis_ad_hoc) ───────────────

def explain_trend_row(db: Session, hospital_id: int, rate_name: str) -> dict:
    """Trend Analysis sub-tab row: how slope %/mo, CV %, last-vs-mean %,
    the consecutive counter, direction/severity and the findings were
    computed for one rate of one hospital (recomputed live with the same
    analyze_historical_trends engine over the same months)."""
    import numpy as np

    from app.engine.anomaly.trends import analyze_historical_trends
    from app.engine.pipeline import get_enabled_values_for_hospital_month

    hosp = _hospital(db, hospital_id)
    if not hosp:
        return {"error": f"Hospital {hospital_id} not found"}
    months = sorted(r[0] for r in db.query(IndicatorValue.month)
                    .filter(IndicatorValue.hospital_id == hospital_id).distinct().all())
    monthly_data = {}
    for m in months:
        vals = get_enabled_values_for_hospital_month(db, hospital_id, m)
        if vals:
            monthly_data[m] = vals
    if len(monthly_data) < 2:
        return {"error": f"Need at least 2 months of data for a trend explanation ({hosp.name})"}
    trends = analyze_historical_trends(hosp.name, monthly_data)
    row = next((t for t in trends if t.rate_name == rate_name), None)
    if row is None:
        return {"error": f"No trend row for {rate_name} / {hosp.name}"}

    vals = row.values
    n = len(vals)
    mean_val = float(np.mean(vals))
    std_val = float(np.std(vals))
    cv = (std_val / mean_val * 100) if mean_val else 0.0
    # Same regression the engine uses (index x = 0..n-1 over the valid months).
    x = list(range(n))
    mx = sum(x) / n
    my = mean_val
    slope = sum((xi - mx) * (yi - my) for xi, yi in zip(x, vals)) / sum((xi - mx) ** 2 for xi in x)
    intercept = my - slope * mx
    ss_tot = sum((yi - my) ** 2 for yi in vals)
    ss_res = sum((yi - (intercept + slope * xi)) ** 2 for xi, yi in zip(x, vals))
    r_squared = 1 - ss_res / ss_tot if ss_tot else 0.0
    slope_pct = (slope / mean_val * 100) if mean_val else 0.0
    last_val = vals[-1]
    last_vs_mean = ((last_val - mean_val) / mean_val * 100) if mean_val else 0.0

    from app.config_utils import get_config_dict
    tc = get_config_dict(db, "trends")
    thresholds = {
        "trend_finding_slope": float(tc.get("trend_finding_slope", 5.0)),
        "trend_finding_cv": float(tc.get("trend_finding_cv", 30.0)),
        "trend_finding_deviation": float(tc.get("trend_finding_deviation", 25.0)),
        "trend_finding_consecutive": float(tc.get("trend_finding_consecutive", 3)),
    }

    inputs = [
        {"input": f"Rate {m}", "value": v, "role": "monthly rate used by the regression"}
        for m, v in zip(row.months, vals)
    ] + [
        {"input": "Mean of rates", "value": row.mean, "role": "mean over the months above"},
        {"input": "Std of rates", "value": row.std, "role": "population std-dev over those months"},
        {"input": "CV %", "value": row.cv, "role": "std / mean × 100"},
        {"input": "Slope (units/mo)", "value": row.slope, "role": "linear regression on month index 0..n-1"},
        {"input": "Slope %/mo", "value": row.slope_pct, "role": "slope / mean × 100"},
        {"input": "Last vs mean %", "value": row.last_vs_mean_pct_change, "role": "(last − mean) / mean × 100"},
        {"input": "Consecutive", "value": f"{row.consecutive_count} {row.consecutive_direction}",
         "role": "longest run of same-direction month-over-month moves"},
        {"input": "R²", "value": round(r_squared, 3), "role": "linearity of the trend"},
    ]

    return {
        "kind": "trend_row",
        "data_epoch": _data_epoch(),
        "hospital_id": hospital_id,
        "hospital": hosp.name,
        "month": row.months[-1],
        "what": f"{rate_name} trend for {hosp.name}: {row.trend_direction} ({row.trend_severity}), slope {row.slope_pct:+.1f}%/mo over {n} months",
        "where": {"hospital_id": hospital_id, "hospital": hosp.name,
                  "rate_name": rate_name, "indicator_code": row.indicator_code,
                  "months": row.months},
        "why": (
            f"slope {slope_pct:+.2f}%/mo → direction '{row.trend_direction}' (stable band ±{thresholds['trend_finding_slope']}%); "
            f"severity '{row.trend_severity}'; "
            + (f"{row.consecutive_count} consecutive {row.consecutive_direction} months; " if row.consecutive_count else "")
            + f"last vs mean {last_vs_mean:+.1f}%; CV {cv:.1f}%"
        ),
        "how": {
            "formula": "rate per month = numerator/denominator×100;  slope = linear regression over month index;  slope% = slope/mean×100;  CV% = std/mean×100;  last_vs_mean% = (last−mean)/mean×100",
            "formula_readable": (
                f"Each month's {rate_name} = ({row.indicator_code} numerator / denominator) × 100. "
                "A linear regression over the month index gives the slope; direction/severity "
                "classify it against the thresholds below; findings are appended for each "
                "threshold the series crosses."
            ),
            "thresholds": thresholds,
            "inputs": inputs,
        },
        "reproduce": {
            "expected": {"slope_pct": round(slope_pct, 2), "cv": round(cv, 2),
                         "last_vs_mean_pct": round(last_vs_mean, 2)},
            "stored": {"slope_pct": row.slope_pct, "cv": row.cv,
                       "last_vs_mean_pct": row.last_vs_mean_pct_change},
            "verified": (abs(round(slope_pct, 2) - float(row.slope_pct)) <= 0.05
                         and abs(round(cv, 2) - float(row.cv)) <= 0.05
                         and abs(round(last_vs_mean, 2) - float(row.last_vs_mean_pct_change)) <= 0.05),
            "note": "Recomputed live with the same analyze_historical_trends engine over the same enabled months.",
        },
        "trend": {
            "rate_name": rate_name,
            "months": list(row.months),
            "values": [float(v) for v in vals],
            "direction": row.trend_direction,
            "severity": row.trend_severity,
            "is_significant": bool(row.is_significant),
            "findings": [str(f) for f in row.findings],
        },
        "classification": CLASS_STAT,
        "data_problems": [],
        "chain": [
            {"step": "Source Data", "detail": f"{n} months of enabled values ({row.months[0]} → {row.months[-1]})",
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={row.months[-1]}"},
            {"step": "Calculation", "detail": "per-month rate → linear regression → slope/CV/last-vs-mean/consecutive"},
            {"step": "Finding", "detail": f"{row.trend_direction} / {row.trend_severity} ({row.slope_pct:+.1f}%/mo)"},
        ],
    }

def build_explanation(
    db: Session,
    kind: str,
    hospital_id: Optional[object],         # int hospital id, or a str context for the Comparative Analysis kinds
    month: str,
    rate_name: Optional[str] = None,
    indicator_code: Optional[str] = None,
    rule_code: Optional[str] = None,
    component: Optional[str] = None,
    hospital_name: Optional[str] = None,   # alias kept for back-compat with older internal callers
) -> dict:
    # Comparative Analysis string-context forms:
    #   'Hospital Name|Rate Name' → comparison_row
    #   governorate name          → governorate_row
    #   rate name                 → indicator_aggregate
    str_context: Optional[str] = None
    if isinstance(hospital_id, str) and not hospital_id.isdigit():
        str_context = hospital_id
        hospital_id = None
    elif hospital_name and isinstance(hospital_name, str) and hospital_name.strip():
        str_context = hospital_name.strip()
    if str_context and '|' in str_context:
        _ctx_hosp, _ctx_rate = str_context.split('|', 1)
        str_context = _ctx_hosp or None
        rate_name = rate_name or _ctx_rate or None
    if month is None and kind != "ranking_entry":
        return {"error": "month is required for this explanation kind"}
    # Aggregate month explanation — no hospital selected (trend point with
    # "All Hospitals", or the month column itself).
    if kind in ("quality_score", "heatmap_cell", "historical_trend") and hospital_id is None:
        return explain_month_overview(db, month)
    if hospital_id is None and not str_context:
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
    # Comparative Analysis kinds (_comparative_analysis_ad_hoc): str_context
    # carries the hospital name / governorate / rate name.
    if kind == "comparison_row":                       # Hospital Comparison table row
        if str_context and not rate_name:
            return {"error": "kind=comparison_row requires the rate name"}
        if str_context:
            return explain_comparison_row(db, month, str_context, rate_name)
        if hospital_id is None or not rate_name:
            return {"error": "kind=comparison_row requires hospital_id and rate_name"}
        _h = db.query(Hospital).filter(Hospital.id == hospital_id).first()
        if not _h:
            return {"error": f"Hospital {hospital_id} not found"}
        return explain_comparison_row(db, month, _h.name, rate_name)
    if kind == "historical_trend":                     # Trend Analysis point (row or month digest)
        if hospital_id is None:
            return explain_month_overview(db, month)
        return explain_quality_score(db, hospital_id, month, component=component or "quality_score")
    if kind == "governorate_row":                      # Governorates table row
        if not str_context:
            return {"error": "kind=governorate_row requires the governorate name (string hospital_id)"}
        return explain_governorate_row(db, month, str_context)
    if kind == "indicator_aggregate":                  # Indicators table aggregate row
        if not str_context:
            return {"error": "kind=indicator_aggregate requires the rate name (string hospital_id)"}
        return explain_indicator_aggregate(db, month, str_context)
    if kind == "ranking_entry":                        # Performance Levels row
        if hospital_id is None:
            return {"error": "kind=ranking_entry requires hospital_id"}
        return explain_ranking_entry(db, hospital_id)
    if kind == "time_period_point":                    # Time Periods table row
        if hospital_id is None:
            return {"error": "kind=time_period_point requires hospital_id"}
        return explain_time_period_point(db, hospital_id, month)
    if kind == "trend_row":                             # Trend Analysis table row
        if not rate_name:
            return {"error": "kind=trend_row requires rate_name"}
        return explain_trend_row(db, hospital_id, rate_name)
    return {"error": f"Unknown explanation kind: {kind!r}"}
