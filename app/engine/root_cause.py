from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
import logging

logger = logging.getLogger(__name__)


try:
    from app.plugins.ai import generate_root_cause_ai as _generate_rc_ai
    _HAVE_AI = True
except ImportError:
    _HAVE_AI = False
    logger.info("ai_recommendations plugin not available; AI for root cause disabled")


@dataclass
class RuleFailurePattern:
    rule_code: str
    rule_description: str
    severity: str
    failure_count: int
    total_runs: int
    failure_rate: float
    primary_cause: str
    recommendation: str


@dataclass
class QualityDriver:
    component: str
    value: float
    weight: float
    impact: float
    status: str
    recommendation: str


@dataclass
class ConfidenceGap:
    indicator_code: str
    indicator_name: str
    confidence: float
    level: str
    weakest_signal: str
    weakest_score: float
    root_cause: str
    recommendation: str


@dataclass
class AnomalyPattern:
    indicator_code: str
    rate_name: str
    hospital_count: int
    avg_z_score: float
    recurrence_count: int
    pattern_type: str
    description: str


@dataclass
class RootCauseReport:
    hospital: str
    hospital_id: int
    month: str
    overall_quality_score: float
    overall_confidence: float
    critical_issues_count: int
    top_rule_failures: List[RuleFailurePattern]
    quality_drivers: List[QualityDriver]
    confidence_gaps: List[ConfidenceGap]
    anomaly_patterns: List[AnomalyPattern]
    summary: str
    priority_actions: List[str]
    ai_recommendations: List[Dict] = field(default_factory=list)


@dataclass
class MonthDataPoint:
    month: str
    value: float
    quality_score: float
    confidence: float
    rule_failure_rate: float


@dataclass
class PeerComparison:
    peer_group: str
    peer_count: int
    mean_value: float
    std_value: float
    hospital_percentile: float
    hospital_z_score: float
    benchmark_hospital: str
    benchmark_value: float
    gap_to_benchmark: float


@dataclass
class CausalNode:
    factor: str
    factor_type: str
    current_value: float
    trend: str
    trend_slope: float
    peer_comparison: Optional[PeerComparison]
    history: List[MonthDataPoint]
    severity: str


@dataclass
class CausalChain:
    root_cause: str
    root_cause_arabic: str
    confidence: float
    evidence: List[str]
    affected_factors: List[str]
    recommended_action: str
    impact_if_fixed: float
    implementation_priority: str


@dataclass
class HistoricalComparativeReport:
    hospital_id: int
    hospital_name: str
    current_month: str
    causal_tree: List[CausalNode]
    causal_chains: List[CausalChain]
    historical_trends: Dict[str, Dict]
    peer_comparisons: Dict[str, PeerComparison]
    summary_arabic: str
    priority_actions: List[str]


def analyze_rule_failures(
    session: Session,
    hospital_id: int,
    month: str,
) -> List[RuleFailurePattern]:
    result = session.execute(text("""
        SELECT vr.rule_code, vr.rule_description, vr.severity,
               COUNT(*) as failure_count, vr.details
        FROM validation_results vr
        WHERE vr.hospital_id = :hid AND vr.month = :mth AND vr.status = 'FAIL'
        GROUP BY vr.rule_code
        ORDER BY COUNT(*) DESC
    """), {"hid": hospital_id, "mth": month})
    patterns = []
    for row in result:
        rule_code = row[0]
        desc = row[1] or ""
        severity = row[2] or "LOW"
        failure_count = row[3]
        details = row[4] or ""
        total_result = session.execute(text("""
            SELECT COUNT(*) FROM validation_results
            WHERE hospital_id = :hid AND month = :mth AND rule_code = :rc
        """), {"hid": hospital_id, "mth": month, "rc": rule_code})
        total = total_result.scalar() or 1
        failure_rate = round((failure_count / total) * 100, 1)

        primary_cause, recommendation = _diagnose_rule_failure(rule_code, details)
        patterns.append(RuleFailurePattern(
            rule_code=rule_code,
            rule_description=desc[:80],
            severity=severity,
            failure_count=failure_count,
            total_runs=total,
            failure_rate=failure_rate,
            primary_cause=primary_cause,
            recommendation=recommendation,
        ))
    patterns.sort(key=lambda p: (p.severity != "CRITICAL", p.severity != "HIGH", -p.failure_rate))
    return patterns[:10]


def _diagnose_rule_failure(rule_code: str, details: str) -> Tuple[str, str]:
    cause_map = {
        "R001": ("Parent-child sum mismatch: sub-indicators don't add up to total",
                 "Verify all sub-categories are reported. Check if any sub-indicator is missing or miscoded."),
        "R002": ("Parity breakdown doesn't match total deliveries",
                 "Review primigravida/multigravida data entry. Ensure both fields are filled."),
        "R004": ("Facility type breakdown mismatch",
                 "Confirm in-facility vs out-of-facility classification is correct."),
        "R005": ("Risk classification mismatch",
                 "Verify low-risk/high-risk classification criteria are consistently applied."),
        "R041": ("C-section rate exceeds safe threshold",
                 "Review indication for C-sections. Consider audit of unnecessary C-sections."),
        "R042": ("Normal delivery rate too low",
                 "Investigate if NVDs are being under-reported or misclassified as C-sections."),
        "R051": ("Deliveries spiked >2x compared to previous month",
                 "Verify data accuracy. Could indicate duplicate reporting or a real surge (e.g., referral influx)."),
        "R052": ("Deliveries dropped >50% from previous month",
                 "Check if data was fully reported. Could indicate data collection gap."),
        "R054": ("Maternal deaths surged above threshold",
                 "CRITICAL: Immediate investigation required. Review each maternal death case."),
        "R055": ("Neonatal deaths surged above threshold",
                 "CRITICAL: Immediate investigation required. Review neonatal care protocols."),
        "R058": ("Total Deliveries indicator is missing",
                 "Core indicator not reported. Facility may not have submitted complete data."),
        "R059": ("Live Births indicator is missing",
                 "Core indicator not reported. Required for neonatal mortality rate calculation."),
    }
    if rule_code in cause_map:
        return cause_map[rule_code]
    if "exceeds" in details.lower() or ">" in details:
        return ("Value exceeds expected threshold",
                "Review the data value. If accurate, investigate underlying causes.")
    if "missing" in details.lower():
        return ("Required indicator value not reported",
                "Ensure all mandatory indicators are filled before submission.")
    if "negative" in details.lower():
        return ("Negative value reported for count indicator",
                "Negative counts are impossible. Check data entry for sign errors.")
    if "decimal" in details.lower():
        return ("Decimal value reported for count field",
                "Counts must be integers. Check if value was incorrectly entered.")
    return ("Rule validation check failed",
            "Review the specific indicator values and verify against source records.")


def analyze_quality_drivers(
    quality_data: Optional[Dict],
) -> List[QualityDriver]:
    drivers = []
    if not quality_data:
        return drivers
    components = [
        ("Rule Compliance", quality_data.get("rule_compliance", 0), 0.35),
        ("Completeness", quality_data.get("completeness", 0), 0.25),
        ("Consistency", quality_data.get("consistency", 0), 0.25),
        ("Outlier Penalty", (1 - quality_data.get("outlier_penalty", 0)) * 100, 0.15),
    ]
    for name, val, weight in components:
        weighted = val * weight
        max_possible = 100 * weight
        gap = max_possible - weighted
        if val >= 80:
            status = "good"
            rec = f"{name} is satisfactory ({val:.1f}%). Maintain current processes."
        elif val >= 50:
            status = "needs_improvement"
            rec = f"{name} at {val:.1f}% is below target. Review related procedures."
        else:
            status = "critical"
            rec = f"{name} at {val:.1f}% requires urgent attention. Investigate root causes."
        drivers.append(QualityDriver(
            component=name,
            value=round(val, 1),
            weight=weight,
            impact=round(gap, 1),
            status=status,
            recommendation=rec,
        ))
    drivers.sort(key=lambda d: d.impact, reverse=True)
    return drivers


def analyze_confidence_gaps(
    session: Session,
    hospital_id: int,
    month: str,
) -> List[ConfidenceGap]:
    result = session.execute(text("""
        SELECT indicators_data FROM confidence_scores
        WHERE hospital_id = :hid AND month = :mth
    """), {"hid": hospital_id, "mth": month})
    row = result.fetchone()
    if not row or not row[0]:
        return []
    try:
        indicators = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return []
    gaps = []
    for ind in indicators:
        level = ind.get("level", "HIGH")
        if level in ("LOW", "CRITICAL", "MEDIUM"):
            confidence = ind.get("confidence", 0)
            signals = ind.get("signals", [])
            weakest = min(signals, key=lambda s: s.get("score", 1)) if signals else {}
            name = ind.get("indicator_name", ind.get("indicator_code", ""))
            cause, rec = _diagnose_confidence_gap(weakest.get("factor", ""), name, level)
            gaps.append(ConfidenceGap(
                indicator_code=ind.get("indicator_code", ""),
                indicator_name=name,
                confidence=round(confidence, 1),
                level=level,
                weakest_signal=weakest.get("factor", "unknown"),
                weakest_score=round(weakest.get("score", 0), 2),
                root_cause=cause,
                recommendation=rec,
            ))
    gaps.sort(key=lambda g: (g.level != "CRITICAL", g.level != "LOW", g.confidence))
    return gaps[:15]


def _diagnose_confidence_gap(signal_factor: str, name: str, level: str) -> Tuple[str, str]:
    diagnoses = {
        "rule_compliance": (
            f"Indicator '{name}' frequently fails validation rules",
            "Review the specific rule failures for this indicator. Check data entry accuracy."
        ),
        "historical": (
            f"Indicator '{name}' shows high volatility compared to historical trend",
            "Verify recent values. If accurate, investigate what changed in the reporting period."
        ),
        "cross_hospital": (
            f"Indicator '{name}' deviates significantly from peer hospitals",
            "Review if this is a genuine outlier or a reporting error. Compare with similar facilities."
        ),
        "trend": (
            f"Indicator '{name}' has an unstable or concerning trend direction",
            "Analyze the 3-6 month trend. Determine if this is seasonal variation or sustained change."
        ),
        "completeness": (
            f"Indicator '{name}' has missing sub-components or related indicators",
            "Ensure all child indicators and related fields are populated."
        ),
    }
    if signal_factor in diagnoses:
        return diagnoses[signal_factor]
    return (
        f"Multiple factors contributing to low confidence in '{name}'",
        "Review all data sources for this indicator. Consider manual verification against source records."
    )


def analyze_anomaly_patterns(
    session: Session,
    hospital_id: int,
    month: str,
) -> List[AnomalyPattern]:
    result = session.execute(text("""
        SELECT indicator_code, rate_name, COUNT(*) as hosp_count,
               AVG(ABS(z_score)) as avg_z
        FROM anomaly_results
        WHERE hospital_id = :hid AND month = :mth AND is_outlier = 1
        GROUP BY indicator_code
        ORDER BY AVG(ABS(z_score)) DESC
    """), {"hid": hospital_id, "mth": month})
    patterns = []
    for row in result:
        code = row[0] or ""
        rate_name = row[1] or ""
        hosp_count = row[2] or 0
        avg_z = round(float(row[3] or 0), 2)
        prev_result = session.execute(text("""
            SELECT COUNT(*) FROM anomaly_results ar
            JOIN (SELECT DISTINCT month FROM indicator_values
                  WHERE hospital_id = :hid AND month < :mth) prev
            WHERE ar.hospital_id = :hid AND ar.indicator_code = :ic
            AND ar.is_outlier = 1 AND ar.month = prev.month
        """), {"hid": hospital_id, "mth": month, "ic": code})
        recurrence = prev_result.scalar() or 0
        if abs(avg_z) > 3:
            ptype = "severe"
            desc = f"Extreme outlier (|z|={avg_z}) for {rate_name}"
        elif abs(avg_z) > 2.5:
            ptype = "moderate"
            desc = f"Moderate outlier (|z|={avg_z}) for {rate_name}"
        else:
            ptype = "mild"
            desc = f"Mild deviation (|z|={avg_z}) for {rate_name}"
        if recurrence > 0:
            desc += f" - recurring anomaly ({recurrence} previous months)"
        patterns.append(AnomalyPattern(
            indicator_code=code,
            rate_name=rate_name,
            hospital_count=hosp_count,
            avg_z_score=avg_z,
            recurrence_count=recurrence,
            pattern_type=ptype,
            description=desc,
        ))
    patterns.sort(key=lambda p: (p.pattern_type != "severe", -abs(p.avg_z_score)))
    return patterns[:10]


def generate_root_cause_analysis(
    session: Session,
    hospital_id: int,
    month: str,
    quality_data: Optional[Dict] = None,
    confidence_data: Optional[Dict] = None,
) -> RootCauseReport:
    hospital = session.execute(
        text("SELECT name FROM hospitals WHERE id = :hid"),
        {"hid": hospital_id}
    ).fetchone()
    hospital_name = hospital[0] if hospital else f"Hospital {hospital_id}"

    rule_failures = analyze_rule_failures(session, hospital_id, month)
    quality_drivers = analyze_quality_drivers(quality_data)
    confidence_gaps = analyze_confidence_gaps(session, hospital_id, month)
    anomaly_patterns = analyze_anomaly_patterns(session, hospital_id, month)

    overall_quality = quality_data.get("score", 0) if quality_data else 0
    overall_confidence = confidence_data.get("overall_confidence", 0) if confidence_data else 0

    critical_count = len([f for f in rule_failures if f.severity == "CRITICAL"])
    critical_count += len([g for g in confidence_gaps if g.level == "CRITICAL"])

    summary_parts = []
    if rule_failures:
        top_failure = rule_failures[0]
        summary_parts.append(
            f"Primary issue: {top_failure.rule_code} ({top_failure.rule_description[:60]}) "
            f"failing at {top_failure.failure_rate:.0f}% rate. {top_failure.primary_cause[:80]}."
        )
    if quality_drivers and quality_drivers[0].status != "good":
        worst = quality_drivers[0]
        summary_parts.append(
            f"Quality score ({overall_quality:.1f}) is primarily dragged down by "
            f"{worst.component} ({worst.value:.1f}%). {worst.recommendation[:80]}."
        )
    if confidence_gaps:
        worst_gap = confidence_gaps[0]
        summary_parts.append(
            f"Confidence is critically low for {worst_gap.indicator_name} "
            f"({worst_gap.confidence:.1f}%). {worst_gap.root_cause[:80]}."
        )
    if anomaly_patterns:
        severe = [a for a in anomaly_patterns if a.pattern_type == "severe"]
        if severe:
            summary_parts.append(
                f"{len(severe)} severe anomalies detected: {severe[0].description}."
            )
    if not summary_parts:
        summary_parts.append(
            "No critical issues identified. Data quality and confidence are within acceptable ranges."
        )

    summary = " | ".join(summary_parts)

    priority_actions = []
    for f in rule_failures[:3]:
        if f.severity in ("CRITICAL", "HIGH"):
            priority_actions.append(f"[{f.severity}] {f.rule_code}: {f.recommendation[:100]}")
    for g in confidence_gaps[:3]:
        if g.level in ("CRITICAL", "LOW"):
            priority_actions.append(f"[{g.level} Confidence] {g.indicator_name}: {g.recommendation[:100]}")
    for a in anomaly_patterns[:2]:
        if a.pattern_type == "severe":
            priority_actions.append(f"[Anomaly] {a.description[:100]}")
    if quality_drivers:
        worst_q = quality_drivers[0]
        if worst_q.status != "good":
            priority_actions.append(f"[Quality] {worst_q.recommendation[:100]}")

    ai_recommendations = []
    if _HAVE_AI:
        try:
            report_data_for_ai = {
                "hospital": hospital_name,
                "month": month,
                "overall_quality_score": round(overall_quality, 1),
                "overall_confidence": round(overall_confidence, 1),
                "critical_issues_count": critical_count,
                "top_rule_failures": [
                    {"rule_code": f.rule_code, "description": f.rule_description,
                     "severity": f.severity, "failure_rate": f.failure_rate,
                     "primary_cause": f.primary_cause}
                    for f in rule_failures
                ],
                "quality_drivers": [
                    {"component": d.component, "value": d.value,
                     "status": d.status, "impact": d.impact}
                    for d in quality_drivers
                ],
                "confidence_gaps": [
                    {"indicator_name": g.indicator_name, "level": g.level,
                     "confidence": g.confidence, "weakest_signal": g.weakest_signal}
                    for g in confidence_gaps
                ],
                "anomaly_patterns": [
                    {"rate_name": a.rate_name, "avg_z_score": a.avg_z_score,
                     "pattern_type": a.pattern_type, "description": a.description}
                    for a in anomaly_patterns
                ],
            }
            rc_ai_results = _generate_rc_ai(report_data_for_ai, session=session)
            ai_recommendations = [
                {"category": r.category, "priority": r.priority,
                 "title": r.title, "description": r.description,
                 "rationale": r.rationale, "action_items": r.action_items,
                 "affected_indicators": r.indicators_monitored}
                for r in rc_ai_results
            ]
        except Exception as e:
            logger.error(f"Failed to generate AI root cause recommendations: {e}")

    return RootCauseReport(
        hospital=hospital_name,
        hospital_id=hospital_id,
        month=month,
        overall_quality_score=round(overall_quality, 1),
        overall_confidence=round(overall_confidence, 1),
        critical_issues_count=critical_count,
        top_rule_failures=rule_failures,
        quality_drivers=quality_drivers,
        confidence_gaps=confidence_gaps,
        anomaly_patterns=anomaly_patterns,
        summary=summary[:300],
        priority_actions=priority_actions[:8],
        ai_recommendations=ai_recommendations,
    )
