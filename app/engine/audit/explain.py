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
import logging
from collections import Counter
from typing import List, Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


def _data_epoch() -> Optional[str]:
    """Snapshot stamp carried on every explanation. Two responses with the
    same epoch were derived from exactly the same data — this is how the UI
    tells "stale view" from "stale analysis"."""
    try:
        from app.cache import get_data_epoch
        return get_data_epoch()
    except Exception:
        return None

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import (
    AnomalyResult,
    ConfidenceScore,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
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
    from app.engine.quality import quality_weights
    raw = get_config_dict(db, "quality")
    w = quality_weights(raw)
    return {
        "config": raw,
        "weights": {
            "rule_compliance": w["rule_compliance"],
            "completeness": w["completeness"],
            "consistency": w["consistency"],
            "outlier_score": w["outlier_penalty"],
        },
        # Same targets the KPI cards and component-diagnostics use.
        "targets": {"rule_compliance": 85, "completeness": 90, "consistency": 85, "outlier_score": 90},
    }


def _zscore_threshold(db: Session) -> float:
    """Authoritative z-score threshold from this explanation's snapshot.

    One snapshot per Explain operation, the same source the trend and rules
    explanations use. ``analysis_config_from_snapshot`` applies the same
    clamp/round as the legacy ``load_analysis_config`` loader, so stored values
    and defaults are unchanged; the display simply cannot disagree with the
    policy the explanation was built from.
    """
    from app.engine.config_resolver import load_policy_snapshot
    from app.engine.policy_view import analysis_config_from_snapshot
    return analysis_config_from_snapshot(
        load_policy_snapshot(db)).zscore_threshold


def _rate_multiplier(num_code: Optional[str], den_code: Optional[str]) -> float:
    """Multiplier of the zscore rate spec for a legacy code pair; 100.0
    when no spec matches (the historical audit default)."""
    from app.engine.rate_config import zscore_spec_for

    spec = zscore_spec_for(num_code, den_code) if num_code and den_code else None
    return spec.rate_multiplier if spec else 100.0


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
      whose absence is a legitimate non-event: an Optional element (the flag
      set on the Data Tree), an indicator that is Optional BY INHERITANCE
      (every source data element of its subtree is Optional — see
      pipeline.get_optional_source_indicator_ids), and one already explained
      by a reported total (the sum-rule "covered" doctrine used by
      completeness: when the reported children already add up to the parent,
      an unreported sibling is "covered" and must NOT be flagged nor penalize
      completeness). Pass ``db`` to enable those gates; a None db keeps the
      legacy unconditional behaviour for callers that cannot reach the config
      tables.
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
            from app.engine.config_resolver import load_display_policy
            from app.engine.policy_view import rules_policy_from_snapshot
            present = {
                v["code"]: v["value"]
                for v in values
                if v.get("value") is not None
            }
            if present:
                covered_codes = compute_covered_codes(
                    present, set(), db,
                    rules=rules_policy_from_snapshot(load_display_policy(db))) or set()
        except Exception:
            covered_codes = set()  # fail open: keep legacy behaviour

    # Optional-code gate (same doctrine as the completeness denominator): a
    # data element flagged Optional on the Data Tree simply may have no value
    # in a month — its absence is a legitimate reason for a None row, not an
    # error. Without this every Optional leaf that was not reported (17.g,
    # 17.h, 19, …) was listed as "has no value for this month" while
    # completeness — correctly — did not penalize it.
    #
    # The set comes from pipeline.get_optional_source_indicator_ids, the single
    # source of truth, so it also covers OPTIONAL BY INHERITANCE: a parent
    # (17 → Neonatal deaths) whose every source element is Optional is not a
    # missing value either, even while its own flag still says 'Required'.
    optional_codes: set = set()
    if db is not None:
        try:
            from app.engine.pipeline import get_optional_source_indicator_ids
            from app.models import Indicator
            nullable = {v["code"] for v in values if v.get("value") is None}
            optional_ids = get_optional_source_indicator_ids(db) if nullable else set()
            if optional_ids:
                optional_codes = {
                    code for (code,) in db.query(Indicator.code)
                    .filter(Indicator.code.in_(nullable),
                            Indicator.id.in_(optional_ids))
                    .all()
                }
        except Exception:
            optional_codes = set()  # fail open: keep legacy behaviour

    problems = []
    seen = Counter()
    for v in values:
        val = v.get("value")
        if val is None:
            if v["code"] in optional_codes:
                continue  # Optional element — an unfilled month is not a problem
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
    outlier_component = component == "outlier_score"
    outlier_drivers = _outliers_behind_score(db, hospital_id, month)
    outlier_evidence = _layered_evidence_status(db, hospital_id, month)
    if outlier_component:
        # A cell with no value creates no outlier row, so it cannot explain the
        # outlier component: reporting "has no value" here buried the real
        # drivers under a wall of completeness findings. Missing cells are
        # explained where they are scored (completeness).
        problems = [p for p in problems if p.get("kind") != "missing_value"]

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
    from app.engine.quality import combine_quality_score
    expected = round(combine_quality_score(rc, cp, co, qs.outlier_penalty, cfg["config"]), 2)
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
    if outlier_component:
        penalty = float(qs.outlier_penalty or 0)
        if outlier_drivers:
            shown = ", ".join(f"{d['indicator']} ({d['level']})"
                              for d in outlier_drivers[:5])
            more = (f" +{len(outlier_drivers) - 5} more"
                    if len(outlier_drivers) > 5 else "")
            why = (f"Outlier score {op_inv:g}% = 100 - {penalty:g} penalty, from "
                   f"{len(outlier_drivers)} indicator(s) at HIGH/VERY_HIGH: "
                   f"{shown}{more}")
        elif outlier_evidence["status"] != "canonical_layered":
            why = (f"Outlier score {op_inv:g}% = 100 - {penalty:g} penalty, but "
                   f"the canonical layered evidence for {month} is missing, so "
                   f"the indicators behind the penalty cannot be listed. This is "
                   f"not a month with no findings — it is a month with no "
                   f"stored layered result")
        else:
            why = (f"No indicator reached HIGH or VERY_HIGH this month — outlier "
                   f"score {op_inv:g}% (penalty {penalty:g}). Missing cells are "
                   f"counted under completeness, not here")

    payload = {
        "kind": "quality_score",
        "data_epoch": _data_epoch(),
        "hospital_id": hospital_id,
        "hospital": hosp.name if hosp else str(hospital_id),
        "month": month,
        "what": (f"Outlier score {op_inv:g} for {month} — 100 minus the penalty from "
                 f"{len(outlier_drivers)} indicator(s) at HIGH/VERY_HIGH"
                 if outlier_component else
                 f"Data quality score {stored} for {month} — weighted mix of rule compliance, completeness, consistency and outlier score"),
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
        "outliers": outlier_drivers,
        "outlier_component": outlier_component,
        # Evidence provenance (Phase 5): the effective band the penalty used,
        # the stored band for audit, and whether this month has layered
        # evidence at all.
        "evidence_status": outlier_evidence["status"],
        "outlier_evidence": outlier_evidence,
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


def _outliers_behind_score(db: Session, hospital_id: int, month: str) -> list:
    """The stored layered rows the outlier component actually counts.

    The penalty counts rows whose EFFECTIVE band (``quality.scoring.
    layered_severity``: the approved caps and the top-band gate included) is
    HIGH/VERY_HIGH, so the explanation resolves every row through that same
    function. The popup can then never claim a stored VERY_HIGH was used when
    the policy made it HIGH — and the stored band travels beside it for audit.
    Both bands, the cap block and the source row id are reported, so a finding
    stays traceable to its ``LayeredOutlierResult``. Names come from the
    analysis specs (data elements and derived rates share them).
    """
    from app.engine.anomaly.layered import LEVEL_RANK
    from app.engine.quality.scoring import FLAGGED_LEVELS, layered_severity
    from app.models import LayeredOutlierResult

    rows = (
        db.query(LayeredOutlierResult)
        .filter(
            LayeredOutlierResult.hospital_id == hospital_id,
            LayeredOutlierResult.month == month,
        )
        .all()
    )
    if not rows:
        return []
    try:
        from app.engine.anomaly.layered import build_analysis_specs
        names = {spec.analysis_code: spec.name for spec in build_analysis_specs(db)}
    except Exception:
        names = {}

    drivers = []
    for row in rows:
        grade = layered_severity(row)
        if grade["level"] not in FLAGGED_LEVELS:
            continue
        cap = grade.get("cap") or {}
        drivers.append({
            "indicator_code": row.analysis_code,
            "indicator": names.get(row.analysis_code) or row.analysis_code,
            # `level` stays the effective band: it is what the penalty used.
            "level": grade["level"],
            "effective_level": grade["level"],
            "stored_level": grade["stored_level"],
            "capped": grade["capped"],
            "cap": grade.get("cap"),
            "cap_policy": cap.get("policy") if isinstance(cap, dict) else None,
            "evidence_status": grade["evidence_status"],
            "layered_result_id": row.id,
            "type": row.outlier_type,
            "value": row.rate if row.rate is not None else row.raw_value,
            "benchmark": (row.peer_mean if row.peer_mean is not None
                          else row.historical_mean),
            "interpretation": row.interpretation,
            "investigation_route": row.investigation_route,
        })
    drivers.sort(key=lambda d: (-LEVEL_RANK.get(d["level"] or "NONE", 0),
                                d["indicator"] or ""))
    return drivers


def _layered_evidence_status(db: Session, hospital_id: int, month: str) -> dict:
    """Whether this hospital+month HAS canonical layered evidence at all.

    No row is not the same as no finding: a month that was never analysed
    stores nothing, and describing that as "no indicator reached HIGH/VERY_HIGH"
    would turn missing evidence into a clean result. ``status`` is
    ``canonical_layered`` only when at least one row carries a stored band.
    """
    from sqlalchemy import func as _func

    from app.models import LayeredOutlierResult

    base = db.query(_func.count(LayeredOutlierResult.id)).filter(
        LayeredOutlierResult.hospital_id == hospital_id,
        LayeredOutlierResult.month == month)
    total = base.scalar() or 0
    graded = base.filter(
        LayeredOutlierResult.outlier_level.isnot(None)).scalar() or 0
    return {
        "status": ("canonical_layered" if graded
                   else "missing_layered_result"),
        "rows": int(total),
        "graded_rows": int(graded),
    }


# ───────────────────────────── anomaly ───────────────────────────────

def _value_formula(row, den_codes, multiplier: float) -> str:
    """The calculation line for any derivative row.

    Ratio rows read ``rate = numerator/denominator×N``; a count-shaped
    definition (no denominator — e.g. adolescent cases = 2.c + 2.d) has no
    denominator to divide by, so it shows its own stored expression instead of
    claiming a "×1" rate.
    """
    if den_codes:
        return f"rate = numerator/denominator×{multiplier:g}"
    if row.formula:
        return f"value = {row.formula}"
    return "value = sum of the reported elements"


def _rebuild_peer_benchmark(db: Session, month: str, hospital_name: str,
                            num_code: str, den_code: str,
                            resolved=None) -> Optional[dict]:
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

        def _rate(values):
            # Non-zscore rows (the scan covers every derivative indicator now)
            # are rebuilt through the very definition they were computed from —
            # the legacy num/den helper would score them at the wrong
            # multiplier and report a false "stale benchmark".
            if resolved is not None:
                from app.engine import indicator_service

                outcome = indicator_service.calculate_from_values(
                    resolved, values, hospital_id=0, month=month)
                return outcome.value if outcome.status == "ok" else None
            return compute_rate(values, num_code, den_code)

        data = get_all_hospital_data_for_month(db, month)
        current = _rate(data.get(hospital_name, {}))
        peers = {}
        for name, values in data.items():
            if name == hospital_name:
                continue
            rate = _rate(values)
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
    # A peer comparison too small to measure a spread carries no z-score at all
    # (layered.PEER_Z_POLICY), so a NULL z here is a policy outcome, not a
    # missing measurement.
    from app.engine.anomaly.layered import (
        MIN_PEERS_FOR_TOP_BAND,
        peer_z_measurable,
        peer_z_provenance,
    )

    # RATE_DEFINITIONS pairs the rate name with (numerator, denominator).
    from app.engine.anomaly.zscore import RATE_DEFINITIONS
    base_name = row.rate_name.replace(" (trend)", "")
    rate_def = next((d for d in RATE_DEFINITIONS if d[0] == base_name), None)
    # The outlier scan covers EVERY derivative indicator, not only the zscore
    # slice RATE_DEFINITIONS describes. For any other rate the row's stored
    # indicator_id resolves back to the registry definition, which names its
    # real inputs and multiplier — the explanation must use them, otherwise
    # the formula, the raw inputs and the benchmark reproduction would all be
    # silently wrong for the new rows.
    resolved_ref = None
    definition = None
    definition_multiplier: Optional[float] = None
    num_codes: List[str] = [rate_def[1]] if rate_def else []
    den_codes: List[str] = [rate_def[2]] if rate_def else []
    if rate_def is None:
        try:
            from app.engine import indicator_service

            resolved_ref = indicator_service.resolve_ref(db, row.indicator_id)
            definition = getattr(resolved_ref, "definition", None)
        except Exception:  # pragma: no cover - registry is optional context
            resolved_ref, definition = None, None
        if definition is not None:
            num_codes = [str(code) for code in (definition.numerator_codes or [])]
            den_codes = [str(code) for code in (definition.denominator_codes or [])]
            definition_multiplier = float(definition.multiplier or 1.0)
    num_code = num_codes[0] if num_codes else row.indicator_code
    den_code = den_codes[0] if den_codes else None
    multiplier = (definition_multiplier if definition_multiplier is not None
                  else _rate_multiplier(num_code, den_code))

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
        formula = (f"{_value_formula(row, den_codes, multiplier)};  "
                   "z = (rate − peer_mean) / peer_std  (hospital excluded from its own benchmark)")
    else:
        formula = (f"{_value_formula(row, den_codes, multiplier)};  "
                   "z = (rate − historical_mean) / historical_std  (trend anomaly)")

    num_v = by_code.get(num_code, {}).get("value")
    den_v = by_code.get(den_code, {}).get("value") if den_code else None
    # One row per input code: a definition may sum two elements in its
    # numerator (adolescent pregnancies = 2.c + 2.d), and listing only the
    # first code would hide half the calculation from the reader.
    for code in num_codes:
        name = _name_for(code)
        inputs.append({"input": f"Raw numerator ({code} — {name})" if name else f"Raw numerator ({code})",
                       "value": by_code.get(code, {}).get("value"), "role": "from uploaded data"})
    for code in den_codes:
        name = _name_for(code)
        inputs.append({"input": f"Raw denominator ({code} — {name})" if name else f"Raw denominator ({code})",
                       "value": by_code.get(code, {}).get("value"), "role": "from uploaded data"})

    if is_peer_row and row.peer_count is not None and row.peer_count < 3:
        problems.append({
            "kind": "small_peer_group",
            "severity": "medium",
            "message": f"Only {row.peer_count} peer hospital(s) — the benchmark is statistically fragile",
        })

    data_problem_flags = [p for p in problems]
    if row.formula:
        from app.engine import indicator_calc

        try:
            formula_ast = indicator_calc.parse_expression(row.formula)
            formula_values = {
                code: by_code[code]["value"]
                for code in indicator_calc.ast_codes(formula_ast)
                if code in by_code and by_code[code].get("value") is not None
            }
            calculated, formula_status = indicator_calc.evaluate(
                formula_ast, formula_values)
            expected_rate = (
                round(calculated, 2)
                if formula_status == indicator_calc.STATUS_OK else None
            )
        except indicator_calc.FormulaError:
            expected_rate = None
    elif row.value is not None and num_v is not None and den_v is not None and den_v:
        # Legacy rows without a stored formula: use the spec multiplier so
        # NMR (x30) / MMR (x1) reproduce; x100 only when no spec is known.
        from app.engine.rate_config import zscore_spec_for

        spec = zscore_spec_for(num_code, den_code) if num_code and den_code else None
        expected_rate = round(
            num_v / den_v * (spec.rate_multiplier if spec else 100.0), 2)
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
        rebuilt = _rebuild_peer_benchmark(db, month, hosp.name, num_code,
                                          den_code, resolved=resolved_ref)
        if rebuilt:
            stored_peers = {p.get("hospital") for p in (row.peers_detail or [])
                            if p.get("hospital")}
            missing = sorted(set(rebuilt["peer_hospitals"]) - stored_peers)
            extra = sorted(stored_peers - set(rebuilt["peer_hospitals"]))
            # A comparison group below MIN_PEERS_FOR_TOP_BAND produces no
            # z-score (layered.PEER_Z_POLICY), so rows written under that
            # policy store a NULL z: the check must compare populations, not
            # invent a missing measurement.
            z_graded = peer_z_measurable(row.peer_count)
            # The recomputed z is quoted whenever there is one to compare:
            # either the group is large enough to produce one, or the row was
            # written before the policy and stored one. A NULL z on a thin
            # group is the policy's output, not a missing measurement.
            peer_expected_z = (round(rebuilt["z"], 2)
                               if (z_graded or z is not None) else None)
            benchmark_verified = (
                not missing and not extra
                and rebuilt["peer_count"] == row.peer_count
                and (z is None
                     or abs(round(rebuilt["z"], 2) - float(z)) <= 0.01)
            )
            peer_check = {
                "verified": benchmark_verified,
                "peer_count": rebuilt["peer_count"],
                "stored_peer_count": row.peer_count,
                "expected_benchmark": round(rebuilt["mean"], 2),
                "expected_peer_std": round(rebuilt["std"], 2),
                "expected_z": peer_expected_z,
                "z_produced": z_graded,
                "z_provenance": peer_z_provenance(row.peer_count),
                "peer_set_matches": not missing and not extra,
                "peers_missing_from_row": missing,
                "peers_not_in_data": extra,
                "note": (
                    "Benchmark recomputed from the current data with the same "
                    "hospital set the engine uses. Fewer than "
                    f"{MIN_PEERS_FOR_TOP_BAND} peer hospitals cannot measure a "
                    "spread, so this comparison produces no z-score; the peer "
                    "values, their mean and the score are kept."
                    if peer_expected_z is None else
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
            "indicator_formula": row.formula,
            "formula_version": row.formula_version,
            "formula_readable": (
                row.formula if row.formula else
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
            # A peer comparison whose group is too small to measure a spread
            # carries no z on purpose (layered.PEER_Z_POLICY): there is nothing
            # to verify about the z, so the population the benchmark came from
            # decides the verdict instead of a NULL being read as a failure.
            "verified": (benchmark_verified
                         if (z is None and benchmark_verified is not None)
                         else (z_verified if benchmark_verified is None
                               else bool(z_verified) and benchmark_verified)),
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


def explain_rule(db: Session, hospital_id: int, month: str, rule_code: str) -> dict:
    vr = (
        db.query(ValidationResult)
        .filter(
            ValidationResult.hospital_id == hospital_id,
            ValidationResult.month == month,
            ValidationResult.rule_code == rule_code,
            or_(
                ValidationResult.rule_type.is_(None),
                func.upper(ValidationResult.rule_type) != "BENCHMARK",
            ),
            ValidationResult.rule_code.notin_(
                tuple(f"R{code:03d}" for code in range(41, 51))
            ),
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
    else:
        classification = CLASS_CLIN

    inputs = [
        {"input": "Rule status", "value": vr.status, "role": "evaluation outcome"},
        {"input": "Severity", "value": vr.severity, "role": "impact weight in the score"},
        {"input": "Details", "value": vr.details, "role": "rule message"},
    ]
    formula_readable = rule.description if rule else vr.rule_description

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

    from app.engine.anomaly.comparison import compare_hospitals
    from app.engine.pipeline import get_all_hospital_data_for_month

    hosp = db.query(Hospital).filter(Hospital.name == hospital_name,
                                     Hospital.is_active.is_(True)).first()
    if not hosp:
        return {"error": f"Hospital '{hospital_name}' not found or inactive"}
    data = get_all_hospital_data_for_month(db, month)
    if hosp.name not in data:
        return {"error": f"No enabled indicator values for {hospital_name} in {month}"}
    from app.engine import indicator_service

    managed_indicators = indicator_service.resolve_active_definitions(
        db, site="zscore")
    comparisons = compare_hospitals(
        {k: {month: v} for k, v in data.items()}, month,
        additional_indicators=managed_indicators)
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

    # p-value exactly as the comparison engine computes it (one-sample t-test of
    # the other hospitals' rates against this hospital's rate).
    from app.engine.anomaly.comparison import peer_significance
    p_value = peer_significance(peer_rates[hospital_name], others) if n_all >= 3 else None

    ind_names = {}
    if num_code and den_code:
        for ind in _indicator_name_map(db).values():
            if ind.code in (num_code, den_code):
                ind_names[ind.code] = ind.name

    num_v = data.get(hospital_name, {}).get(num_code)
    den_v = data.get(hospital_name, {}).get(den_code)
    # Reproduce the value through the SAME central formula the comparison
    # engine used (row.formula); fall back to the spec multiplier for legacy
    # rows, and to x100 only when nothing else is known.
    expected_rate = None
    hosp_vals = data.get(hospital_name, {})
    if row.formula:
        from app.engine import indicator_calc

        try:
            formula_ast = indicator_calc.parse_expression(row.formula)
            formula_values = {
                code: hosp_vals[code]
                for code in indicator_calc.ast_codes(formula_ast)
                if hosp_vals.get(code) is not None
            }
            calculated, formula_status = indicator_calc.evaluate(
                formula_ast, formula_values)
            expected_rate = (
                round(calculated, 2)
                if formula_status == indicator_calc.STATUS_OK else None
            )
        except indicator_calc.FormulaError:
            expected_rate = None
    elif num_v is not None and den_v:
        from app.engine.rate_config import zscore_spec_for

        spec = zscore_spec_for(num_code, den_code) if num_code and den_code else None
        expected_rate = round(
            num_v / den_v * (spec.rate_multiplier if spec else 100.0), 2)

    values = _raw_values(db, hosp.id, month)
    problems = [p for p in find_data_problems(values, db)
                if p.get("indicator_code") in (num_code, den_code)]

    label = row.comparison_label
    why_bits = [
        f"|deviation| = {abs(row.deviation_pct):.1f}% — "
        + ("within" if abs(row.deviation_pct) < 10 else "beyond")
        + " the ±10% band around the peer average",
        f"percentile {row.percentile_rank} among {len(others)} peer hospitals",
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
            "formula": (f"rate = numerator/denominator×{_rate_multiplier(num_code, den_code):g};  "
                        "benchmark = mean(rate of the OTHER hospitals, self excluded);  "
                        "deviation% = (rate − benchmark)/benchmark×100;  "
                        "percentile = (peers below + 0.5×peers equal)/peers ×100"),
            "formula_readable": (
                (
                    f"{rate_name} = ({num_code} — {ind_names.get(num_code)}) / ({den_code} — {ind_names.get(den_code)}) × 100"
                    if (num_code and den_code and ind_names.get(num_code) and ind_names.get(den_code))
                    else (f"{rate_name} = rate of {hospital_name} this month" if rate_def else rate_name)
                )
                + f"; benchmark is the mean of the other {len(others)} peer hospital rates (this hospital excluded)"
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
                {"input": "Benchmark (mean of peers)", "value": row.benchmark, "role": f"mean of {len(others)} other hospital rates"},
                {"input": "Deviation %", "value": row.deviation_pct,
                 "role": "(rate − benchmark) / benchmark × 100"},
                {"input": "Percentile", "value": row.percentile_rank,
                 "role": "peer-relative position, self excluded, on a 0-100 scale"},
                {"input": "p-value", "value": p_value,
                 "role": "one-sample t-test of the other hospitals' rates against this rate (n≥3 only; indicative, not a robust test)"},
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
            {"step": "Calculation", "detail": f"rate = numerator/denominator×{_rate_multiplier(num_code, den_code):g} for every hospital; mean → benchmark",
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
            "formula": (f"rate per hospital = numerator/denominator×{_rate_multiplier(num_code, den_code):g};  "
                        "avg = sum/n;  std = population std-dev;  "
                        "coverage% = computing hospitals / active hospitals × 100"),
            "formula_readable": (
                f"Each hospital's {rate_name} = ({num_code}) / ({den_code}) × {_rate_multiplier(num_code, den_code):g} from its enabled values. "
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
            {"step": "Calculation", "detail": f"per-hospital rate = num/den×{_rate_multiplier(num_code, den_code):g}, then avg/min/max/std across hospitals"},
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
    from app.engine import indicator_service

    managed_indicators = indicator_service.resolve_active_definitions(
        db, site="zscore")
    from app.engine.config_resolver import PolicyUnavailable, load_policy_snapshot
    from app.engine.policy_view import (
        analysis_config_from_snapshot, trends_policy_from_snapshot)

    # One snapshot per explanation: the engine and the displayed thresholds
    # read the same resolved policy — never the process global, never a second
    # database read that could disagree with it.
    try:
        policy_snapshot = load_policy_snapshot(db)
    except PolicyUnavailable as exc:
        return {"error": str(exc)}
    analysis_config = analysis_config_from_snapshot(policy_snapshot)
    trends_policy = trends_policy_from_snapshot(policy_snapshot)
    trends = analyze_historical_trends(
        hosp.name, monthly_data,
        additional_indicators=managed_indicators,
        policy=trends_policy)
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
    slope = sum((xi - mx) * (yi - my) for xi, yi in zip(x, vals, strict=False)) / sum((xi - mx) ** 2 for xi in x)
    intercept = my - slope * mx
    ss_tot = sum((yi - my) ** 2 for yi in vals)
    ss_res = sum((yi - (intercept + slope * xi)) ** 2 for xi, yi in zip(x, vals, strict=False))
    r_squared = 1 - ss_res / ss_tot if ss_tot else 0.0
    slope_pct = (slope / mean_val * 100) if mean_val else 0.0
    last_val = vals[-1]
    last_vs_mean = ((last_val - mean_val) / mean_val * 100) if mean_val else 0.0

    thresholds = {
        "trend_finding_slope": trends_policy.finding_slope,
        "trend_finding_cv": trends_policy.finding_cv,
        "trend_finding_deviation": trends_policy.finding_deviation,
        # Persistence is the SAME setting System Control exposes.
        "trend_finding_consecutive": float(analysis_config.trend.min_persistence),
        # Effective temporal-trend policy (System Control).
        "trend_assessment_enabled": analysis_config.trend.enabled,
        "trend_analysis_window": analysis_config.trend.window,
        "trend_min_history_months": analysis_config.trend.min_history,
        "trend_direction": analysis_config.trend.trend_direction,
        "trend_min_cumulative_change_pct": analysis_config.trend.min_cumulative_change,
        "trend_severity_policy": analysis_config.trend.policy,
        "trend_severity_escalation": analysis_config.trend.escalation,
        "trend_severity_target": analysis_config.trend.target,
        "zscore_threshold": analysis_config.zscore_threshold,
    }

    inputs = [
        {"input": f"Rate {m}", "value": v, "role": "monthly rate used by the regression"}
        for m, v in zip(row.months, vals, strict=False)
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

    # Legacy rows without a stored formula: resolve the display multiplier
    # from the zscore registry (same helper as every other explanation here)
    # instead of hardcoding ×100, so a per-1,000 definition reads truthfully.
    from app.engine.anomaly.zscore import RATE_DEFINITIONS

    _trend_den = next((d for _rn, n, d, _tp in RATE_DEFINITIONS
                       if n == row.indicator_code), None)
    trend_mult = _rate_multiplier(row.indicator_code, _trend_den)

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
            "formula": (
                (f"rate per month = {row.formula};  " if row.formula
                 else f"rate per month = numerator/denominator×{trend_mult:g};  ")
                + "slope = linear regression over month index;  slope% = slope/mean×100;  "
                + "CV% = std/mean×100;  last_vs_mean% = (last−mean)/mean×100"),
            "formula_readable": (
                (f"Each month's {rate_name} = {row.formula}. " if row.formula
                 else f"Each month's {rate_name} = ({row.indicator_code} numerator / denominator) × {trend_mult:g}. ")
                + "A linear regression over the month index gives the slope; direction/severity "
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
            "trend_assessment": row.trend_assessment,
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


def _layered_identity_key(spec) -> str:
    """Canonical formula identity of a layered analysis unit (same key Quality
    Alerts stores in ``evidence["canonical"]["key"]``)."""
    from app.engine import canonical_identity

    if spec.is_rate:
        identity = canonical_identity.ratio_identity(
            spec.numerator_codes, spec.denominator_codes, "/",
            spec.rate_multiplier, spec.unit)
    else:
        identity = canonical_identity.stored_identity(
            None, None, spec.analysis_code)
    return canonical_identity.identity_key(identity)


_ALERT_SEVERITY_RANK = {"NONE": 0, "LOW": 1, "MODERATE": 2,
                        "HIGH": 3, "VERY_HIGH": 4}

# Display order required for the same-identity peer perspectives. A
# perspective this map does not know keeps a deterministic place after these.
_PEER_PERSPECTIVE_ORDER = {"type": 0, "ownership": 1, "governorate": 2,
                           "facility_type": 3, "all": 4}


def _peer_scale_evidence(verdict: Optional[dict], value_key: str,
                         band_key: str, usable_key: str) -> dict:
    """One robust scale exactly as the existing Rule B verdict holds it.

    ``None`` means the scale was not available (no stored peer group, or the
    gate did not judge this row). A stored ``0`` value and a stored ``False``
    usability flag are valid evidence and are preserved as such; nothing is
    recomputed here.
    """
    if not verdict or verdict.get(value_key) is None:
        return {"value": None, "band": None, "usable": None}
    return {"value": verdict.get(value_key),
            "band": verdict.get(band_key),
            "usable": verdict.get(usable_key)}


def _peer_perspective_view(alert, assessment: dict,
                           threshold: Optional[float]) -> dict:
    """One stored peer perspective of the SAME identity, for display.

    The verdict, reason code, robust-scale evidence, comparability status and
    zero-share are read from the Rule B assessment the existing cross-check
    already produced from ``evidence["comparison_policy"]``. When that stored
    group is absent, every one of them stays ``None`` (unavailable): a missing
    group is not an unverified comparison, and no verdict is inferred from the
    alert's band, its peer count or another perspective.
    """
    from app.engine import comparison_identity as identity_logic
    from app.engine.quality_alerts import PERSPECTIVE_LABELS

    identity = identity_logic.comparison_identity(alert)
    verdict = (assessment or {}).get("peer_eligibility")
    if not isinstance(verdict, dict):
        verdict = None
    return {
        "source": "quality_alerts",
        "alert_id": alert.id,
        "perspective": alert.perspective,
        "label": PERSPECTIVE_LABELS.get(alert.perspective, alert.perspective),
        # WHICH hospitals the label compared (Step 10D-5). Empty when the
        # stored evidence cannot prove a complete group: a label names why
        # the group was chosen, never the sample itself.
        "comparison_identity": identity.hash[:12] if identity.hash else None,
        "identity_hash": identity.hash,
        "peer_ids": list(identity.peer_ids),
        "evidence_state": identity.state,
        "evidence_reason": identity.reason,
        # Stored on the alert row itself.
        "peer_count": alert.peer_count,
        "current": alert.current_value,
        "threshold": threshold,
        # Rule B: both fields together carry the meaning; neither is inferred
        # from the stored band.
        "verdict": verdict.get("decision") if verdict else None,
        "reason_code": verdict.get("reason") if verdict else None,
        "mad": _peer_scale_evidence(verdict, "mad", "mad_level", "mad_usable"),
        "iqr": _peer_scale_evidence(verdict, "iqr", "iqr_level", "iqr_usable"),
        # The stored evidence does not record which scales supported the top
        # band, so it is reported unavailable rather than derived from the
        # reason code or the verdict.
        "scales_supporting": None,
        "group_comparability_status": (
            verdict.get("group_comparability_status") if verdict else None),
        "zero_share": verdict.get("zero_share") if verdict else None,
        "zero_share_warning": (
            verdict.get("zero_share_warning") if verdict else None),
    }


# Fields two rows on ONE peer identity must agree on. Identity is the peer set
# alone, so a disagreement here is one comparison with conflicting statistics,
# never a second comparison.
_IDENTITY_STAT_FIELDS = ("severity", "stored_severity", "z_score",
                         "current_value", "baseline_value", "method",
                         "peer_count", "direction")

# Helper reasons that mean "the stored list is shorter than the group", as
# opposed to evidence that was never written. Kept apart so a reader is not
# told a group is malformed when it is merely truncated.
_TRUNCATION_REASONS = ("truncated_nested_peer_ids",
                       "top_level_truncation_possible",
                       "incomplete_top_level_peer_ids")


def _identity_statistics(alert, band: str) -> dict:
    """Stored outcomes of one alert, as the identity conflict test reads them."""
    return {
        "severity": band,
        "stored_severity": alert.severity,
        "z_score": alert.z_score,
        "current_value": alert.current_value,
        "baseline_value": alert.baseline_value,
        "method": alert.method,
        "peer_count": alert.peer_count,
        "direction": alert.direction,
    }


def _join_labels(labels) -> str:
    """Join labels as prose ("a, b and c") without inventing a term."""
    items = [str(label) for label in labels if label]
    if not items:
        return "the stored rows"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _human_field(name: str) -> str:
    return name.replace("_", " ")


def _comparison_evidence(matched, shown: dict) -> dict:
    """Group one formula/month's stored perspectives by comparison IDENTITY.

    A perspective label says WHY a peer group was chosen (``all``,
    ``facility_type``, ``governorate``...); the peer set says WHICH hospitals
    were compared. Two labels over one peer set are one statistical sample, so
    they are reported once here — the grouping itself is the Step 10D-5
    correction, and no stored row, band or verdict is changed by it.

    Temporal (history) rows are a different evidence class: they are listed in
    their own ``temporal`` section and never enter a peer count. Rows whose
    stored evidence cannot prove a group are kept in ``unreadable`` with the
    helper's own reason — ``invalid`` when the evidence contradicts itself,
    ``unknown`` when it is absent or truncated — and no group is inferred from
    the label, the band or another perspective.
    """
    from app.engine import comparison_identity as identity_logic
    from app.engine.quality_alerts import PERSPECTIVE_LABELS, stored_series

    def label_of(alert) -> str:
        return PERSPECTIVE_LABELS.get(alert.perspective, alert.perspective)

    def version_of(alert):
        policy = (alert.evidence or {}).get("comparison_policy")
        block = policy.get("peer") if isinstance(policy, dict) else None
        version = block.get("policy_version") if isinstance(block, dict) else None
        return version if isinstance(version, str) and version else None

    groups: dict = {}
    temporal: list = []
    unreadable: list = []
    versions: set = set()
    for alert in matched:
        version = version_of(alert)
        if version:
            versions.add(version)
        identity = identity_logic.comparison_identity(alert)
        band = shown.get(alert.id, alert.severity)
        if identity.type == identity_logic.COMPARISON_TEMPORAL:
            series = stored_series(alert.evidence)
            temporal.append({
                "alert_id": alert.id,
                "perspective": alert.perspective,
                "label": label_of(alert),
                "state": "valid" if series else "unknown",
                "reason": None if series else "no_readable_history_window",
                "observations": len(series),
                "band": band,
                "stored_severity": alert.severity,
            })
            continue
        if identity.type == identity_logic.COMPARISON_PEER:
            entry = groups.get(identity.hash)
            if entry is None:
                entry = groups[identity.hash] = {
                    "identity": identity,
                    "perspectives": [],
                    "alert_ids": [],
                    "versions": set(),
                    "statistics": [],
                    "bands": [],
                }
            entry["perspectives"].append(alert.perspective)
            entry["alert_ids"].append(alert.id)
            if version:
                entry["versions"].add(version)
            statistics = _identity_statistics(alert, band)
            if statistics not in entry["statistics"]:
                entry["statistics"].append(statistics)
            entry["bands"].append(band)
            continue
        unreadable.append({
            "alert_id": alert.id,
            "perspective": alert.perspective,
            "label": label_of(alert),
            "state": identity.state,
            "reason": identity.reason,
        })

    keys = list(groups)
    relations: dict = {key: [] for key in keys}
    pairwise_kinds: set = set()
    for index, left in enumerate(keys):
        for right in keys[index + 1:]:
            first = groups[left]["identity"]
            second = groups[right]["identity"]
            kind = identity_logic.pairwise_relationship(first, second)
            shared = len(set(first.peer_ids) & set(second.peer_ids))
            pairwise_kinds.add(kind)
            relations[left].append({"identity": second.hash[:12],
                                    "relationship": kind,
                                    "shared_peers": shared})
            relations[right].append({"identity": first.hash[:12],
                                     "relationship": kind,
                                     "shared_peers": shared})

    def order_of(entry) -> int:
        unknown = len(_PEER_PERSPECTIVE_ORDER)
        return min(_PEER_PERSPECTIVE_ORDER.get(perspective, unknown)
                   for perspective in entry["perspectives"])

    comparisons: list = []
    for key in sorted(keys, key=lambda k: (order_of(groups[k]),
                                           sorted(groups[k]["perspectives"]))):
        entry = groups[key]
        identity = entry["identity"]
        statistics = entry["statistics"]
        conflicting: list = []
        if len(statistics) > 1:
            conflicting = sorted(
                name for name in _IDENTITY_STAT_FIELDS
                if len({row[name] for row in statistics}) > 1)
        perspectives = sorted(entry["perspectives"],
                              key=lambda p: (_PEER_PERSPECTIVE_ORDER.get(
                                  p, len(_PEER_PERSPECTIVE_ORDER)), p))
        bands = [band for band in entry["bands"] if band]
        comparisons.append({
            "identity": key[:12],
            "identity_hash": key,
            "source": identity.source,
            "peer_count": len(identity.peer_ids),
            "peer_ids": list(identity.peer_ids),
            "perspectives": perspectives,
            "perspective_labels": [PERSPECTIVE_LABELS.get(p, p)
                                   for p in perspectives],
            "perspective_rows": len(entry["alert_ids"]),
            "alert_ids": sorted(entry["alert_ids"]),
            "policy_versions": sorted(entry["versions"]),
            "effective_severity": (max(bands, key=lambda band:
                                       _ALERT_SEVERITY_RANK.get(band, 0))
                                   if bands else None),
            "stored_severities": sorted({row["stored_severity"]
                                         for row in statistics},
                                        key=lambda name: name or ""),
            "relationships": relations[key],
            "evidence_conflict": bool(conflicting),
            "conflict_fields": conflicting,
        })

    peer_rows = sum(item["perspective_rows"] for item in comparisons)
    unknown = [item for item in unreadable if item["state"] != "invalid"]
    invalid = [item for item in unreadable if item["state"] == "invalid"]
    evidence = {
        "perspective_rows": len(matched),
        "peer_rows": peer_rows,
        "distinct_peer_comparisons": len(comparisons),
        # Labels that point at a peer set already counted. Published so a
        # reader can reconcile "8 cards" with "7 comparisons" without guessing.
        "duplicate_perspective_rows": peer_rows - len(comparisons),
        "comparisons": comparisons,
        "temporal_rows": len(temporal),
        "temporal": temporal,
        "temporal_present": bool(temporal),
        "temporal_state": (("valid" if any(item["state"] == "valid"
                                           for item in temporal) else "unknown")
                           if temporal else None),
        "unknown_rows": len(unknown),
        "unknown_evidence_present": bool(unknown),
        "invalid_rows": len(invalid),
        "invalid_evidence_present": bool(invalid),
        "truncated_evidence_present": any(
            item["reason"] in _TRUNCATION_REASONS for item in unreadable),
        "evidence_conflict": any(item["evidence_conflict"]
                                 for item in comparisons),
        "policy_mixed": len(versions) > 1,
        "policy_versions": sorted(versions),
        "relationships": sorted(pairwise_kinds),
        "unreadable": unreadable,
    }
    evidence["narrative"] = _comparison_narrative(evidence)
    return evidence


def _comparison_narrative(evidence: dict) -> dict:
    """Plain sentences describing the comparison structure (no markup).

    Each sentence states which labels pointed at which sample, whether the
    samples nest, overlap or share nothing, and what could not be read. Peer-set
    membership is described only with ``nested`` / ``overlapping`` /
    ``disjoint``; statistical agreement is never called clinical confirmation,
    and disjoint groups are never called independent comparisons.
    """
    comparisons = evidence["comparisons"]
    perspective_rows = evidence["perspective_rows"]
    duplicates = evidence["duplicate_perspective_rows"]
    if not comparisons:
        summary = ("No stored label on this formula holds a complete peer "
                   "group, so no peer comparison is described here.")
    elif len(comparisons) == 1:
        labels = _join_labels(comparisons[0]["perspective_labels"])
        if duplicates:
            summary = (f"{perspective_rows} stored perspective labels describe "
                       f"one peer comparison: {labels} name the same peer set, "
                       "so they are counted once.")
        else:
            summary = (f"One stored perspective label ({labels}) describes one "
                       "peer comparison.")
    else:
        summary = (f"{perspective_rows} stored perspective labels describe "
                   f"{len(comparisons)} distinct peer comparisons.")
        if duplicates:
            summary += (f" {duplicates} of those labels name a peer set that is "
                        "already counted, so they add no second comparison.")

    described: list = []
    for comparison in comparisons:
        described.append(
            f"{_join_labels(comparison['perspective_labels'])}: "
            f"{comparison['peer_count']} peer hospitals, "
            f"{comparison['perspective_rows']} label(s), effective severity "
            f"{comparison['effective_severity'] or 'NONE'}.")

    by_identity = {item["identity"]: item for item in comparisons}
    relationships: list = []
    seen: set = set()
    for comparison in comparisons:
        for relation in comparison["relationships"]:
            pair = frozenset((comparison["identity"], relation["identity"]))
            if pair in seen:
                continue
            seen.add(pair)
            other = by_identity.get(relation["identity"])
            if other is None:
                continue
            left = _join_labels(comparison["perspective_labels"])
            right = _join_labels(other["perspective_labels"])
            kind = relation["relationship"]
            if kind == "nested":
                text = (f"{left} peers and {right} peers are nested: one group "
                        f"is contained in the other ({relation['shared_peers']} "
                        "shared hospitals), so the smaller row compares part of "
                        "the same sample.")
            elif kind == "overlapping":
                text = (f"{left} peers and {right} peers overlap: they share "
                        f"{relation['shared_peers']} hospitals but neither group "
                        "contains the other.")
            elif kind == "disjoint":
                text = (f"{left} peers and {right} peers are disjoint: they "
                        "share no hospital, so neither row repeats the other's "
                        "evidence.")
            else:
                text = (f"The relationship between {left} and {right} cannot be "
                        "determined from the stored peer groups.")
            relationships.append(text)

    if evidence["temporal"]:
        if any(item["state"] == "valid" for item in evidence["temporal"]):
            temporal_text = ("The history perspective is temporal evidence, not "
                             "a peer comparison: it compared the hospital with "
                             "its own earlier months and is counted on its own, "
                             "never in the peer counts above.")
        else:
            temporal_text = ("The history perspective stores no readable "
                             "window, so its temporal comparison is unknown; it "
                             "is not turned into a peer comparison.")
    else:
        temporal_text = None

    caveats: list = []
    for item in evidence["unreadable"]:
        if item["state"] == "invalid":
            caveats.append(
                f"{item['label']}: the stored peer evidence contradicts itself "
                f"({_human_field(item['reason'] or 'unspecified')}), so it is "
                "not counted as a comparison.")
        elif item["reason"] in _TRUNCATION_REASONS:
            caveats.append(
                f"{item['label']}: the stored peer list is incomplete, so the "
                "comparison cannot be established and is reported as unknown.")
        else:
            caveats.append(
                f"{item['label']}: the stored evidence does not name which "
                "hospitals were compared "
                f"({_human_field(item['reason'] or 'no reason recorded')}), so "
                "the comparison is unknown.")
    for comparison in comparisons:
        if comparison["evidence_conflict"]:
            fields = ", ".join(_human_field(name)
                               for name in comparison["conflict_fields"])
            caveats.append(
                f"{_join_labels(comparison['perspective_labels'])}: rows on this "
                f"one peer set disagree on {fields}; that is conflicting "
                "statistics on one comparison, not a second comparison.")
    if evidence["policy_mixed"]:
        caveats.append(
            "More than one comparison-policy version is stored for this formula "
            f"({', '.join(evidence['policy_versions'])}); the difference is "
            "provenance, not another sample.")

    return {
        "labels_vs_comparisons": summary,
        "comparisons": described,
        "relationships": relationships,
        "temporal": temporal_text,
        "caveats": caveats,
    }


def _quality_alert_cross_check(db: Session, row, spec, hospital_id: int,
                               month: str, recomputed=None,
                               level_assessment=None) -> dict:
    """How the stored Quality Alerts for this formula/month compare with the
    diagnostic row, and why any difference exists.

    Quality Alerts scores several peer perspectives as separate labels; Outlier
    Diagnostics classifies against ONE detection baseline (all active reporting
    hospitals). A stratified perspective (governorate, ownership, ...) may
    legitimately be more severe, and this block states that instead of leaving
    two screens to look contradictory.

    ``level_assessment`` is the caller's ``(displayed band, cap provenance)``
    for this row. The popup assesses the row once and passes the result here,
    so the headline and this block quote the same band by construction.

    Matching is by formula, not by whichever code happens to hold it: the
    stored (or current) code, the canonical evidence block, and the canonical
    identity of the alert's OWN stored formula are all accepted, so alerts
    written before the canonical evidence block existed still match.
    """
    from app.engine import canonical_identity
    from app.engine.anomaly.layered import (
        LEVEL_NONE,
        LEVEL_RANK,
        MIN_PEERS_FOR_TOP_BAND,
        ROUTE_PEER,
        cap_thin_peer,
        cap_zero_spread,
        level_for_score,
        peer_z_provenance,
        row_level_assessment,
        row_very_high_eligibility,
        thin_peer_group,
    )
    from app.engine.quality_alerts import (
        PERSPECTIVE_LABELS,
        alert_route,
        effective_severity,
        eligibility_assessment,
        is_open_status,
        peer_definition_codes,
        peer_gate_inputs,
        severity_cap,
        stored_series,
        stored_threshold,
    )
    from app.models import QualityAlert

    alerts = (
        db.query(QualityAlert)
        .filter(QualityAlert.hospital_id == hospital_id,
                QualityAlert.month == month,
                QualityAlert.active.is_(True))
        .all()
    )
    identity = _layered_identity_key(spec)
    matched = []
    for alert in alerts:
        canonical = (alert.evidence or {}).get("canonical") or {}
        stored_identity = canonical_identity.identity_key(
            canonical_identity.alert_identity(alert))
        if (alert.indicator_code == row.analysis_code
                or row.analysis_code in (canonical.get("registered_codes") or [])
                or canonical.get("key") == identity
                or stored_identity == identity):
            matched.append(alert)

    stratified_perspectives = {"type", "ownership", "facility_type",
                              "governorate"}
    # The definition gate's catalog, resolved ONCE for this row's alerts and
    # only when one of them is a peer comparison: the history path never asks
    # for it. The band above is unaffected either way (Rule B cannot move one).
    peer_catalog = (peer_definition_codes(db)
                   if any(alert_route(a.perspective, a.method) == ROUTE_PEER
                           for a in matched) else None)
    perspectives = []
    peer_perspectives = []
    shown_by_id = {}
    for alert in matched:
        scope = (((alert.evidence or {}).get("comparison_policy") or {})
                 .get("perspective_scope"))
        if not scope:
            # Alerts written before the provenance block existed: the
            # perspective itself states the scope unambiguously.
            scope = ("detection_baseline" if alert.perspective == "all"
                     else "history" if alert.perspective == "history"
                     else "stratified" if alert.perspective in stratified_perspectives
                     else "unknown")
        stats = (alert.evidence or {}).get("stats")
        series = stored_series(alert.evidence)
        # The gate's inputs, exactly as the Quality Alerts screen reads them:
        # the stored window, the compared value, the row's own threshold and the
        # perspective that produced the band.
        threshold = stored_threshold(alert.evidence)
        gate_inputs = {"current": alert.current_value,
                       "perspective": alert.perspective,
                       "threshold": threshold}
        cap = severity_cap(alert.severity, stats=stats, method=alert.method,
                           peer_count=alert.peer_count, series=series,
                           **gate_inputs)
        shown = effective_severity(alert.severity, stats=stats,
                                   method=alert.method,
                                   peer_count=alert.peer_count,
                                   series=series,
                                   **gate_inputs) or alert.severity
        shown_by_id[alert.id] = shown
        eligibility = eligibility_assessment(
            alert.severity, stats=stats, method=alert.method,
            peer_count=alert.peer_count, series=series, **gate_inputs,
            **peer_gate_inputs(alert, peer_catalog))
        # The level the policy refuses to this row, before the cap that
        # lowered it (zero-spread, then the thin peer group, then the top-band
        # eligibility gate for the history perspective).
        capped_from = None
        for reason in ("dispersion", "thin_peer_group",
                       "very_high_eligibility"):
            entry = (cap or {}).get(reason) or {}
            if entry.get("capped"):
                capped_from = entry.get("resolved_level")
                break
        entry = {
            "perspective": alert.perspective,
            "label": PERSPECTIVE_LABELS.get(alert.perspective,
                                            alert.perspective),
            "scope": scope or "unknown",
            # The band the QUALITY ALERTS SCREEN shows: the same approved cap
            # policy, recomputed from this row's own evidence by the shared
            # rule. Quoting the stored band here made the two screens name
            # different severities for one stored row.
            "severity": shown,
            "stored_severity": alert.severity,
            "severity_cap": cap,
            # The routed verdict stated even when nothing was capped, so this
            # popup can say "the window could not judge it" instead of leaving
            # an undecided row reading as an ordinary top-band finding.
            "top_band_eligibility": eligibility,
            "score": alert.score,
            "peer_count": alert.peer_count,
            "baseline_value": alert.baseline_value,
            # The band is lower than the score implies because the comparison
            # could not be graded (no dispersion, or too few peers to measure
            # a spread) — see the comparison policy doc.
            "level_capped": capped_from is not None,
            "capped_from": capped_from,
            # Investigation state (Quality Alerts spec §10). A closed alert
            # (Resolved / False Positive) no longer raises on the Quality
            # Alerts screen, so it must not be presented here as a live second
            # verdict — but it is still stored evidence and is named as such.
            "status": alert.status,
            "closed": not is_open_status(alert.status),
        }
        perspectives.append(entry)
        if (alert_route(alert.perspective, alert.method) == ROUTE_PEER
                and shown == "VERY_HIGH"):
            # The same identity's separate peer perspectives, in their own
            # collection. Only a perspective the Quality Alerts screen still
            # shows at the top band is a peer-claim counterpart to this
            # Diagnostics divergence; lower bands raise no contradiction.
            # Nothing is re-queried or re-matched here: they come from the loop
            # above, and the Rule B verdict is the one the existing cross-check
            # already computed from the stored
            # ``evidence["comparison_policy"]`` group.
            peer_perspectives.append(
                _peer_perspective_view(alert, eligibility, threshold))
    perspectives.sort(
        key=lambda p: (_ALERT_SEVERITY_RANK.get(p["severity"], 0),
                       p["score"] or 0.0),
        reverse=True)
    peer_perspectives.sort(
        key=lambda p: (_PEER_PERSPECTIVE_ORDER.get(p["perspective"], 99),
                       p["alert_id"] or 0))

    # Which peer SET each label compared (Step 10D-5). Labels name why a
    # group was chosen; they do not name the sample. Grouping by comparison
    # identity lets the popup say "two labels, one comparison" instead of
    # reporting one stored sample twice, and keeps temporal and unreadable
    # evidence in their own sections.
    comparison_evidence = _comparison_evidence(matched, shown_by_id)

    # The peer band the DIAGNOSTIC row can claim. A comparison group whose
    # members all reported the same value has no spread, so the peer layer's
    # 1.0 cannot grade a magnitude: the same cap the classifier applies is
    # re-applied here instead of quoting the uncapped band next to a capped
    # alert.
    prov = row.classification_provenance or {}
    peer_degenerate = "peer" in (prov.get("zero_spread_layers") or ())
    # Too few peers to measure a spread: the classifier capped the peer band at
    # HIGH, so this popup must quote the same band rather than the uncapped one.
    peer_thin = "peer" in (prov.get("thin_peer_layers") or ())
    if not prov:
        # Legacy row: the stored peer group's values are the ground truth.
        stored_values = list(((row.peer_provenance or {}).get("values") or {})
                             .values())
        peer_degenerate = (len(stored_values) >= 2
                           and len(set(stored_values)) == 1)
        peer_thin = thin_peer_group(row.peer_count, "peer_zscore")
    detection_peer_level = level_for_score(row.peer_outlier_score)
    if peer_degenerate:
        detection_peer_level, _ = cap_zero_spread(
            detection_peer_level, 0.0, "peer_zscore")
    if peer_thin:
        detection_peer_level, _ = cap_thin_peer(
            detection_peer_level, row.peer_count, "peer_zscore")
    # The STORED row may predate the current classification policy. Compare the
    # alerts with what the row recomputes to now, and say so: otherwise a stale
    # NORMAL row next to a HIGH alert reads as a contradiction the popup cannot
    # explain.
    current_type = recomputed.outlier_type if recomputed is not None else row.outlier_type
    current_level = (recomputed.outlier_level if recomputed is not None
                     else row.outlier_level)
    stale = (recomputed is not None
             and (current_type != row.outlier_type
                  or current_level != row.outlier_level))
    stale_note = (
        f" Under the current classification policy this row recomputes to "
        f"{current_type} {current_level} (stored: {row.outlier_type or 'NORMAL'} "
        f"{row.outlier_level or 'NONE'}) — recalculate this month."
        if stale else "")
    # The band the DIAGNOSTICS SCREEN shows is the one the approved policy
    # allows for this stored row (``row_level_assessment``, which the table,
    # the filters and the badge all read), not the band left on disk. Comparing
    # against the stored band made this block answer at a severity no screen
    # displays — a gated row was compared at VERY_HIGH while the table beside
    # the popup printed HIGH.
    stored_level = row.outlier_level or LEVEL_NONE
    if level_assessment is not None:
        displayed_level, level_cap = level_assessment
    else:
        displayed_level, level_cap = row_level_assessment(row)
    stored_level_refused = (LEVEL_RANK.get(stored_level, 0)
                            > LEVEL_RANK.get(displayed_level, 0))
    diagnostic = {
        "type": row.outlier_type,
        # ``level`` keeps its historical meaning: the band stored on the row.
        # The popup's sentences compare against ``displayed_level`` — the band
        # the Diagnostics screen renders (``effective_level`` is its alias) —
        # so a reader can see the stored band and the screen band side by side.
        "level": stored_level,
        "stored_level": stored_level,
        "displayed_level": displayed_level,
        "effective_level": displayed_level,
        "stored_level_refused": stored_level_refused,
        # Which rule refused the stored band, for the popup's own band line.
        "severity_cap": level_cap,
        "recomputed_type": current_type,
        "recomputed_level": current_level,
        "recomputed_differs": bool(stale),
        "peer_score": row.peer_outlier_score,
        "peer_level": detection_peer_level,
        "peer_count": row.peer_count,
        "history_ok": row.historical_outlier_score is not None,
        "zero_spread_layers": list(prov.get("zero_spread_layers") or ()),
        "peer_zero_spread": peer_degenerate,
        "thin_peer_layers": list(prov.get("thin_peer_layers") or ()),
        "peer_thin_group": peer_thin,
        "min_peers_for_top_band": MIN_PEERS_FOR_TOP_BAND,
        # Whether the peer comparison could produce a z-score at all (too few
        # peers to measure a spread -> no z, score and peer list kept).
        "peer_z": peer_z_provenance(row.peer_count),
        # The routed top-band verdict for THIS row: history claims are judged by
        # the window, peer/volume claims are deliberately left undecided, and a
        # refusal only ever moves the band to HIGH. Stated apart from ``level``
        # so a reader can tell "not judged" from "judged and refused".
        "top_band_eligibility": row_very_high_eligibility(row),
    }
    policy = ("Quality Alerts scores each labelled perspective (history, type, "
              "ownership, facility type, governorate, all hospitals); Outlier "
              "Diagnostics classifies against the single all-hospital detection "
              "baseline and its own-history baseline.")
    peer_score_text = (f"{row.peer_outlier_score:.2f}"
                       if row.peer_outlier_score is not None else "n/a")
    history_text = (
        "the hospital's own history is not assessable."
        if current_type == "INSUFFICIENT_HISTORY"
        else "the hospital's own history could not be assessed either."
        if current_type == "PEER_ANOMALY" and row.historical_outlier_score is None
        else "its own history stayed within its band.")

    # Compare with the strongest alert the QUALITY ALERTS SCREEN STILL RAISES:
    # a closed row is kept as evidence, but it cannot be the verdict the other
    # screen is showing. With every matched alert closed, the closed one is
    # used and the explanation says why it no longer alerts.
    open_perspectives = [p for p in perspectives if not p["closed"]]
    strongest = ((open_perspectives or perspectives or [None])[0])
    closed_note = (
        " The matching Quality Alert was closed by a reviewer (Resolved / "
        "skipped as False Positive), so it no longer raises on the Quality "
        "Alerts screen; closing records the investigation decision and changes "
        "neither detection result."
        if perspectives and not open_perspectives else ""
    )
    if strongest is None:
        agreement = "no_stored_alert"
        explanation = ("No active Quality Alert is stored for this formula and "
                       "month, so there is no second verdict to compare with. "
                       "Re-scan the month if an alert was expected." + stale_note)
    elif (strongest["scope"] == "stratified"
          and (_ALERT_SEVERITY_RANK.get(displayed_level, 0)
               < _ALERT_SEVERITY_RANK.get(strongest["severity"], 0))):
        agreement = "differs_by_perspective"
        explanation = (
            f"Quality Alerts reports {strongest['severity']} under "
            f"\"{strongest['label']}\" (n={strongest['peer_count']}), a narrower "
            "stratified comparison. Outlier Diagnostics classifies this row "
            f"{current_type or 'NORMAL'} at {displayed_level or 'NONE'} against the "
            "single all-hospital detection baseline "
            f"(peer score {peer_score_text} / {detection_peer_level or 'not available'}), "
            f"and {history_text}" + stale_note)
    elif (strongest["scope"] == "history"
          and (_ALERT_SEVERITY_RANK.get(displayed_level, 0)
               < _ALERT_SEVERITY_RANK.get(strongest["severity"], 0))):
        agreement = "differs"
        explanation = (
            "The stored history-perspective alert is more severe than this "
            "diagnostic row although both use the same history baseline; "
            "recalculate the month before relying on either." + stale_note)
    elif (_ALERT_SEVERITY_RANK.get(strongest["severity"], 0)
          > _ALERT_SEVERITY_RANK.get(displayed_level, 0)):
        agreement = "differs"
        explanation = (
            f"The stored alert ({strongest['severity']}, \"{strongest['label']}\") "
            f"is more severe than this diagnostic row ({displayed_level or 'NONE'}) "
            "under the same detection baseline, so the two stored results "
            "disagree." + (stale_note or " Recalculate this month to reconcile them."))
    elif (strongest.get("level_capped")
          and _ALERT_SEVERITY_RANK.get(displayed_level, 0)
          > _ALERT_SEVERITY_RANK.get(strongest["severity"], 0)):
        # The two screens disagree because the alert's band was capped, not
        # because either computed something different: the comparison could not
        # be graded, so it cannot claim the top band. Which cap applied is
        # named, so the reader is not told "no dispersion" about a record whose
        # comparison group was simply too small.
        cap = strongest.get("severity_cap") or {}
        reasons = []
        if (cap.get("dispersion") or {}).get("capped"):
            reasons.append(
                "every hospital in that comparison reported the same value, so "
                "the deviation has no measurable scale")
        if (cap.get("thin_peer_group") or {}).get("capped"):
            reasons.append(
                f"the comparison group holds {strongest['peer_count']} other "
                f"hospital(s) and measuring a spread needs at least "
                f"{MIN_PEERS_FOR_TOP_BAND}, so its z-score is not a measurement")
        gate = cap.get("very_high_eligibility") or {}
        if gate.get("capped") and gate.get("eligible") is False:
            reasons.append(
                "the hospital's own history window does not support the top "
                "band (the same window's dispersion-aware band is "
                f"{gate.get('dispersion_band') or 'below VERY_HIGH'})")
        if not reasons:
            # The cap is recorded but names no clause this popup knows: say what
            # the cap does instead of printing an empty reason list.
            reasons.append(
                "the approved cap policy refuses the top band for this "
                "comparison")
        agreement = "differs"
        explanation = (
            f"The stored alert was written {strongest['stored_severity']}, but "
            f"the approved cap policy assigns it {strongest['severity']} "
            f"(\"{strongest['label']}\"): " + "; ".join(reasons)
            + ". Quality Alerts shows that policy band while Outlier Diagnostics "
            "classifies the peer layer without the cap "
            f"({current_type or 'NORMAL'} at {displayed_level or 'NONE'}). The "
            f"stored row keeps {strongest['stored_severity']} until the month is "
            "re-scanned." + stale_note)
    else:
        agreement = "agree"
        explanation = (
            "Quality Alerts and Outlier Diagnostics agree: the most severe stored "
            f"alert ({strongest['severity']}, \"{strongest['label']}\") is "
            f"consistent with this diagnostic level ({displayed_level or 'NONE'}).")

    return {
        "agreement": agreement,
        "explanation": explanation + closed_note,
        "policy": policy,
        "diagnostic": diagnostic,
        "strongest_alert": strongest,
        "perspectives": perspectives,
        "peer_perspectives": peer_perspectives,
        "comparison_evidence": comparison_evidence,
    }


def explain_layered_outlier(db: Session, hospital_id: int, month: str,
                            analysis_code: str) -> dict:
    """Layered-outlier row explanation (design spec §9).

    The persisted row is the source of truth for type/level/route/
    interpretation — exactly what the dashboards show. The rule NUMBER is
    not persisted, so it is recovered by re-running the pure classification
    function over the stored layer scores; when the re-run no longer matches
    the row (history changed since the analysis ran) the payload says so
    instead of inventing a rule."""
    from app.engine.anomaly.classify import RULE2_MIN_CHANGE_PERCENT, classify_layered
    from app.engine.anomaly.layered import (
        LEVEL_NONE,
        LEVEL_RANK,
        MIN_PEERS_FOR_TOP_BAND,
        THIN_PEER_LEVEL_CAP,
        ZERO_SPREAD_LEVEL_CAP,
        build_analysis_specs,
        level_for_score,
        peer_z_measurable,
        peer_z_provenance,
        prior_months,
        rate_analysis_value,
        raw_analysis_value,
        thin_peer_group,
    )
    from app.engine.comparison_policy import load_comparison_policy
    from app.engine.pipeline import get_historical_months

    row = (
        db.query(LayeredOutlierResult)
        .filter(
            LayeredOutlierResult.hospital_id == hospital_id,
            LayeredOutlierResult.month == month,
            LayeredOutlierResult.analysis_code == analysis_code,
        )
        .first()
    )
    if row is None:
        return {"error": (f"No layered outlier row for hospital {hospital_id}, "
                          f"{month}, {analysis_code!r}")}

    spec = {s.analysis_code: s for s in build_analysis_specs(db)}.get(analysis_code)
    if spec is None:
        return {"error": f"Unknown analysis code: {analysis_code!r}"}

    hosp = _hospital(db, hospital_id)

    # Same pair, same threshold the engine used (prior_months splits off the
    # current month; get_historical_months excludes it — plan Task 12). The
    # sufficiency test is the ENGINE's: the shared policy window and a minimum
    # of VALID observations (the per-indicator floor included). Counting
    # calendar months here made the popup claim a history was sufficient when
    # the analysed value was missing for part of it, and then report the row
    # as unreproducible for a reason that did not exist.
    history = get_historical_months(db, hospital_id, month)
    history_policy = load_comparison_policy(db).history.with_item_minimum(
        spec.minimum_history_period)
    prior = prior_months(history, month, history_policy.window)
    valid_prior = []
    for prior_month in prior:
        value = (rate_analysis_value(spec, history[prior_month])
                 if spec.is_rate
                 else raw_analysis_value(spec, history[prior_month]))
        if value is not None:
            valid_prior.append(value)
    history_ok = len(valid_prior) >= history_policy.min_observations
    den_ok = (row.denominator is not None and row.denominator > 0) if spec.is_rate else True

    # The stored row records WHICH layers could not grade a magnitude (spread
    # 0). The re-run must apply the same cap, or a row that is correct under
    # the policy would look unreproducible. Rows written before the policy
    # carry NULL: the re-run then derives the cap from the stored scores and
    # the popup reports the row as needing recalculation.
    stored_provenance = row.classification_provenance or {}
    recomputed = classify_layered(
        spec,
        raw_score=row.raw_value_outlier_score,
        rate_score=row.rate_outlier_score,
        hist_score=row.historical_outlier_score,
        volume_score=row.volume_anomaly_score,
        peer_score=row.peer_outlier_score,
        den_ok=den_ok,
        history_ok=history_ok,
        change_percent=row.historical_change_percent,
        denominator=row.denominator,
        degenerate_layers=tuple(stored_provenance.get("zero_spread_layers")
                                or ()),
        # A row written before this policy carries no list; the recompute then
        # reports it as stale rather than silently re-deriving the cap.
        thin_peer_layers=tuple(stored_provenance.get("thin_peer_layers") or ()),
    )
    verified = (recomputed.outlier_type == row.outlier_type
                and recomputed.outlier_level == row.outlier_level)
    rule_number = recomputed.rule_number if verified else None

    raw_change_percent = None
    if row.raw_value is not None and row.previous_value:
        raw_change_percent = ((float(row.raw_value) - float(row.previous_value))
                              / float(row.previous_value) * 100.0)
    den_change_percent = None
    if spec.is_rate and row.denominator is not None and row.previous_denominator:
        den_change_percent = ((float(row.denominator) - float(row.previous_denominator))
                              / float(row.previous_denominator) * 100.0)
    rate_change_percent = None
    if spec.is_rate and row.rate is not None and row.previous_value is not None and row.previous_denominator:
        previous_rate = float(row.previous_value) / float(row.previous_denominator) * spec.rate_multiplier
        if previous_rate:
            rate_change_percent = (float(row.rate) - previous_rate) / previous_rate * 100.0

    inputs = {
        "raw_value": row.raw_value,
        "previous_value": row.previous_value,
        "raw_change_percent": raw_change_percent,
        "rate": row.rate,
        "rate_change_percent": rate_change_percent,
        "denominator": row.denominator,
        "previous_denominator": row.previous_denominator,
        "denominator_change_percent": den_change_percent,
        "historical_mean": row.historical_mean,
        "historical_median": row.historical_median,
        "historical_std": row.historical_std,
        "historical_z_score": row.historical_z_score,
        "historical_change_percent": row.historical_change_percent,
        "peer_mean": row.peer_mean,
        "peer_count": row.peer_count,
        "recorded_method": row.outlier_method,
        "scores": {
            "raw": row.raw_value_outlier_score,
            "rate": row.rate_outlier_score,
            "historical": row.historical_outlier_score,
            "volume": row.volume_anomaly_score,
            "peer": row.peer_outlier_score,
        },
    }

    if spec.is_rate:
        num = " + ".join(spec.numerator_codes)
        den = " + ".join(spec.denominator_codes)
        formula = f"({num}) / ({den}) × {spec.rate_multiplier:g}"
        formula_readable = f"{spec.name} = ({num}) / ({den}) × {spec.rate_multiplier:g}"
    else:
        formula = f"count({analysis_code})"
        formula_readable = f"{spec.name} = count of indicator {analysis_code}"

    degenerate_layers = tuple(recomputed.zero_spread_layers)
    thin_peer_layers = tuple(recomputed.thin_peer_layers)

    def _layer(key, name, value, score, detail):
        level = LEVEL_NONE if score is None else level_for_score(score)
        capped = (key in degenerate_layers
                  and LEVEL_RANK.get(level, 0)
                  > LEVEL_RANK[ZERO_SPREAD_LEVEL_CAP])
        if capped:
            level = ZERO_SPREAD_LEVEL_CAP
        peer_capped = (key in thin_peer_layers
                       and LEVEL_RANK.get(level, 0)
                       > LEVEL_RANK[THIN_PEER_LEVEL_CAP])
        if peer_capped:
            level = THIN_PEER_LEVEL_CAP
        return {
            "key": key,
            "name": name,
            "value": value,
            "score": score,
            # The strip must show the band the row actually carries, not the
            # band a zero-dispersion or thin-peer score would imply on its own.
            "level": level,
            "detail": detail,
            "zero_spread": key in degenerate_layers,
            "thin_peer_group": key in thin_peer_layers,
            # A comparison group too small to measure a spread produces no
            # z-score even when another layer carries the band, so the strip
            # says so on the peer layer itself (layered.PEER_Z_POLICY).
            "peer_z_withheld": (key == "peer" and score is not None
                                and not peer_z_measurable(row.peer_count)),
            "min_peers_for_top_band": MIN_PEERS_FOR_TOP_BAND,
        }

    if row.raw_value is None:
        raw_value_text = "not computable"
    elif row.previous_value:
        raw_value_text = (f"{row.raw_value:g} (previous {row.previous_value:g}, "
                          f"{raw_change_percent:+.1f}%)")
    else:
        raw_value_text = f"{row.raw_value:g}"

    if not spec.is_rate:
        rate_value_text = "not applicable (count indicator)"
        volume_value_text = "not applicable (count indicator)"
    elif row.rate is None or not den_ok:
        rate_value_text = "not computable (denominator missing or zero)"
        volume_value_text = "not computable (denominator missing or zero)"
    else:
        rate_value_text = f"{row.rate:g}{(' ' + spec.unit) if spec.unit else ''}"
        if row.previous_denominator and den_change_percent is not None:
            volume_value_text = (f"{row.denominator:g} (previous "
                                 f"{row.previous_denominator:g}, {den_change_percent:+.1f}%)")
        else:
            volume_value_text = f"{row.denominator:g}"

    if row.historical_mean is None:
        historical_value_text = "insufficient history"
    elif row.historical_change_percent is not None:
        historical_value_text = (f"{row.historical_change_percent:+.1f}% vs baseline "
                                 f"mean {row.historical_mean:g}")
    else:
        historical_value_text = f"{row.historical_mean:g}"

    if row.peer_mean is not None and row.peer_count:
        peer_value_text = f"{row.peer_mean:g} across {row.peer_count} peer hospitals"
    else:
        peer_value_text = "not computable (fewer than 2 hospitals reported it)"

    # The peer layer's z is only produced when the group can measure a spread
    # (layered.PEER_Z_POLICY): a group of 2-3 hospitals cannot, and the row
    # keeps its score and its peer list without a z.
    peer_detail = ("every hospital reporting the indicator this month "
                   "(≥ 2 others), self excluded")
    if thin_peer_group(row.peer_count, "peer_zscore"):
        peer_detail += (
            f". Fewer than {MIN_PEERS_FOR_TOP_BAND} peer hospitals cannot "
            "measure a spread, so no z-score is produced for this comparison")

    layers = [
        _layer("raw", "Raw value", raw_value_text, row.raw_value_outlier_score,
               "this month's analysis value vs its own recent distribution"),
        _layer("rate", "Rate", rate_value_text, row.rate_outlier_score,
               "rate vs its own recent distribution" if spec.is_rate
               else "count indicators have no separate rate layer"),
        _layer("historical", "Historical baseline", historical_value_text,
               row.historical_outlier_score,
               f"{len(valid_prior)} valid prior months against a "
               f"{history_policy.min_observations}-observation minimum"),
        _layer("volume", "Patient volume", volume_value_text, row.volume_anomaly_score,
               "denominator change guards against volume-driven spikes" if spec.is_rate
               else "count indicators have no denominator layer"),
        _layer("peer", "Peer comparison", peer_value_text, row.peer_outlier_score,
               peer_detail),
    ]

    # The band every screen shows for a STORED row: the Diagnostics table, its
    # level filters, its badge and this popup's cross-check all read
    # ``row_level_assessment`` (the approved caps + the history top-band gate).
    # The headline below quotes THAT band, never the band left on disk, so the
    # popup and the table beside it cannot print different severities for one
    # row. The stored band stays available as ``outlier_level``; it is never
    # rewritten here.
    from app.engine.anomaly.layered import row_level_assessment

    displayed_level, level_cap = row_level_assessment(row)

    # The hospital's own month-by-month series for the flagged indicator. A
    # layered verdict is a statement about THIS hospital's history ("+150% vs
    # baseline"), so the shape it is judged against belongs in the popup — the
    # reviewer should not have to leave for the trend chart to see it. Capped:
    # the popup draws a sparkline, not an archive.
    series_rows = (
        db.query(LayeredOutlierResult)
        .filter(
            LayeredOutlierResult.hospital_id == hospital_id,
            LayeredOutlierResult.analysis_code == analysis_code,
        )
        .order_by(LayeredOutlierResult.month.asc())
        .all()
    )
    series = [
        {
            "month": r.month,
            "value": r.raw_value,
            "rate": r.rate,
            "type": r.outlier_type,
            # ``level`` keeps its historical meaning: the band STORED on that
            # month's row. ``displayed_level`` is the band the Diagnostics
            # screen renders for it, so the legend can label the two apart
            # instead of presenting a stored band as the effective one.
            "level": r.outlier_level,
            "displayed_level": row_level_assessment(r)[0],
            "current": r.month == month,
        }
        for r in series_rows
    ][-18:]
    # Which column the popup must plot. The historical and peer layers both
    # z-score the RATE for a rate indicator (spec.is_rate), so drawing the raw
    # numerator there would put the series and its baselines on different
    # rulers. The unit travels with the payload rather than being re-derived
    # in the browser from a name or a type string.
    series_unit = "rate" if spec.is_rate else "raw"

    if row.raw_value is not None and raw_change_percent is not None:
        what = (f"{spec.name} {row.raw_value:g} vs {row.previous_value:g} previous "
                f"({raw_change_percent:+.0f}%) — {row.outlier_type} "
                f"({displayed_level} level)")
    else:
        what = f"{spec.name} — {row.outlier_type} ({displayed_level} level)"

    if verified and rule_number is not None:
        why = (f"Rule {rule_number} of the layered rule table fired → "
               f"{row.outlier_type}. {row.interpretation}")
    else:
        why = ("The stored classification no longer matches the current history "
               f"(recomputed: {recomputed.outlier_type}) — recalculate this month. "
               f"Stored interpretation: {row.interpretation}")

    # The assessment travels to the cross-check instead of being recomputed:
    # one stored row, one verdict, so the headline and the block below it are
    # structurally unable to disagree.
    cross_check = _quality_alert_cross_check(
        db, row, spec, hospital_id, month, recomputed,
        level_assessment=(displayed_level, level_cap),
    )
    if cross_check["agreement"] in ("differs", "differs_by_perspective"):
        # Two screens must not appear to contradict each other without the
        # popup naming the reason.
        why = f"{why} {cross_check['explanation']}"
    reproduce = {
        "inputs": inputs,
        "history_ok": history_ok,
        "history_months": len(prior),
        "valid_history_observations": len(valid_prior),
        "history_policy": history_policy.as_dict(),
        "zero_spread_layers": list(recomputed.zero_spread_layers),
        "thin_peer_layers": list(recomputed.thin_peer_layers),
        "peer_z": peer_z_provenance(row.peer_count),
        "level_from_layers": recomputed.level_capped_from,
        "classification_policy": (
            "rule 1 -> INSUFFICIENT_HISTORY (level NONE) when the own-history "
            "baseline is not evaluable and the peer band is below HIGH; "
            "rule 11 -> PEER_ANOMALY at the peer band when peer >= HIGH."),
        "rule_number": rule_number,
        "recomputed_type": recomputed.outlier_type,
        "recomputed_level": recomputed.outlier_level,
        "verified": verified,
        "note": ("Stored layer scores and the current history reproduce the "
                 "stored classification."
                 if verified else
                 "Re-running the rule table over the stored scores with the "
                 "CURRENT history gives a different result — the history "
                 "changed since this row was written; recalculate this month."),
    }

    return {
        "kind": "layered_outlier",
        "data_epoch": _data_epoch(),
        "hospital_id": hospital_id,
        "hospital": hosp.name if hosp else str(hospital_id),
        "month": month,
        "what": what,
        "where": {
            "hospital_id": hospital_id,
            "hospital": hosp.name if hosp else str(hospital_id),
            "month": month,
            "analysis_code": analysis_code,
            "indicator_name": spec.name,
            "indicator_type": spec.indicator_type,
            "outlier_type": row.outlier_type,
        },
        "why": why,
        "how": {
            "formula": formula,
            "formula_readable": formula_readable,
            "thresholds": {
                "peer_z_threshold": _zscore_threshold(db),
                "minimum_history_period": spec.minimum_history_period,
                "minimum_denominator": spec.minimum_denominator,
                "outlier_method": spec.outlier_method,
                "rule2_min_change_percent": RULE2_MIN_CHANGE_PERCENT,
            },
            "inputs": inputs,
        },
        "reproduce": reproduce,
        "cross_check": cross_check,
        # What was stored when this row was written (NULL on legacy rows): which
        # layers had no dispersion and the band their scores alone implied.
        "classification_provenance": row.classification_provenance,
        "classification": row.outlier_type,
        # ``outlier_level`` stays the STORED band; ``displayed_outlier_level``
        # is the band every screen renders (and the one the headline quotes).
        "outlier_level": row.outlier_level,
        "displayed_outlier_level": displayed_level,
        "investigation_required": bool(row.investigation_required),
        "investigation_route": row.investigation_route,
        "rule_number": rule_number,
        "layers": layers,
        "series": series,
        "series_unit": series_unit,
        "chain": [
            {"step": "Source Data",
             "detail": f"Uploaded indicator values for {month}",
             "endpoint": f"/audit/data-auditor/{hospital_id}?month={month}"},
            {"step": "Layer computation",
             "detail": ("raw → rate/volume → historical → peer "
                        f"(recorded method: {row.outlier_method})"),
             "endpoint": f"/audit/benchmark/{hospital_id}?month={month}"},
            {"step": "Classification",
             "detail": (f"Rule {rule_number if rule_number is not None else '—'}: "
                        f"{row.outlier_type} at {row.outlier_level}, route "
                        f"{row.investigation_route}"),
             "endpoint": f"/analysis/outliers?hospital_id={hospital_id}&month={month}"},
            {"step": "Finding",
             "detail": f"layered_outlier_results row #{row.id}",
             "endpoint": f"/analysis/layered?hospital={hospital_id}&month={month}"},
        ],
    }


# ─────────────── US-11 unified audit trail (on-demand) ────────────────
_TRAIL_STAGE_META = {
    "raw_data": ("\u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0623\u0635\u0644\u064a\u0629", "Raw Data"),
    "validation": ("\u0627\u0644\u062a\u062d\u0642\u0642", "Validation"),
    "issue": ("\u0627\u0644\u0645\u0634\u0643\u0644\u0629", "Issue"),
    "evidence": ("\u0627\u0644\u0623\u062f\u0644\u0629", "Evidence"),
    "root_cause": ("\u0627\u0644\u0633\u0628\u0628 \u0627\u0644\u062c\u0630\u0631\u064a", "Root Cause"),
    "impact": ("\u0627\u0644\u0623\u062b\u0631", "Impact"),
    "recommendation": ("\u0627\u0644\u062a\u0648\u0635\u064a\u0629", "Recommendation"),
    "action": ("\u0627\u0644\u0625\u062c\u0631\u0627\u0621", "Action"),
    # aggregate data-origin stages
    "calculation": ("\u0627\u0644\u062d\u0633\u0627\u0628 / \u0627\u0644\u0645\u0643\u0648\u0651\u0646\u0627\u062a", "Calculation / Constituents"),
    "finding": ("\u0627\u0644\u0646\u062a\u064a\u062c\u0629", "Finding"),
}
_PER_ISSUE_KINDS = {
    "quality_score", "anomaly", "layered_outlier", "rule",
    "comparison_row", "trend_row", "time_period_point", "heatmap_cell",
}
_CHAIN_STEP_NAMES = {
    "raw_data": "Source Data",       # legacy name kept for backward compatibility
    "validation": "Validation",
    "issue": "Issue",
    "evidence": "Evidence",
    "root_cause": "Root Cause",
    "impact": "Impact",
    "recommendation": "Recommendation",
    "action": "Action",
    # aggregate data-origin stages
    "calculation": "Calculation",
    "finding": "Finding",
}
_RC_NA_REASON = {
    "ar": "\u0644\u0627 \u062a\u0648\u062c\u062f \u0628\u064a\u0627\u0646\u0627\u062a \u0633\u0628\u0628 \u062c\u0630\u0631 \u0645\u062d\u062f\u062f\u0629 \u0644\u0647\u0630\u0647 \u0627\u0644\u0645\u0634\u0643\u0644\u0629",
    "en": "No specific root cause data for this issue",
}


def _bilingual(ar, en):
    return ar if ar == en else {"ar": ar, "en": en}


def _na_stage(key, order, ar_label, en_label, ar_reason, en_reason):
    return {
        "key": key,
        "order": order,
        "ar": ar_label,
        "en": en_label,
        "status": "na",
        "detail": None,
        "na_reason": {"ar": ar_reason, "en": en_reason},
    }


def _deep_link(endpoint=None, query=None, hash_=None):
    if not endpoint and not hash_:
        return None
    link = {}
    if endpoint:
        link["endpoint"] = endpoint
    if query:
        link["query"] = {k: v for k, v in query.items() if v is not None}
    if hash_:
        link["hash"] = hash_
    return link


def _evidence_item(label_ar, label_en, value, unit=None):
    item = {"label_ar": label_ar, "label_en": label_en, "value": value}
    if unit is not None:
        item["unit"] = unit
    return item


def _stage(key, order, detail_ar, detail_en, status="has_content",
           na_reason=None, evidence_items=None, deep_link=None, source_engine=None):
    ar_label, en_label = _TRAIL_STAGE_META.get(key, (key, key))
    st = {
        "key": key,
        "order": order,
        "ar": ar_label,
        "en": en_label,
        "status": status,
        "detail": _bilingual(detail_ar, detail_en),
    }
    if na_reason is not None:
        st["na_reason"] = na_reason
    if evidence_items:
        st["evidence_items"] = evidence_items
    if deep_link:
        st["deep_link"] = deep_link
    if source_engine:
        st["source_engine"] = source_engine
    return st


def _link_url(link):
    if not link:
        return None
    if link.get("hash"):
        return link["hash"]
    endpoint = link.get("endpoint")
    if not endpoint:
        return None
    query = link.get("query") or {}
    return endpoint + ("?" + urlencode(query) if query else "")


def _chain_from_trail(trail):
    chain = []
    for st in trail:
        detail = st.get("detail")
        detail_str = detail.get("en", "") if isinstance(detail, dict) else (detail or "")
        chain.append({
            "step": _CHAIN_STEP_NAMES.get(st.get("key"), st.get("en", st.get("key"))),
            "detail": detail_str,
            "key": st.get("key"),
            "status": st.get("status"),
            "endpoint": _link_url(st.get("deep_link")),
        })
    return chain


def _load_root_cause_cached(db, hid, month, rc_cache):
    """Load (and cache per (hid, month)) the root-cause report — on demand."""
    if hid is None or not month:
        return None
    key = (hid, month)
    if key in rc_cache:
        return rc_cache[key]
    report = None
    try:
        from app.engine.pipeline import run_full_analysis
        from app.engine.root_cause import generate_root_cause_analysis

        qs = (
            db.query(QualityScore)
            .filter(QualityScore.hospital_id == hid, QualityScore.month == month)
            .first()
        )
        cs = (
            db.query(ConfidenceScore)
            .filter(ConfidenceScore.hospital_id == hid, ConfidenceScore.month == month)
            .first()
        )
        quality_data = None
        confidence_data = None
        if qs:
            quality_data = {
                "score": qs.score,
                "rule_compliance": qs.rule_compliance,
                "completeness": qs.completeness,
                "consistency": qs.consistency,
                "outlier_penalty": qs.outlier_penalty,
                "issues": json.loads(qs.issues) if qs.issues else [],
            }
        if cs:
            confidence_data = {
                "overall_confidence": cs.overall_confidence,
                "level": cs.level,
                "indicators": json.loads(cs.indicators_data) if cs.indicators_data else [],
                "by_level": {
                    "HIGH": cs.high_count, "MEDIUM": cs.medium_count,
                    "LOW": cs.low_count, "CRITICAL": cs.critical_count,
                },
            }
        if not quality_data or not confidence_data:
            full = run_full_analysis(db, hid, month)
            quality_data = quality_data or {
                "score": full.get("data_quality_score", 0),
                "rule_compliance": full.get("rule_compliance", 0),
                "completeness": full.get("completeness", 0),
                "consistency": full.get("consistency", 0),
                "outlier_penalty": full.get("outlier_penalty", 0),
                "issues": full.get("issues", []),
            }
            confidence_data = confidence_data or full.get("confidence", {})
        report = generate_root_cause_analysis(
            db, hid, month,
            quality_data=quality_data,
            confidence_data=confidence_data,
            include_history=True,
            compare_peers=False,
            months_back=6,
            peer_mode="auto",
        )
    except Exception as exc:  # graceful: later stages degrade to N/A
        logger.warning("trail: root cause failed for %s/%s: %s", hid, month, exc)
        report = None
    rc_cache[key] = report
    return report


def _narrow_root_cause(rc_report, kind, rate_name=None, rule_code=None,
                       indicator_code=None, component=None):
    """Pick the causal chain / rule failure / quality driver best matching an issue.

    Only narrows when an explicit match key exists; otherwise falls back to the
    hospital-month summary and flags ``general`` (never invents a link).
    """
    result = {"chain": None, "rule_fail": None, "qdriver": None, "paction": None, "general": True}
    if rc_report is None:
        return result

    if rule_code:
        for fail in rc_report.top_rule_failures:
            if fail.rule_code == rule_code:
                result["rule_fail"] = fail
                break
        for chain in rc_report.causal_chains:
            factors = set(chain.affected_factors or []) | set(chain.chain_path or [])
            if rule_code in factors:
                result["chain"] = chain
                result["general"] = False
                break

    if result["chain"] is None and component:
        for driver in rc_report.quality_drivers:
            if driver.component == component:
                result["qdriver"] = driver
                result["general"] = False
                break

    token = rate_name or indicator_code
    if result["chain"] is None and result["qdriver"] is None and token:
        base = token.replace(" (trend)", "")
        for pattern in rc_report.anomaly_patterns:
            if (pattern.rate_name or "").replace(" (trend)", "") == base:
                result["general"] = False
                break
        for driver in rc_report.quality_drivers:
            if driver.component == token:
                result["qdriver"] = driver
                result["general"] = False
                break
        for fail in rc_report.top_rule_failures:
            if token.lower() in (fail.rule_description or "").lower():
                result["rule_fail"] = fail
                result["general"] = False
                break

    if result["chain"] is None and rc_report.causal_chains:
        result["chain"] = rc_report.causal_chains[0]  # general hospital-month context

    source_pref = {"rule": "rule", "quality_score": "quality",
                   "time_period_point": "quality", "anomaly": "anomaly",
                   "layered_outlier": "anomaly"}.get(kind)
    details = rc_report.priority_action_details or []
    result["paction"] = (
        next((p for p in details if p.source == source_pref), None)
        if source_pref else (details[0] if details else None)
    )
    if result["paction"] is None and details:
        result["paction"] = details[0]
    return result


def _impact_from_narrowed(narrowed):
    chain = narrowed.get("chain")
    if chain is not None and getattr(chain, "impact_if_fixed", 0):
        return {"quantified": True, "value": float(chain.impact_if_fixed),
                "unit": "quality points",
                "severity": getattr(chain, "implementation_priority", "") or ""}
    driver = narrowed.get("qdriver")
    if driver is not None and getattr(driver, "impact", 0):
        return {"quantified": True, "value": float(driver.impact),
                "unit": "quality points", "severity": getattr(driver, "status", "") or ""}
    fail = narrowed.get("rule_fail")
    return {"quantified": False, "value": None, "unit": None,
            "severity": getattr(fail, "severity", "") if fail is not None else ""}


def _recommendation_from_narrowed(narrowed, kind):
    chain = narrowed.get("chain")
    if chain is not None and getattr(chain, "recommended_action", ""):
        return {"ar": getattr(chain, "root_cause_arabic", "") or "",
                "en": chain.recommended_action, "source": "causal_chain"}
    fail = narrowed.get("rule_fail")
    if fail is not None and getattr(fail, "recommendation", ""):
        return {"ar": getattr(fail, "primary_cause_ar", "") or "",
                "en": fail.recommendation, "source": "rule_failure"}
    driver = narrowed.get("qdriver")
    if driver is not None and getattr(driver, "recommendation", ""):
        return {"ar": "", "en": driver.recommendation, "source": "quality_driver"}
    return {"ar": "", "en": "", "source": "derived"}


def _action_from_narrowed(narrowed, kind):
    paction = narrowed.get("paction")
    if paction is not None:
        return {"ar": "", "en": paction.action, "effort": paction.effort,
                "roi": paction.roi, "impact": paction.impact, "source": paction.source}
    rec = _recommendation_from_narrowed(narrowed, kind)
    en = ("Implement: " + rec["en"]) if rec["en"] else ""
    return {"ar": rec["ar"], "en": en, "effort": None, "roi": None,
            "impact": None, "source": "derived"}


def _raw_data_stage(db, hid, month, kind, payload):
    where = payload.get("where") or {}
    sources = where.get("source_files") or []
    data_audit = None
    if hid and month and db is not None:
        try:
            from app.engine.audit.data_auditor import get_data_audit
            data_audit = get_data_audit(db, hid, month)
        except Exception:
            data_audit = None
    n = where.get("raw_value_count")
    if n is None and data_audit:
        completeness = data_audit.get("completeness") or {}
        n = (completeness.get("present") or 0) + (completeness.get("covered") or 0)
    n = n if n is not None else 0
    suffix_en = f" from {len(sources)} file(s)" if sources else ""
    suffix_ar = f" \u0645\u0646 {len(sources)} \u0645\u0644\u0641" if sources else ""
    detail_en = f"{n} indicator values{suffix_en}"
    detail_ar = f"{n} \u0642\u064a\u0645\u0629 \u0645\u0624\u0634\u0631{suffix_ar}"
    ind_name = where.get("indicator_name")
    if ind_name:
        detail_en = f"{detail_en} \u2014 {ind_name}"
        detail_ar = f"{detail_ar} \u2014 {ind_name}"
    evidence = []
    if data_audit:
        completeness = data_audit.get("completeness") or {}
        evidence = [
            _evidence_item("\u0627\u0644\u062d\u0627\u0636\u0631", "Present", completeness.get("present")),
            _evidence_item("\u0627\u0644\u0645\u063a\u0637\u0649", "Covered", completeness.get("covered")),
            _evidence_item("\u0627\u062e\u062a\u064a\u0627\u0631\u064a", "Optional", completeness.get("optional")),
            _evidence_item("\u0627\u0644\u0645\u0641\u0642\u0648\u062f", "Missing", completeness.get("missing")),
        ]
    link = _deep_link(endpoint=f"/audit/data-auditor/{hid}", query={"month": month}) if hid and month else None
    return _stage("raw_data", 1, detail_ar, detail_en,
                  evidence_items=evidence or None, deep_link=link, source_engine="data_auditor")


def _validation_stage(db, hid, month, kind, payload):
    failed = payload.get("failed_rules") or []
    problems = payload.get("data_problems") or []
    codes = [str(r.get("rule_code")) for r in failed if r.get("rule_code")][:5]
    codes_str = ", ".join(codes)
    if failed:
        detail_en = f"Business rules evaluated on the raw values \u2014 {len(failed)} failed ({codes_str})"
        detail_ar = f"\u062a\u0645 \u062a\u0642\u064a\u064a\u0645 \u0642\u0648\u0627\u0639\u062f \u0627\u0644\u0639\u0645\u0644 \u2014 \u0641\u0634\u0644 {len(failed)} ({codes_str})"
    elif problems:
        detail_en = f"Business rules evaluated \u2014 {len(problems)} raw-data problem(s) detected"
        detail_ar = f"\u062a\u0645 \u062a\u0642\u064a\u064a\u0645 \u0627\u0644\u0642\u0648\u0627\u0639\u062f \u2014 {len(problems)} \u0645\u0634\u0643\u0644\u0629 \u0641\u064a \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a"
    else:
        detail_en = "Business rules evaluated on the raw values \u2014 none failed"
        detail_ar = "\u062a\u0645 \u062a\u0642\u064a\u064a\u0645 \u0642\u0648\u0627\u0639\u062f \u0627\u0644\u0639\u0645\u0644 \u2014 \u0644\u0645 \u062a\u0641\u0634\u0644 \u0623\u064a \u0642\u0627\u0639\u062f\u0629"
    evidence = []
    if failed:
        evidence.append(_evidence_item("\u0642\u0648\u0627\u0639\u062f \u0641\u0627\u0634\u0644\u0629", "Failed rules", len(failed)))
        for r in failed[:5]:
            evidence.append(_evidence_item("\u0642\u0627\u0639\u062f\u0629", "Rule", r.get("rule_code"), unit=r.get("severity")))
    link = _deep_link(endpoint=f"/audit/data-auditor/{hid}", query={"month": month}) if hid and month else None
    return _stage("validation", 2, detail_ar, detail_en,
                  evidence_items=evidence or None, deep_link=link, source_engine="data_auditor")


def _issue_stage(kind, payload):
    detail_en = payload.get("what") or payload.get("description") or "Detected issue"
    return _stage("issue", 3, detail_en, detail_en, source_engine=payload.get("kind", kind))


def _evidence_stage(db, hid, month, kind, payload):
    repro = payload.get("reproduce") or {}
    evidence = []
    for key, ar, en in (
        ("expected", "\u0627\u0644\u0645\u062a\u0648\u0642\u0639", "Expected"),
        ("stored", "\u0627\u0644\u0645\u062e\u0632\u0651\u0646", "Stored"),
        ("expected_rate", "\u0627\u0644\u0645\u0639\u062f\u0644 \u0627\u0644\u0645\u062a\u0648\u0642\u0639", "Expected rate"),
        ("expected_z", "z \u0627\u0644\u0645\u062a\u0648\u0642\u0639", "Expected z"),
    ):
        if repro.get(key) is not None:
            evidence.append(_evidence_item(ar, en, repro.get(key)))
    if "verified" in repro:
        evidence.append(_evidence_item("\u0645\u064f\u062a\u062d\u0642\u0651\u0642", "Verified", bool(repro.get("verified"))))
    if kind == "layered_outlier":
        link = _deep_link(endpoint="/analysis/layered")
    elif hid and month:
        link = _deep_link(endpoint=f"/audit/calculation-steps/{hid}", query={"month": month})
    else:
        link = None
    return _stage("evidence", 4,
                  "\u0625\u0639\u0627\u062f\u0629 \u0627\u0644\u0625\u0646\u062a\u0627\u062c \u0648\u0627\u0644\u0645\u062f\u062e\u0644\u0627\u062a \u0645\u0646 \u0627\u0644\u062d\u0633\u0627\u0628",
                  "Reproduction and inputs from the calculation",
                  evidence_items=evidence or None, deep_link=link, source_engine="calculation_steps")


def _root_cause_stages(db, hid, month, kind, rate_name, rule_code,
                       indicator_code, component, payload, rc_cache):
    report = _load_root_cause_cached(db, hid, month, rc_cache)
    if report is None:
        na = _RC_NA_REASON
        return [
            _na_stage("root_cause", 5, *_TRAIL_STAGE_META["root_cause"], na["ar"], na["en"]),
            _na_stage("impact", 6, *_TRAIL_STAGE_META["impact"], na["ar"], na["en"]),
            _na_stage("recommendation", 7, *_TRAIL_STAGE_META["recommendation"], na["ar"], na["en"]),
            _na_stage("action", 8, *_TRAIL_STAGE_META["action"], na["ar"], na["en"]),
        ]

    narrowed = _narrow_root_cause(report, kind, rate_name=rate_name,
                                  rule_code=rule_code, indicator_code=indicator_code,
                                  component=component)
    general_note_en = "general to this hospital/month"
    general_note_ar = "\u0639\u0627\u0645 \u0644\u0647\u0630\u0627 \u0627\u0644\u0645\u0633\u062a\u0634\u0641\u0649/\u0627\u0644\u0634\u0647\u0631"
    rc_link = _deep_link(endpoint=f"/root-cause/{hid}",
                         query={"month": month, "include_history": "true", "compare_peers": "false"})

    chain = narrowed["chain"]
    fail = narrowed["rule_fail"]
    driver = narrowed["qdriver"]
    if chain is not None:
        rc_en = chain.root_cause or ""
        rc_ar = chain.root_cause_arabic or rc_en
        if narrowed["general"]:
            rc_en = f"{rc_en} ({general_note_en})"
            rc_ar = f"{rc_ar} ({general_note_ar})"
        rc_evidence = [_evidence_item("\u0627\u0644\u062b\u0642\u0629", "Confidence", chain.confidence)]
        if chain.chain_path:
            rc_evidence.append(_evidence_item(
                "\u0645\u0633\u0627\u0631 \u0627\u0644\u0633\u0644\u0633\u0644\u0629", "Chain path",
                chain.chain_path_arabic or " \u2192 ".join(chain.chain_path),
            ))
        if chain.affected_factors:
            rc_evidence.append(_evidence_item(
                "\u0627\u0644\u0639\u0648\u0627\u0645\u0644 \u0627\u0644\u0645\u062a\u0623\u062b\u0631\u0629",
                "Affected factors", ", ".join(chain.affected_factors),
            ))
        if chain.implementation_priority:
            rc_evidence.append(_evidence_item(
                "\u0627\u0644\u0623\u0648\u0644\u0648\u064a\u0629", "Priority", chain.implementation_priority,
            ))
        root_stage = _stage("root_cause", 5, rc_ar, rc_en,
                            evidence_items=rc_evidence, deep_link=rc_link,
                            source_engine="root_cause")
    elif fail is not None:
        rc_en = f"{fail.rule_code}: {fail.primary_cause} ({general_note_en})"
        rc_ar = fail.primary_cause_ar or fail.primary_cause or fail.rule_code
        rc_ar = f"{rc_ar} ({general_note_ar})"
        root_stage = _stage("root_cause", 5, rc_ar, rc_en,
                            evidence_items=[_evidence_item(
                                "\u0645\u0639\u062f\u0644 \u0627\u0644\u0641\u0634\u0644", "Failure rate",
                                fail.failure_rate)],
                            deep_link=rc_link, source_engine="root_cause")
    elif driver is not None:
        rc_en = f"{driver.component} driver ({driver.status}) ({general_note_en})"
        root_stage = _stage("root_cause", 5, rc_en, rc_en,
                            evidence_items=[_evidence_item(
                                "\u0627\u0644\u0642\u064a\u0645\u0629", "Value", driver.value)],
                            deep_link=rc_link, source_engine="root_cause")
    else:
        na = _RC_NA_REASON
        root_stage = _na_stage("root_cause", 5, *_TRAIL_STAGE_META["root_cause"], na["ar"], na["en"])

    impact = _impact_from_narrowed(narrowed)
    if impact["quantified"]:
        impact_en = f"{impact['value']} {impact['unit']} recoverable (severity {impact['severity'] or 'n/a'})"
        impact_ar = f"{impact['value']} \u0646\u0642\u0637\u0629 \u062c\u0648\u062f\u0629 \u0642\u0627\u0628\u0644\u0629 \u0644\u0644\u0627\u0633\u062a\u0631\u062c\u0627\u0639"
        impact_evidence = [
            _evidence_item("\u0627\u0644\u0623\u062b\u0631", "Impact", impact["value"], unit=impact["unit"]),
            _evidence_item("\u0627\u0644\u062e\u0637\u0648\u0631\u0629", "Severity", impact["severity"]),
        ]
    else:
        sev = impact["severity"] or "n/a"
        impact_en = f"Not quantified \u2014 severity {sev}"
        impact_ar = f"\u063a\u064a\u0631 \u0645\u0642\u0627\u0633 \u2014 \u0627\u0644\u062e\u0637\u0648\u0631\u0629 {sev}"
        impact_evidence = [_evidence_item("\u0627\u0644\u062e\u0637\u0648\u0631\u0629", "Severity", sev)]
    impact_stage = _stage("impact", 6, impact_ar, impact_en,
                          evidence_items=impact_evidence, deep_link=rc_link, source_engine="root_cause")

    rec = _recommendation_from_narrowed(narrowed, kind)
    if rec["en"]:
        rec_stage = _stage("recommendation", 7, rec["ar"] or rec["en"], rec["en"],
                           evidence_items=[_evidence_item(
                               "\u0627\u0644\u0645\u0635\u062f\u0631", "Source", rec["source"])],
                           deep_link=rc_link, source_engine="root_cause")
    else:
        rec_stage = _na_stage("recommendation", 7, *_TRAIL_STAGE_META["recommendation"],
                              _RC_NA_REASON["ar"], _RC_NA_REASON["en"])

    act = _action_from_narrowed(narrowed, kind)
    if act["en"]:
        act_evidence = []
        if act["effort"] is not None:
            act_evidence.append(_evidence_item("\u0627\u0644\u062c\u0647\u062f", "Effort", act["effort"]))
        if act["roi"] is not None:
            act_evidence.append(_evidence_item("\u0627\u0644\u0639\u0627\u0626\u062f", "ROI", act["roi"]))
        if act["impact"] is not None:
            act_evidence.append(_evidence_item("\u0627\u0644\u0623\u062b\u0631", "Impact", act["impact"]))
        act_evidence.append(_evidence_item("\u0627\u0644\u0645\u0635\u062f\u0631", "Source", act["source"]))
        act_stage = _stage("action", 8, act["ar"] or act["en"], act["en"],
                           evidence_items=act_evidence, deep_link=rc_link, source_engine="root_cause")
    else:
        act_stage = _na_stage("action", 8, *_TRAIL_STAGE_META["action"],
                              _RC_NA_REASON["ar"], _RC_NA_REASON["en"])

    return [root_stage, impact_stage, rec_stage, act_stage]


def _build_issue_trail(db, hid, month, kind, rate_name, rule_code,
                       indicator_code, component, payload, rc_cache):
    stages = [
        _raw_data_stage(db, hid, month, kind, payload),
        _validation_stage(db, hid, month, kind, payload),
        _issue_stage(kind, payload),
        _evidence_stage(db, hid, month, kind, payload),
    ]
    stages.extend(_root_cause_stages(db, hid, month, kind, rate_name,
                                     rule_code, indicator_code, component,
                                     payload, rc_cache))
    return stages


def _build_aggregate_trail(kind, payload):
    where = payload.get("where") or {}
    sources = where.get("source_files") or []
    n = where.get("raw_value_count")
    hospitals = payload.get("hospitals") or []
    if n is None and hospitals:
        n = len(hospitals)
    if n is not None:
        raw_en = f"{n} constituent values" + (f" from {len(sources)} file(s)" if sources else "")
        raw_ar = f"{n} \u0642\u064a\u0645\u0629 \u0645\u0643\u0648\u0651\u0646\u0629" + (f" \u0645\u0646 {len(sources)} \u0645\u0644\u0641" if sources else "")
    else:
        raw_en = "Constituent data across the aggregate"
        raw_ar = "\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0645\u0643\u0648\u0651\u0646\u0627\u062a \u0644\u0644\u062a\u062c\u0645\u064a\u0639"
    link = None
    for node in (payload.get("chain") or []):
        if node.get("endpoint"):
            link = _deep_link(endpoint=node["endpoint"])
            break
    what = payload.get("what") or "Aggregate finding"
    return [
        _stage("raw_data", 1, raw_ar, raw_en, deep_link=link, source_engine="data_auditor"),
        _stage("validation", 2,
               "\u062a\u062f\u0642\u064a\u0642 \u0642\u0648\u0627\u0639\u062f \u0627\u0644\u0639\u0645\u0644 \u0639\u0644\u0649 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0645\u0643\u0648\u0651\u0646\u0629",
               "Business rules evaluated on the constituent data",
               deep_link=link, source_engine="data_auditor"),
        _stage("calculation", 3,
               "\u062d\u0633\u0627\u0628 \u0627\u0644\u062a\u062c\u0645\u064a\u0639 (\u0645\u062a\u0648\u0633\u0637/\u0646\u0637\u0627\u0642/\u0639\u062f\u062f) \u0639\u0628\u0631 \u0627\u0644\u0645\u0643\u0648\u0651\u0646\u0627\u062a",
               "Aggregate computed across constituents (average / range / count)",
               deep_link=link, source_engine="calculation_steps"),
        _stage("finding", 4, what, what, source_engine=payload.get("kind", kind)),
    ]


def _dispatch_explanation(
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
    if kind == "layered_outlier":
        # The analysis unit rides on indicator_code for this kind — no new
        # query param (spec §8.4: extend the dispatcher, not the API).
        if not indicator_code:
            return {"error": "kind=layered_outlier requires indicator_code (the row's analysis_code)"}
        return explain_layered_outlier(db, hospital_id, month, indicator_code)
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


def _build_trail(db, hid, month, kind, rate_name, rule_code,
                 indicator_code, component, payload, rc_cache):
    if kind in _PER_ISSUE_KINDS:
        return _build_issue_trail(db, hid, month, kind, rate_name, rule_code,
                                  indicator_code, component, payload, rc_cache)
    return _build_aggregate_trail(kind, payload)


def build_explanation(
    db: Session,
    kind: str,
    hospital_id: Optional[object],
    month: str,
    rate_name: Optional[str] = None,
    indicator_code: Optional[str] = None,
    rule_code: Optional[str] = None,
    component: Optional[str] = None,
    hospital_name: Optional[str] = None,
) -> dict:
    """US-11 wrapper: dispatch the base explanation, then attach the unified
    ``trail`` and extend ``chain`` to 8 stages for per-issue kinds."""
    payload = _dispatch_explanation(
        db, kind, hospital_id, month,
        rate_name=rate_name, indicator_code=indicator_code, rule_code=rule_code,
        component=component, hospital_name=hospital_name,
    )
    if not isinstance(payload, dict) or "error" in payload:
        return payload

    emitted_kind = payload.get("kind", kind)
    hid = payload.get("hospital_id")
    if not isinstance(hid, int):
        hid = (payload.get("where") or {}).get("hospital_id")
    if not isinstance(hid, int):
        hid = hospital_id if isinstance(hospital_id, int) else None
    resolved_month = payload.get("month", month)

    rc_cache = {}
    trail = _build_trail(db, hid, resolved_month, emitted_kind, rate_name,
                         rule_code, indicator_code, component, payload, rc_cache)
    payload["trail"] = trail
    payload["chain"] = _chain_from_trail(trail)
    return payload
