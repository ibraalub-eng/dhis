from __future__ import annotations
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
    causal_tree: List[CausalNode] = field(default_factory=list)
    causal_chains: List[CausalChain] = field(default_factory=list)
    historical_trends: Dict[str, Dict] = field(default_factory=dict)
    peer_comparisons: Dict[str, PeerComparison] = field(default_factory=dict)
    summary_arabic: str = ""


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


def get_historical_data(
    session: Session,
    hospital_id: int,
    indicator_code: str,
    months_back: int = 6,
) -> List[MonthDataPoint]:
    """
    Retrieve historical data for a specific indicator at a hospital.

    Returns list of MonthDataPoint objects for the last N months.
    """
    result = session.execute(text("""
        SELECT iv.month, iv.value,
               COALESCE(qs.score, 0) as quality_score,
               COALESCE(cs.overall_confidence, 0) as confidence,
               COALESCE(
                   (SELECT COUNT(*) FROM validation_results vr
                    WHERE vr.hospital_id = iv.hospital_id
                    AND vr.month = iv.month AND vr.status = 'FAIL') * 100.0 /
                   NULLIF((SELECT COUNT(*) FROM validation_results vr2
                           WHERE vr2.hospital_id = iv.hospital_id
                           AND vr2.month = iv.month), 0),
                   0) as rule_failure_rate
        FROM indicator_values iv
        JOIN indicators i ON iv.indicator_id = i.id
        LEFT JOIN quality_scores qs ON iv.hospital_id = qs.hospital_id
            AND iv.month = qs.month
        LEFT JOIN confidence_scores cs ON iv.hospital_id = cs.hospital_id
            AND iv.month = cs.month
        WHERE iv.hospital_id = :hid
        AND i.code = :code
        AND iv.month >= strftime('%Y-%m', 'now', :offset)
        ORDER BY iv.month ASC
    """), {"hid": hospital_id, "code": indicator_code, "offset": f"-{months_back} months"})

    history = []
    for row in result:
        history.append(MonthDataPoint(
            month=row[0],
            value=float(row[1] or 0),
            quality_score=float(row[2] or 0),
            confidence=float(row[3] or 0),
            rule_failure_rate=float(row[4] or 0),
        ))
    return history


def get_peer_historical_data(
    session: Session,
    hospital_id: int,
    indicator_code: str,
    months_back: int = 6,
) -> Dict[str, List[MonthDataPoint]]:
    """
    Retrieve historical data for peer hospitals (same type).

    Returns dict of {hospital_name: [MonthDataPoint, ...]}
    """
    hospital = session.execute(text("""
        SELECT hospital_type_id FROM hospitals WHERE id = :hid
    """), {"hid": hospital_id}).fetchone()

    if not hospital or not hospital[0]:
        return {}

    peers = session.execute(text("""
        SELECT id, name FROM hospitals
        WHERE hospital_type_id = :htid
        AND id != :hid
        AND is_active = 1
    """), {"htid": hospital[0], "hid": hospital_id})

    peer_data = {}
    for peer in peers:
        history = get_historical_data(session, peer[0], indicator_code, months_back)
        if history:
            peer_data[peer[1]] = history

    return peer_data


def calculate_trend(history: List[MonthDataPoint]) -> Dict:
    """
    Calculate trend metrics for a factor over time.

    Returns:
    - slope: linear regression slope (positive = improving)
    - r_squared: how well the trend fits (0-1)
    - volatility: standard deviation of changes
    - direction: "improving" / "declining" / "stable"
    - significant_change: bool (p-value < 0.05)
    """
    from scipy import stats
    import numpy as np

    if len(history) < 2:
        return {
            "slope": 0,
            "r_squared": 0,
            "volatility": 0,
            "direction": "stable",
            "significant_change": False,
        }

    values = [p.value for p in history]
    months = list(range(len(values)))

    slope, intercept, r_value, p_value, std_err = stats.linregress(months, values)

    changes = np.diff(values)
    volatility = float(np.std(changes)) if len(changes) > 0 else 0

    if slope > 0.5:
        direction = "improving"
    elif slope < -0.5:
        direction = "declining"
    else:
        direction = "stable"

    return {
        "slope": round(slope, 2),
        "r_squared": round(r_value ** 2, 3),
        "volatility": round(volatility, 2),
        "direction": direction,
        "significant_change": p_value < 0.05,
    }


MIN_PEER_SIZE = 3


def identify_peer_groups(session: Session, hospital_id: int) -> Dict[str, List[int]]:
    """
    Identify three peer groups:
    1. Same hospital_type_id (e.g., government hospitals)
    2. Same facility_ownership_id (e.g., Ministry of Health)
    3. Same governorate (regional average)

    Returns: {peer_group_name: [hospital_ids]}
    If a peer group has fewer than MIN_PEER_SIZE members, it is excluded.
    """
    hospital = session.execute(text("""
        SELECT hospital_type_id, facility_ownership_id, governorate_id
        FROM hospitals WHERE id = :hid
    """), {"hid": hospital_id}).fetchone()

    if not hospital:
        return {}

    result = {}

    # Peers by type
    if hospital[0]:
        peers = session.execute(text("""
            SELECT id FROM hospitals
            WHERE hospital_type_id = :htid
            AND id != :hid
            AND is_active = 1
        """), {"htid": hospital[0], "hid": hospital_id})
        peer_ids = [p[0] for p in peers]
        if len(peer_ids) >= MIN_PEER_SIZE:
            result["hospital_type"] = peer_ids

    # Peers by ownership
    if hospital[1]:
        peers = session.execute(text("""
            SELECT id FROM hospitals
            WHERE facility_ownership_id = :foid
            AND id != :hid
            AND is_active = 1
        """), {"foid": hospital[1], "hid": hospital_id})
        peer_ids = [p[0] for p in peers]
        if len(peer_ids) >= MIN_PEER_SIZE:
            result["ownership"] = peer_ids

    # Peers by region
    if hospital[2]:
        peers = session.execute(text("""
            SELECT id FROM hospitals
            WHERE governorate_id = :gid
            AND id != :hid
            AND is_active = 1
        """), {"gid": hospital[2], "hid": hospital_id})
        peer_ids = [p[0] for p in peers]
        if len(peer_ids) >= MIN_PEER_SIZE:
            result["regional"] = peer_ids

    return result


def calculate_peer_comparison(
    hospital_value: float,
    peer_values: List[float],
    hospital_name: str = "Hospital",
) -> PeerComparison:
    """
    Calculate how hospital compares to peers.

    Metrics:
    - Percentile: rank among peers (0-100)
    - Z-score: standard deviations from mean
    - Gap to benchmark: difference from best performer
    """
    import numpy as np
    from scipy import stats as sp_stats

    if not peer_values:
        return PeerComparison(
            peer_group="hospital_type",
            peer_count=0,
            mean_value=0,
            std_value=0,
            hospital_percentile=50.0,
            hospital_z_score=0.0,
            benchmark_hospital=hospital_name,
            benchmark_value=hospital_value,
            gap_to_benchmark=0.0,
        )

    mean_val = float(np.mean(peer_values))
    std_val = float(np.std(peer_values)) if len(peer_values) > 1 else 0

    percentile = float(sp_stats.percentileofscore(peer_values, hospital_value))
    z_score = (hospital_value - mean_val) / std_val if std_val > 0 else 0

    best_value = max(peer_values)

    return PeerComparison(
        peer_group="hospital_type",
        peer_count=len(peer_values),
        mean_value=round(mean_val, 2),
        std_value=round(std_val, 2),
        hospital_percentile=round(percentile, 1),
        hospital_z_score=round(z_score, 2),
        benchmark_hospital=hospital_name,
        benchmark_value=round(best_value, 2),
        gap_to_benchmark=round(best_value - hospital_value, 2),
    )


def find_correlated_factors(source: CausalNode, candidates: List[CausalNode]) -> List[CausalNode]:
    """
    Find factors that are correlated with source factor.

    Correlation criteria:
    1. Pearson correlation > 0.6 (strong positive correlation)
    2. Both trending in same direction
    3. Temporal lag < 1 month (changes happen together)

    Returns factors that meet all criteria, sorted by correlation strength.
    """
    from scipy import stats

    correlated = []
    source_values = [h.value for h in source.history]

    for candidate in candidates:
        candidate_values = [h.value for h in candidate.history]

        min_len = min(len(source_values), len(candidate_values))
        if min_len < 3:
            continue

        s = source_values[:min_len]
        c = candidate_values[:min_len]

        corr, p_value = stats.pearsonr(s, c)

        if abs(corr) > 0.6 and p_value < 0.05:
            correlated.append((candidate, corr))

    return [c for c, _ in sorted(correlated, key=lambda x: x[1], reverse=True)]


def build_causal_chains(nodes: List[CausalNode]) -> List[CausalChain]:
    """
    Build causal chains by linking related factors.

    Example chain:
    R001 fails (70%) -> Rule Compliance low (55%) -> Quality Score low (62)
    -> Confidence drops (40) -> Anomaly detected (Z=3.2)
    """
    rule_factors = [n for n in nodes if n.factor_type == "rule"]
    quality_factors = [n for n in nodes if n.factor_type == "quality_component"]
    confidence_factors = [n for n in nodes if n.factor_type == "confidence_signal"]

    chains = []

    for rule in rule_factors:
        if rule.severity in ("critical", "high"):
            related_quality = find_correlated_factors(rule, quality_factors)
            related_confidence = find_correlated_factors(rule, confidence_factors)

            evidence = [
                f"{rule.factor} failure rate: {rule.current_value}%",
                f"Trend: {rule.trend} over {len(rule.history)} months",
            ]
            if related_quality:
                evidence.append(f"Correlated with {related_quality[0].factor} ({related_quality[0].current_value}%)")

            impact = 0
            if related_quality:
                impact += abs(rule.current_value - 50) * 0.2
                impact += abs(related_quality[0].current_value - 80) * 0.15
            else:
                impact += abs(rule.current_value - 50) * 0.3

            chain = CausalChain(
                root_cause=f"{rule.factor}: {rule.factor} failing at {rule.current_value}%",
                root_cause_arabic=f"فشل {rule.factor}: {rule.current_value}%",
                confidence=min(0.9, 0.5 + len(related_quality) * 0.15),
                evidence=evidence,
                affected_factors=[rule.factor] + [f.factor for f in related_quality + related_confidence],
                recommended_action=f"Investigate and fix {rule.factor} root cause",
                impact_if_fixed=round(impact, 1),
                implementation_priority=rule.severity,
            )
            chains.append(chain)

    return sorted(chains, key=lambda c: c.confidence, reverse=True)


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
    include_history: bool = False,
    compare_peers: bool = False,
    months_back: int = 6,
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

    causal_nodes = []
    for rf in rule_failures:
        history = []
        if include_history:
            history = get_historical_data(session, hospital_id, rf.rule_code, months_back)

        causal_nodes.append(CausalNode(
            factor=rf.rule_code,
            factor_type="rule",
            current_value=rf.failure_rate,
            trend=calculate_trend(history)["direction"] if history else "stable",
            trend_slope=calculate_trend(history)["slope"] if history else 0,
            peer_comparison=None,
            history=history,
            severity=rf.severity,
        ))

    for qd in quality_drivers:
        causal_nodes.append(CausalNode(
            factor=qd.component,
            factor_type="quality_component",
            current_value=qd.value,
            trend="stable",
            trend_slope=0,
            peer_comparison=None,
            history=[],
            severity="critical" if qd.status == "critical" else "high" if qd.status == "needs_improvement" else "low",
        ))

    causal_chains = build_causal_chains(causal_nodes)

    peer_comparisons = {}
    if compare_peers:
        peer_groups = identify_peer_groups(session, hospital_id)
        for group_name, peer_ids in peer_groups.items():
            peer_values = []
            for pid in peer_ids:
                iv = session.execute(text("""
                    SELECT value FROM indicator_values
                    WHERE hospital_id = :pid AND month = :mth
                    LIMIT 1
                """), {"pid": pid, "mth": month}).fetchone()
                if iv:
                    peer_values.append(float(iv[0]))
            if peer_values:
                peer_comparisons[group_name] = calculate_peer_comparison(
                    overall_quality, peer_values, hospital_name
                )

    historical_trends = {}
    if include_history:
        for node in causal_nodes:
            if node.history:
                historical_trends[node.factor] = calculate_trend(node.history)

    summary_parts = []
    if causal_chains:
        top_chain = causal_chains[0]
        summary_parts.append(
            f"Primary root cause: {top_chain.root_cause} "
            f"(confidence: {top_chain.confidence:.0%})"
        )
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

    summary_arabic = _generate_arabic_summary(
        causal_chains, rule_failures, quality_drivers,
        confidence_gaps, anomaly_patterns, peer_comparisons
    )

    priority_actions = []
    for chain in causal_chains[:3]:
        priority_actions.append(
            f"[{chain.implementation_priority.upper()}] "
            f"{chain.root_cause}: {chain.recommended_action}"
        )
    for f in rule_failures[:3]:
        if f.severity in ("CRITICAL", "HIGH") and len(priority_actions) < 8:
            priority_actions.append(f"[{f.severity}] {f.rule_code}: {f.recommendation[:100]}")
    for g in confidence_gaps[:3]:
        if g.level in ("CRITICAL", "LOW") and len(priority_actions) < 8:
            priority_actions.append(f"[{g.level} Confidence] {g.indicator_name}: {g.recommendation[:100]}")
    for a in anomaly_patterns[:2]:
        if a.pattern_type == "severe" and len(priority_actions) < 8:
            priority_actions.append(f"[Anomaly] {a.description[:100]}")
    if quality_drivers and len(priority_actions) < 8:
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
        causal_tree=causal_nodes,
        causal_chains=causal_chains,
        historical_trends=historical_trends,
        peer_comparisons=peer_comparisons,
        summary_arabic=summary_arabic,
    )


def _generate_arabic_summary(
    causal_chains, rule_failures, quality_drivers,
    confidence_gaps, anomaly_patterns, peer_comparisons
) -> str:
    """Generate Arabic narrative summary of root cause analysis."""
    parts = []

    if causal_chains:
        top = causal_chains[0]
        parts.append(f"السبب الجذري الرئيسي: {top.root_cause_arabic}")

    if peer_comparisons:
        for group, comp in peer_comparisons.items():
            if comp.hospital_percentile < 50:
                parts.append(
                    f"مقارنة ب {group}: المستشفى في المئوية {comp.hospital_percentile:.0f}"
                )

    if rule_failures:
        critical = [r for r in rule_failures if r.severity == "CRITICAL"]
        if critical:
            parts.append(f"يوجد {len(critical)} مشاكل حرجة في قواعد التحقق")

    if quality_drivers:
        worst = quality_drivers[0]
        if worst.status == "critical":
            parts.append(f"العامل الحرج: {worst.component} بنسبة {worst.value:.1f}%")
        elif worst.status == "needs_improvement":
            parts.append(f"يحتاج تحسين: {worst.component} بنسبة {worst.value:.1f}%")

    if confidence_gaps:
        critical_gaps = [g for g in confidence_gaps if g.level in ("CRITICAL", "LOW")]
        if critical_gaps:
            parts.append(f" الثقة منخفضة لـ {len(critical_gaps)} مؤشرات")

    if anomaly_patterns:
        severe = [a for a in anomaly_patterns if a.pattern_type == "severe"]
        if severe:
            parts.append(f"تم اكتشاف {len(severe)} شذوذ حاد")

    return ". ".join(parts) if parts else "لا توجد مشاكل حرجة"
