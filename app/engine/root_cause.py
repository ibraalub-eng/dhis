from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from app.models import Hospital, Indicator, IndicatorValue, ValidationResult, QualityScore, ConfidenceScore, AnomalyResult, Rule
import json
import logging

logger = logging.getLogger(__name__)

from app.engine.smart.anomaly import FEATURE_KEYS  # noqa: E402

# الأسماء العربية للمؤشرات المشتقة (نفس مفاتيح FEATURE_KEYS في محرك الشذوذ الذكي)
INDICATOR_NAMES = {
    "cs_rate": "معدل القيصارية",
    "smm_total": "المضاعفات الخطيرة",
    "mat_deaths": "الوفيات الأمومية",
    "nd": "وفيات المولودين",
    "sb": "الولادات الميتة",
    "preterm": "الولادات السابقة لأوانها",
    "lbw": "نقص وزن الولادة",
    "total_births": "إجمالي المواليد",
    "high_risk": "حالات الخطر العالي",
    "adolescent": "الحالات المراهقة",
}


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
    rule_type: str = "LOGIC"
    primary_cause_ar: str = ""


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
    priority_action_details: List[PriorityActionDetail] = field(default_factory=list)
    ai_recommendations: List[Dict] = field(default_factory=list)
    causal_tree: List[CausalNode] = field(default_factory=list)
    causal_chains: List[CausalChain] = field(default_factory=list)
    historical_trends: Dict[str, Dict] = field(default_factory=dict)
    peer_comparisons: Dict[str, PeerComparison] = field(default_factory=dict)
    summary_arabic: str = ""


@dataclass
class PriorityActionDetail:
    """إجراء أولوية مع تقدير كمي: أثر (نقاط جودة قابلة للاسترجاع 0-100)،
    جهد (1-5)، وعائد = أثر/جهد — مشتق من بيانات الفشل الفعلية."""
    action: str
    source: str  # rule | confidence | anomaly | quality | chain
    severity: str
    impact: float
    effort: int
    roi: float


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
class PeerIndicatorComparison:
    """مقارنة قيمة المستشفى الفعلية بمتوسط النظير لنفس المؤشر — لا مقارنة درجة الجودة بقيمة عشوائية."""
    indicator_code: str
    indicator_name: str
    hospital_value: float
    peer_group: str
    peer_count: int
    peer_mean: float
    peer_std: float
    hospital_percentile: float
    hospital_z_score: float
    gap_pct: float
    peer_governorates: List[str] = field(default_factory=list)
    peer_governorate_counts: Dict[str, int] = field(default_factory=dict)
    peer_types: List[str] = field(default_factory=list)


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
    chain_path: List[str] = field(default_factory=list)
    chain_path_arabic: str = ""


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


def _month_offset(month: str, months_back: int) -> str:
    """يعيد أول شهر ضمن نافذة الرجوع، نسبةً لشهر التقرير لا لتاريخ اليوم."""
    try:
        year, mon = (int(x) for x in month.split("-"))
    except (ValueError, AttributeError):
        return month
    idx = year * 12 + (mon - 1) - max(0, months_back - 1)
    y, m = divmod(idx, 12)
    return f"{y:04d}-{m + 1:02d}"


def get_historical_data(
    session: Session,
    hospital_id: int,
    indicator_code: str,
    months_back: int = 6,
    month: str = "",
) -> List[MonthDataPoint]:
    """
    Retrieve historical data for a specific indicator at a hospital.

    نافذة الأشهر تُحسب نسبةً لشهر التقرير (month) وليس تاريخ اليوم،
    حتى تعمل مع البيانات التاريخية. عند غياب month تُعاد آخر months_back
    أشهر متاحة في قاعدة البيانات.
    Returns list of MonthDataPoint objects for the last N months.
    """
    cutoff = _month_offset(month, months_back) if month else ""
    indicator = session.query(Indicator).filter(Indicator.code == indicator_code).first()
    if not indicator:
        return []

    # Main query: indicator values with quality + confidence scores
    q = (
        session.query(
            IndicatorValue.month,
            IndicatorValue.value,
            func.coalesce(QualityScore.score, 0).label("quality_score"),
            func.coalesce(ConfidenceScore.overall_confidence, 0).label("confidence"),
        )
        .join(Indicator, IndicatorValue.indicator_id == Indicator.id)
        .outerjoin(QualityScore, (IndicatorValue.hospital_id == QualityScore.hospital_id) & (IndicatorValue.month == QualityScore.month))
        .outerjoin(ConfidenceScore, (IndicatorValue.hospital_id == ConfidenceScore.hospital_id) & (IndicatorValue.month == ConfidenceScore.month))
        .filter(IndicatorValue.hospital_id == hospital_id, Indicator.id == indicator.id)
        .order_by(IndicatorValue.month.asc())
    )
    if cutoff:
        q = q.filter(IndicatorValue.month >= cutoff)

    rows = q.all()

    # Pre-fetch rule failure rates per month for this hospital
    fail_counts = {}
    total_counts = {}
    for fc_row in (
        session.query(ValidationResult.month, func.count(ValidationResult.id))
        .filter(ValidationResult.hospital_id == hospital_id, ValidationResult.status == "FAIL")
        .group_by(ValidationResult.month)
        .all()
    ):
        fail_counts[fc_row[0]] = fc_row[1]
    for tc_row in (
        session.query(ValidationResult.month, func.count(ValidationResult.id))
        .filter(ValidationResult.hospital_id == hospital_id)
        .group_by(ValidationResult.month)
        .all()
    ):
        total_counts[tc_row[0]] = tc_row[1]

    history = []
    for row in rows:
        m = row[0]
        fails = fail_counts.get(m, 0)
        total = total_counts.get(m, 0)
        rate = round((fails * 100.0 / total), 2) if total > 0 else 0.0
        history.append(MonthDataPoint(
            month=m,
            value=float(row[1] or 0),
            quality_score=float(row[2] or 0),
            confidence=float(row[3] or 0),
            rule_failure_rate=rate,
        ))
    return history


_SEVERITY_WEIGHT = {"CRITICAL": 1.0, "HIGH": 0.8, "MEDIUM": 0.6, "LOW": 0.4}

# جهد تقديري (1-5) حسب نوع القاعدة: إصلاح الإدخال أرخص من تغيير عملي
_EFFORT_BY_RULE_TYPE = {
    "LOGIC": 2,
    "DATA_QUALITY": 3,
    "CLINICAL": 3,
    "THRESHOLD": 3,
    "BENCHMARK": 4,
    "STATISTICAL": 4,
}


def _estimate_action_metrics(
    severity: str = "MEDIUM",
    failure_rate: float = 0.0,
    rule_type: str = "",
    confidence: float = 100.0,
    z_score: float = 0.0,
    impact_hint: float = 0.0,
) -> Dict[str, float]:
    """تقدير كمي (أثر/جهد/عائد) مشتق من بيانات الفشل الفعلية.

    - impact: نقاط الجودة القابلة للاسترجاع (0-100) = معدل الفشل × وزن الخطورة،
      أو فجوة الثقة / درجة الشذوذ عند غياب قاعدة.
    - effort: 1-5 حسب نوع القاعدة (إصلاح إدخال = 2، تغيير عملي = 4).
    - roi: أثر ÷ جهد.
    """
    sev_w = _SEVERITY_WEIGHT.get(str(severity).upper(), 0.6)
    if failure_rate > 0:
        impact = min(100.0, failure_rate * sev_w)
    elif confidence < 100:
        impact = min(100.0, (100.0 - confidence) * 0.9)
    elif z_score:
        impact = min(100.0, abs(z_score) * 25.0)
    else:
        impact = max(0.0, min(100.0, impact_hint))
    effort = int(_EFFORT_BY_RULE_TYPE.get(str(rule_type).upper(), 3))
    roi = round(impact / effort, 2) if effort else 0.0
    return {"impact": round(impact, 1), "effort": effort, "roi": roi}


def get_rule_failure_history(
    session: Session,
    hospital_id: int,
    rule_code: str,
    months_back: int = 6,
    month: str = "",
) -> List[MonthDataPoint]:
    """
    Retrieve per-month failure-rate history for a rule at a hospital.

    أكواد القواعد (R001…) ليست أكواد مؤشرات، لذا يُشتق الاتجاه من نسبة فشل
    القاعدة عبر الأشهر بدل قيمة مؤشر.
    """
    cutoff = _month_offset(month, months_back) if month else ""
    q = (
        session.query(
            ValidationResult.month,
            func.sum(func.case((ValidationResult.status == "FAIL", 1), else_=0)).label("fails"),
            func.count(ValidationResult.id).label("total"),
        )
        .filter(ValidationResult.hospital_id == hospital_id, ValidationResult.rule_code == rule_code)
        .group_by(ValidationResult.month)
        .order_by(ValidationResult.month.asc())
    )
    if cutoff:
        q = q.filter(ValidationResult.month >= cutoff)
    rows = q.all()
    history = []
    for row in rows:
        fails = row[1] or 0
        total = row[2] or 0
        rate = round((fails * 100.0 / total), 2) if total > 0 else 0.0
        history.append(MonthDataPoint(
            month=row[0],
            value=round(rate, 2),
            quality_score=0,
            confidence=0,
            rule_failure_rate=round(rate, 2),
        ))
    return history


def get_peer_historical_data(
    session: Session,
    hospital_id: int,
    indicator_code: str,
    months_back: int = 6,
    month: str = "",
) -> Dict[str, List[MonthDataPoint]]:
    """
    Retrieve historical data for peer hospitals (same type).

    Returns dict of {hospital_name: [MonthDataPoint, ...]}
    """
    hosp = session.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp or not hosp.hospital_type_id:
        return {}

    peers = session.query(Hospital.id, Hospital.name).filter(
        Hospital.hospital_type_id == hosp.hospital_type_id,
        Hospital.id != hospital_id,
        Hospital.is_active.is_(True),
    )

    peer_data = {}
    for peer in peers:
        history = get_historical_data(session, peer[0], indicator_code, months_back, month=month)
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
        "slope": float(round(slope, 2)),
        "r_squared": float(round(r_value ** 2, 3)),
        "volatility": float(round(volatility, 2)),
        "direction": direction,
        "significant_change": bool(p_value < 0.05),
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
    hosp = session.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        return {}

    result = {}

    # Peers by type
    if hosp.hospital_type_id:
        peer_ids = [r[0] for r in session.query(Hospital.id).filter(
            Hospital.hospital_type_id == hosp.hospital_type_id,
            Hospital.id != hospital_id,
            Hospital.is_active.is_(True),
        ).all()]
        if len(peer_ids) >= MIN_PEER_SIZE:
            result["hospital_type"] = peer_ids

    # Peers by ownership
    if hosp.facility_ownership_id:
        peer_ids = [r[0] for r in session.query(Hospital.id).filter(
            Hospital.facility_ownership_id == hosp.facility_ownership_id,
            Hospital.id != hospital_id,
            Hospital.is_active.is_(True),
        ).all()]
        if len(peer_ids) >= MIN_PEER_SIZE:
            result["ownership"] = peer_ids

    # Peers by region
    if hosp.governorate_id:
        peer_ids = [r[0] for r in session.query(Hospital.id).filter(
            Hospital.governorate_id == hosp.governorate_id,
            Hospital.id != hospital_id,
            Hospital.is_active.is_(True),
        ).all()]
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


def _extract_rule_structure(session: Session) -> Dict[str, Dict]:
    """
    Build a map of rule_code -> {parent, children} from the rules.params JSON.

    rules.params encodes the indicator hierarchy, e.g. R001 checks that the
    total indicator "2" is >= the sum of its children ["3", "4", "5"].
    Returns {} on empty rules table or unparseable params.
    """
    try:
        rows = session.query(Rule.code, Rule.params).all()
    except Exception:
        return {}
    structure = {}
    for code, params_json in rows:
        try:
            params = json.loads(params_json) if params_json else {}
        except (ValueError, TypeError):
            continue
        if not isinstance(params, dict):
            continue
        parent = params.get("parent")
        child = params.get("child")
        children = params.get("children")
        num = params.get("num_code")
        den = params.get("den_code")
        if isinstance(children, list) and children:
            # شكلان: {parent, children} (R001) أو {child, children} (R024)
            structure[code] = {
                "total": parent or child,
                "parts": list(children),
            }
        elif parent and child:
            # شكل {child, parent}: القاعدة تفحص جزءاً داخل إجمالي
            structure[code] = {
                "total": parent,
                "parts": [child],
            }
        elif num:
            # قواعد المعدلات: تفحص نسبة (بسط/مقام) دون تفكيك — البسط هو المؤشر المقارن
            structure[code] = {
                "total": num,
                "parts": [],
            }
        elif parent:
            structure[code] = {
                "total": parent,
                "parts": [],
            }
    return structure


def _link_rule_causes(
    failing: List[RuleFailurePattern],
    structure: Dict[str, Dict],
) -> Dict[str, List[str]]:
    """
    Link failing rules into a cause graph: parent rule <- child rules.

    A rule C is a direct cause of rule P when C's checked indicator
    (parent / child / num_code) appears inside P's children set. E.g.
    R001 children include "5", and R006's parent is "5", so R006 is a
    direct cause of R001. Returns {rule_code: [direct causes...]}.
    """
    causes: Dict[str, List[str]] = {f.rule_code: [] for f in failing}
    for p in failing:
        p_struct = structure.get(p.rule_code)
        if not p_struct:
            continue
        p_parts = set(p_struct["parts"])
        for c in failing:
            if c.rule_code == p.rule_code:
                continue
            c_struct = structure.get(c.rule_code)
            if not c_struct:
                continue
            c_total = c_struct.get("total")
            c_parts = set(c_struct.get("parts", []))
            # C سبب مباشر لـ P إذا كان مؤشر C الإجمالي ضمن أجزاء P،
            # أو شارك C نفس الأجزاء الدقيقة التي يفككها P (تعمق أكبر)
            if (c_total and c_total in p_parts) or (c_parts & p_parts):
                causes[p.rule_code].append(c.rule_code)
    # فرز الأسباب حسب معدل الفشل ثم الخطورة (الأكثر احتمالاً أولاً)
    rate = {f.rule_code: f.failure_rate for f in failing}
    sev = {f.rule_code: f.severity for f in failing}
    sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    for code in causes:
        causes[code].sort(key=lambda x: (sev_rank.get(str(sev.get(x)).upper(), 9), -rate.get(x, 0)))
    return causes


def _walk_deepest_path(
    code: str,
    causes: Dict[str, List[str]],
    visited: set,
) -> List[str]:
    """أعمق سلسلة سببية بدءاً من code (الأب ← الأبناء ← الأحفاد)."""
    best = []
    for cause in causes.get(code, []):
        if cause in visited:
            continue
        sub = _walk_deepest_path(cause, causes, visited | {code})
        if len(sub) + 1 > len(best):
            best = [cause] + sub
    return best


def build_transitive_causal_chains(
    session: Session,
    rule_failures: List[RuleFailurePattern],
) -> List[CausalChain]:
    """
    Build deep causal chains by linking transitive rule failures.

    A rule's params declare which indicators it checks; when a parent rule
    (e.g. R001 checks total "2" >= sum of ["3","4","5"]) and a child rule
    (e.g. R006 checks "5" = emergency + planned C-sections) both fail, the
    child failure is a likely cause of the parent failure. chain_path is
    ordered [top symptom, ..., deepest cause] — القراءة من الأب إلى الأعمق.
    Note: ربط قواعد المعدلات (مثل R041) بقواعد المجاميع ارتباطي لا سببي صِرف؛
    إنه تخمين استدلالي لترتيب أولويات الفحص.
    """
    structure = _extract_rule_structure(session)
    if not structure:
        return []
    causes = _link_rule_causes(rule_failures, structure)
    severity = {f.rule_code: f.severity for f in rule_failures}
    rate = {f.rule_code: f.failure_rate for f in rule_failures}
    sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

    # المستويات العليا فقط: قواعد ليست سبباً لقاعدة أخرى فاشلة (لتفادي سلاسل مكررة)
    is_cause = {c for cs in causes.values() for c in cs}
    top_level = [f for f in rule_failures if f.rule_code not in is_cause]

    chains = []
    for f in top_level:
        path = _walk_deepest_path(f.rule_code, causes, set())
        if len(path) < 1:
            continue  # لا توجد سلاسل متعدية — تُترك للارتباطات العادية
        full = [f.rule_code] + path  # الأب ← الأبناء ← الأحفاد
        arabic_names = _rule_arabic_labels(full)
        evidence = [
            f"{code} failure rate: {rate.get(code, 0)}%"
            for code in full
        ]
        # الثقة: كلما تعمقت السلسلة زادت الثقة في السبب الجذري
        depth_bonus = min(0.25, len(full) * 0.08)
        confidence = round(min(0.95, 0.5 + depth_bonus), 2)
        impact = sum(rate.get(code, 0) * (0.6 if str(severity.get(code)).upper() == "CRITICAL" else 0.4) for code in full)
        chains.append(CausalChain(
            root_cause=f"{f.rule_code} failing at {rate.get(f.rule_code, 0)}% "
                        f"(root cause chain: {' -> '.join(full)})",
            root_cause_arabic=f"فشل {f.rule_code} بنسبة {rate.get(f.rule_code, 0)}% "
                              f"(السلسلة الكاملة: {' ← '.join(arabic_names)})",
            confidence=confidence,
            evidence=evidence,
            affected_factors=full,
            recommended_action=_diagnose_rule_failure(path[-1], "")[1]
            if path else f"Investigate and fix {full[0]} root cause",
            impact_if_fixed=round(impact, 1),
            implementation_priority=severity.get(f.rule_code, "HIGH"),
            chain_path=full,
            chain_path_arabic=" ← ".join(arabic_names),
        ))

    chains.sort(key=lambda c: (sev_rank.get(str(c.implementation_priority).upper(), 9), -c.confidence))
    return chains


def _rule_arabic_labels(codes: List[str]) -> List[str]:
    """تسميات عربية مختصرة لأكواد القواعد في السلسلة."""
    labels = {
        "R001": "إجمالي الولادات", "R002": "الولادات الأولى/متعددة",
        "R003": "الفئات العمرية", "R004": "داخل/خارج المنشأة",
        "R005": "مخاطر الحمل", "R006": "القيصرية الطارئة/المجدولة",
        "R007": "القيصرية الأولية/التكرارية", "R008": "القيصرية الطارئة",
        "R009": "القيصرية المجدولة", "R010": "القيصرية التكرارية",
        "R011": "أجناس المواليد", "R014": "الولادات المبكرة",
        "R015": "نقص الوزن", "R016": "الولادات الميتة",
        "R017": "الإجهاضات", "R021": "نزف ما بعد الولادة",
        "R024": "نزف الوضع", "R030": "مضاعفات النفاس",
        "R031": "مضاعفات الأمومة", "R041": "معدل القيصرية",
        "R042": "الولادات الطبيعية", "R051": "قفزة الولادات",
        "R052": "انخفاض الولادات", "R054": "الوفيات الأمومية",
        "R055": "وفيات المواليد", "R058": "نقص إجمالي الولادات",
        "R059": "نقص المواليد الأحياء",
    }
    return [labels.get(c, c) for c in codes]


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
    rows = (
        session.query(
            ValidationResult.rule_code,
            func.min(ValidationResult.rule_description).label("rule_description"),
            func.min(ValidationResult.severity).label("severity"),
            func.coalesce(func.min(Rule.rule_type), func.min(ValidationResult.rule_type), "LOGIC").label("rule_type"),
            func.count(ValidationResult.id).label("failure_count"),
            func.min(ValidationResult.details).label("details"),
            func.min(Rule.params).label("params"),
        )
        .outerjoin(Rule, Rule.code == ValidationResult.rule_code)
        .filter(ValidationResult.hospital_id == hospital_id, ValidationResult.month == month, ValidationResult.status == "FAIL")
        .group_by(ValidationResult.rule_code)
        .order_by(func.count(ValidationResult.id).desc())
        .all()
    )
    patterns = []
    for row in rows:
        rule_code = row[0]
        desc = row[1] or ""
        severity = row[2] or "LOW"
        rule_type = row[3]
        failure_count = row[4]
        details = row[5] or ""
        params_raw = row[6]
        try:
            params = json.loads(params_raw) if params_raw else {}
        except (ValueError, TypeError):
            params = {}
        total = session.query(func.count(ValidationResult.id)).filter(
            ValidationResult.hospital_id == hospital_id, ValidationResult.month == month, ValidationResult.rule_code == rule_code
        ).scalar() or 1
        failure_rate = round((failure_count / total) * 100, 1)

        primary_cause, recommendation = _diagnose_rule_failure_v2(rule_code, params, details)
        primary_cause_ar, _ = _diagnose_rule_failure_v2_ar(rule_code, params, details)
        patterns.append(RuleFailurePattern(
            rule_code=rule_code,
            rule_description=desc[:80],
            severity=severity,
            failure_count=failure_count,
            total_runs=total,
            failure_rate=failure_rate,
            primary_cause=primary_cause,
            recommendation=recommendation,
            primary_cause_ar=primary_cause_ar,
            rule_type=rule_type,
        ))
    patterns.sort(key=lambda p: (p.severity != "CRITICAL", p.severity != "HIGH", -p.failure_rate))
    return patterns[:10]


_CAUSE_MAP: Dict[str, Tuple[str, str]] = {
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
    "R003": ("Age-group breakdown doesn't sum to total deliveries",
             "Verify all age-group fields are filled and sum to Total Deliveries."),
    "R006": ("Emergency + Planned C-sections don't sum to Total C-sections",
             "Review the emergency/planned C-section split. Both sub-fields must sum to the total."),
    "R060": ("All key indicators reported as zero — facility may be non-operational or data missing",
             "CRITICAL: Confirm whether the facility operated this month; if it did, verify submission completeness."),
}


def _extract_rule_type(params: dict) -> str:
    """Classify a rule's params shape: SUM / PART / RATE / EXISTS / GENERIC."""
    if not isinstance(params, dict):
        return "GENERIC"
    if isinstance(params.get("children"), list) and params["children"]:
        return "SUM"
    if params.get("child") and params.get("parent"):
        return "PART"
    if params.get("num_code") and params.get("den_code"):
        return "RATE"
    if params.get("code"):
        return "EXISTS"
    return "GENERIC"


def _build_dynamic_diagnosis(rule_code: str, params: dict, details: str) -> Tuple[str, str]:
    """Generate (cause, recommendation) from a rule's structure. Returns ("", "") when no structure."""
    rtype = _extract_rule_type(params)
    if rtype == "SUM":
        children = ", ".join(str(x) for x in params["children"][:3])
        total = params.get("parent") or params.get("child") or "total"
        return (
            f"Sub-indicators ({children}) don't sum to total ({total}). Check for missing or duplicate sub-indicator reporting.",
            "Verify all sub-categories are reported and sum correctly to the parent indicator.",
        )
    if rtype == "PART":
        child, parent = params.get("child"), params.get("parent")
        return (
            f"Component ({child}) doesn't reconcile with total ({parent}). Verify the component is correctly classified.",
            "Confirm the breakdown value is classified under the correct category.",
        )
    if rtype == "RATE":
        num, den = params.get("num_code"), params.get("den_code")
        return (
            f"Rate ({num}/{den}) outside expected bounds. Review the raw counts feeding the ratio.",
            "Verify numerator and denominator source values are accurate and complete.",
        )
    if rtype == "EXISTS":
        code = params.get("code")
        return (
            f"Required indicator ({code}) missing or not reported. Confirm submission completeness.",
            "Ensure all mandatory indicators are filled before submission.",
        )
    return ("", "")


def _diagnose_rule_failure(rule_code: str, details: str) -> Tuple[str, str]:
    if rule_code in _CAUSE_MAP:
        return _CAUSE_MAP[rule_code]
    low = details.lower()
    if "exceeds" in low or ">" in details or "duplicate" in low:
        return ("Value exceeds expected threshold or is duplicated",
                "Review the data value. If accurate, investigate underlying causes.")
    if "missing" in low or "not reported" in low:
        return ("Required indicator value not reported",
                "Ensure all mandatory indicators are filled before submission.")
    if "negative" in low:
        return ("Negative value reported for count indicator",
                "Negative counts are impossible. Check data entry for sign errors.")
    if "decimal" in low:
        return ("Decimal value reported for count field",
                "Counts must be integers. Check if value was incorrectly entered.")
    if "zero" in low or "all zeros" in low:
        return ("Zero value reported for an indicator expected to be non-zero",
                "Verify the facility was operational and data was fully reported.")
    if "mismatch" in low or "inconsistent" in low:
        return ("Reported values are inconsistent or mismatched",
                "Reconcile the reported values against source records.")
    return ("Rule validation check failed",
            "Review the specific indicator values and verify against source records.")


def _diagnose_rule_failure_v2(rule_code: str, params: dict, details: str) -> Tuple[str, str]:
    """Three-level diagnosis: explicit map -> structural -> details patterns (English)."""
    if rule_code in _CAUSE_MAP:
        return _CAUSE_MAP[rule_code]
    cause, rec = _build_dynamic_diagnosis(rule_code, params, details)
    if cause:
        return cause, rec
    return _diagnose_rule_failure(rule_code, details)


_CAUSE_MAP_AR: Dict[str, Tuple[str, str]] = {
    "R001": ("عدم تطابق مجموع الأجزاء مع الإجمالي",
             "تحقق من إبلاغ جميع الفئات الفرعية، وافحص أي مؤشر ناقص أو مشفّر خطأً."),
    "R002": ("تفصيل الولادات الأولى/المتعددة لا يطابق إجمالي الولادات",
             "راجع إدخال الولادات الأولى والمتعددة، وتأكد من ملء الحقلين."),
    "R004": ("عدم تطابق تفصيل داخل/خارج المنشأة",
             "تأكد من صحة تصنيف الولادات داخل المنشأة وخارجها."),
    "R005": ("عدم تطابق تصنيف المخاطر",
             "تحقق من تطبيق معايير تصنيف المخاطر المنخفضة/العالية بشكل ثابت."),
    "R041": ("معدل القيصرية يتجاوز العتبة الآمنة",
             "راجع مؤشرات العمليات القيصرية، وادرس الحد من القيصرية غير الضرورية."),
    "R042": ("معدل الولادات الطبيعية منخفض جداً",
             "تحقق من نقص الإبلاغ عن الولادات الطبيعية أو تصنيفها خطأً كقيصرية."),
    "R051": ("قفزة في الولادات تتجاوز ضعفي الشهر السابق",
             "تحقق من دقة البيانات؛ قد يشير لتكرار في الإبلاغ أو تدفق إحالات حقيقي."),
    "R052": ("انخفاض الولادات أكثر من 50% عن الشهر السابق",
             "افحص اكتمال الإبلاغ؛ قد يشير لفجوة في جمع البيانات."),
    "R054": ("ارتفاع الوفيات الأمومية فوق العتبة",
             "حرج: تحقيق فوري مطلوب، وراجع كل حالة وفاة أمومية."),
    "R055": ("ارتفاع وفيات المواليد فوق العتبة",
             "حرج: تحقيق فوري مطلوب، وراجع بروتوكولات رعاية المواليد."),
    "R058": ("مؤشر إجمالي الولادات غير مُبلَّغ عنه",
             "مؤشر أساسي غير مُبلَّغ؛ قد تكون المنشأة لم ترسل بيانات كاملة."),
    "R059": ("مؤشر المواليد الأحياء غير مُبلَّغ عنه",
             "مؤشر أساسي غير مُبلَّغ؛ مطلوب لحساب معدل وفيات المواليد."),
    "R003": ("تفصيل الفئات العمرية لا يطابق إجمالي الولادات",
             "تحقق من ملء جميع حقول الفئات العمرية ومطابقتها لإجمالي الولادات."),
    "R006": ("مجموع القيصرية الطارئة والمخطط لها لا يطابق إجمالي العمليات القيصرية",
             "راجع توزيع العمليات القيصرية؛ يجب أن يطابق مجموع الحقلين الإجمالي."),
    "R060": ("جميع المؤشرات الرئيسية صفر — قد تكون المنشأة غير عاملة أو البيانات مفقودة",
             "حرج: تحقق إن كانت المنشأة تعمل هذا الشهر؛ وإن كانت تعمل فتأكد من اكتمال الإرسال."),
}


def _diagnose_rule_failure_ar(rule_code: str, details: str) -> Tuple[str, str]:
    """نسخة عربية من _diagnose_rule_failure (السبب + التوصية)."""
    if rule_code in _CAUSE_MAP_AR:
        return _CAUSE_MAP_AR[rule_code]
    low = details.lower()
    if "exceeds" in low or ">" in details or "duplicate" in low:
        return ("القيمة تتجاوز العتبة المتوقعة أو مكررة",
                "راجع القيمة؛ إن كانت دقيقة فحقق في الأسباب الكامنة.")
    if "missing" in low or "not reported" in low:
        return ("قيمة المؤشر المطلوب غير مُبلَّغ عنها",
                "تأكد من ملء جميع المؤشرات الإلزامية قبل الإرسال.")
    if "negative" in low:
        return ("قيمة سالبة لمؤشر عددي",
                "القيم السالبة مستحيلة؛ راجع الإدخال بحثاً عن أخطاء الإشارة.")
    if "decimal" in low:
        return ("قيمة عشرية لحقل عددي",
                "يجب أن تكون العدّادات أرقاماً صحيحة؛ تحقق من صحة الإدخال.")
    if "zero" in low or "all zeros" in low:
        return ("قيمة صفرية لمؤشر يُتوقع أن يكون غير صفري",
                "تحقق من أن المنشأة كانت تعمل وأن البيانات أُرسلت كاملة.")
    if "mismatch" in low or "inconsistent" in low:
        return ("القيم المُبلَّغ عنها غير متسقة أو غير متطابقة",
                "طابق القيم المُبلَّغ عنها مع السجلات المصدرية.")
    return ("فشل فحص التحقق من القاعدة",
            "راجع قيم المؤشرات المحددة وتحقق منها مقابل السجلات المصدرية.")


_CAUSE_MAP_AR_STRUCT = {
    "SUM": ("المؤشرات الفرعية لا تجمع للإجمالي. تحقق من نقص أو تكرار الإبلاغ عن مؤشر فرعي.",
            "تأكد من إبلاغ جميع الفئات الفرعية وأن مجموعها يطابق المؤشر الأصلي."),
    "PART": ("المكوّن لا يتطابق مع الإجمالي. تحقق من صحة تصنيف المكوّن.",
             "تأكد من تصنيف القيمة التفصيلية تحت الفئة الصحيحة."),
    "RATE": ("نسبة المؤشرين خارج الحدود المتوقعة. راجع القيم الخام المغذية للنسبة.",
             "تحقق من صحة واكتمال قيم البسط والمقام المصدرية."),
    "EXISTS": ("المؤشر المطلوب غير مُبلّغ. تأكد من اكتمال الإرسال.",
               "تأكد من ملء جميع المؤشرات الإلزامية قبل الإرسال."),
}


def _diagnose_rule_failure_v2_ar(rule_code: str, params: dict, details: str) -> Tuple[str, str]:
    """Three-level diagnosis: explicit map -> structural -> details patterns (Arabic)."""
    if rule_code in _CAUSE_MAP_AR:
        return _CAUSE_MAP_AR[rule_code]
    rtype = _extract_rule_type(params)
    if rtype in _CAUSE_MAP_AR_STRUCT:
        return _CAUSE_MAP_AR_STRUCT[rtype]
    return _diagnose_rule_failure_ar(rule_code, details)


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
    cs = session.query(ConfidenceScore.indicators_data).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    if not cs or not cs[0]:
        return []
    try:
        indicators = json.loads(cs[0])
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


def _diagnose_confidence_gap_ar(signal_factor: str, name: str, level: str) -> Tuple[str, str]:
    """نسخة عربية من _diagnose_confidence_gap."""
    diagnoses = {
        "rule_compliance": (
            f"المؤشر '{name}' يفشل بانتظام في قواعد التحقق",
            "راجع فشل القواعد الخاص بهذا المؤشر وتحقق من دقة الإدخال."
        ),
        "historical": (
            f"المؤشر '{name}' يظهر تقلباً عالياً مقارنة بالاتجاه التاريخي",
            "تحقق من القيم الأخيرة؛ إن كانت دقيقة فافحص ما تغيّر في فترة الإبلاغ."
        ),
        "cross_hospital": (
            f"المؤشر '{name}' ينحرف بشكل كبير عن المستشفيات النظيرة",
            "راجع إن كان انحرافاً حقيقياً أو خطأ إبلاغ، وقارن مع منشآت مماثلة."
        ),
        "trend": (
            f"المؤشر '{name}' له اتجاه غير مستقر أو مقلق",
            "حلل اتجاه 3-6 أشهر، وحدد إن كان تغيراً موسمياً أو تحولاً مستمراً."
        ),
        "completeness": (
            f"المؤشر '{name}' ينقصه مكوّنات فرعية أو مؤشرات مرتبطة",
            "تأكد من ملء جميع المؤشرات الفرعية والحقول ذات الصلة."
        ),
    }
    if signal_factor in diagnoses:
        return diagnoses[signal_factor]
    return (
        f"عوامل متعددة تسهم في انخفاض الثقة في '{name}'",
        "راجع جميع مصادر البيانات لهذا المؤشر، وفكر في التحقق اليدوي من السجلات المصدرية."
    )


def analyze_anomaly_patterns(
    session: Session,
    hospital_id: int,
    month: str,
) -> List[AnomalyPattern]:
    rows = (
        session.query(
            AnomalyResult.indicator_code,
            func.min(AnomalyResult.rate_name).label("rate_name"),
            func.count(AnomalyResult.id).label("hosp_count"),
            func.avg(func.abs(AnomalyResult.z_score)).label("avg_z"),
        )
        .filter(AnomalyResult.hospital_id == hospital_id, AnomalyResult.month == month, AnomalyResult.is_outlier.is_(True))
        .group_by(AnomalyResult.indicator_code)
        .order_by(func.avg(func.abs(AnomalyResult.z_score)).desc())
        .all()
    )
    # Pre-fetch previous months for recurrence check
    prev_months = [r[0] for r in session.query(IndicatorValue.month).filter(
        IndicatorValue.hospital_id == hospital_id, IndicatorValue.month < month
    ).distinct().all()]
    patterns = []
    for row in rows:
        code = row[0] or ""
        rate_name = row[1] or ""
        hosp_count = row[2] or 0
        avg_z = round(float(row[3] or 0), 2)
        recurrence = 0
        if prev_months:
            recurrence = session.query(func.count(AnomalyResult.id)).filter(
                AnomalyResult.hospital_id == hospital_id,
                AnomalyResult.indicator_code == code,
                AnomalyResult.is_outlier.is_(True),
                AnomalyResult.month.in_(prev_months),
            ).scalar() or 0
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


def _rec_priority_rank(p: str) -> int:
    """ترتيب الأولوية للفرز: حرج < عالٍ < متوسط < منخفض."""
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(p).lower(), 4)


_AR_CATEGORY_NAMES = {
    "Data Validation": "التحقق من البيانات",
    "Data Quality": "جودة البيانات",
    "Confidence Improvement": "رفع الثقة",
    "Outlier Management": "إدارة الشذوذ",
    "Peer Comparison": "مقارنة النظير",
    "Historical Decline": "الانحدار التاريخي",
    "Causal Chain": "السلاسل السببية",
    "Continuous Improvement": "التحسين المستمر",
    "General Monitoring": "المراقبة العامة",
    "Risk Management": "إدارة المخاطر",
    "Maternal Mortality": "الوفيات الأمومية",
    "Maternal Morbidity": "الاعتلال الأمومي",
    "C-Section Management": "إدارة القيصرية",
}


def _build_local_recommendations(
    hospital: str,
    month: str,
    overall_quality: float,
    overall_confidence: float,
    rule_failures: List[RuleFailurePattern],
    quality_drivers: List[QualityDriver],
    confidence_gaps: List[ConfidenceGap],
    anomaly_patterns: List[AnomalyPattern],
    causal_chains: List[CausalChain],
    peer_comparisons: Dict[str, PeerIndicatorComparison],
    historical_trends: Dict[str, Dict],
) -> List[Dict]:
    """توصيات محلية محددة وثنائية اللغة (عربي/إنجليزي) مبنية على بيانات التحليل الفعلية.

    تعمل دائماً (حتى دون مزود AI خارجي) وتذكر الأكواد والأرقام والتسميات العربية
    الحقيقية لكل مشكلة — بدل قوالب عامة.
    """
    recs: List[Dict] = []

    def _add(category, category_ar, priority, title, title_ar, description, description_ar,
             rationale, rationale_ar, action_items, action_items_ar, indicators):
        recs.append({
            "category": category, "category_ar": category_ar, "priority": priority,
            "title": title, "title_ar": title_ar,
            "description": description, "description_ar": description_ar,
            "rationale": rationale, "rationale_ar": rationale_ar,
            "action_items": action_items, "action_items_ar": action_items_ar,
            "affected_indicators": indicators,
        })

    # 1) السلاسل السببية — أعلى قيمة: تعالج السبب لا العرض
    for chain in causal_chains[:2]:
        prio = str(chain.implementation_priority).lower()
        # التوصية تستهدف أعمق سبب في السلسلة — نعربها بنفس المنطق
        deepest = chain.chain_path[-1] if chain.chain_path else (chain.affected_factors[-1] if chain.affected_factors else "")
        if deepest and deepest.startswith("R"):
            ar_action = _diagnose_rule_failure_ar(deepest, "")[1]
        else:
            ar_action = "حقق في السبب الجذري للمشكلة وطبّق الإجراءات التصحيحية"
        _add(
            "Causal Chain", "السلاسل السببية", prio,
            f"Fix root cause: {chain.root_cause}",
            chain.root_cause_arabic or f"معالجة السبب: {chain.root_cause}",
            f"{chain.recommended_action} — expected impact {chain.impact_if_fixed:.1f} quality points.",
            f"{ar_action} — الأثر المتوقع {chain.impact_if_fixed:.1f} نقطة جودة.",
            "Linked rule failures point to one common upstream cause — fixing it resolves several issues at once.",
            "فشل القواعد المترابط يشير إلى سبب منبع واحد مشترك — إصلاحه يحل عدة مشاكل معاً.",
            [chain.recommended_action],
            [ar_action],
            chain.affected_factors,
        )

    # 2) فشل قواعد التحقق الحرج/العالي
    for f in [x for x in rule_failures if str(x.severity).upper() in ("CRITICAL", "HIGH")][:2]:
        ar_label = _rule_arabic_labels([f.rule_code])[0]
        prio = "critical" if str(f.severity).upper() == "CRITICAL" else "high"
        ar_cause, ar_rec = _diagnose_rule_failure_ar(f.rule_code, f.primary_cause)
        _add(
            "Data Validation", "التحقق من البيانات", prio,
            f"Fix {f.rule_code}: {f.rule_description[:50]}",
            f"معالجة فشل {f.rule_code} ({ar_label}) — فشل بنسبة {f.failure_rate:.0f}%",
            f"{f.primary_cause} Failure rate {f.failure_rate:.0f}%.",
            f"{ar_cause} — معدل الفشل {f.failure_rate:.0f}%.",
            "Validation failures directly lower rule compliance and confidence.",
            "فشل قواعد التحقق يخفض الالتزام بالقواعد والثقة مباشرة.",
            [f.recommendation], [ar_rec], [f.rule_code],
        )

    # 3) فجوات الثقة
    for g in [x for x in confidence_gaps if str(x.level).upper() in ("CRITICAL", "LOW")][:2]:
        ar_cause, ar_rec = _diagnose_confidence_gap_ar(g.weakest_signal, g.indicator_name, g.level)
        _add(
            "Confidence Improvement", "رفع الثقة", "high",
            f"Improve confidence for {g.indicator_name}",
            f"رفع الثقة في {g.indicator_name}",
            f"Confidence {g.confidence:.0f}% — weakest signal: {g.weakest_signal}.",
            f"الثقة {g.confidence:.0f}% — أضعف إشارة: {g.weakest_signal}.",
            g.root_cause, ar_cause,
            [g.recommendation], [ar_rec], [g.indicator_code],
        )

    # 4) الشذوذ الحاد
    for a in [x for x in anomaly_patterns if x.pattern_type == "severe"][:2]:
        ar_desc = f"شذوذ حاد (|z|={a.avg_z_score}) لمؤشر {a.rate_name}"
        if a.recurrence_count:
            ar_desc += f" — يتكرر ({a.recurrence_count} أشهر سابقة)"
        _add(
            "Outlier Management", "إدارة الشذوذ", "high",
            f"Investigate severe anomaly: {a.rate_name}",
            f"التحقيق في شذوذ حاد: {a.rate_name}",
            f"|z|={a.avg_z_score} — {a.description}",
            ar_desc,
            "Severe anomalies may hide data entry errors or a real clinical change.",
            "الشذوذ الحاد قد يخفي أخطاء إدخال أو تغيراً سريرياً حقيقياً.",
            ["Verify source data for the flagged indicator", "Compare with previous months", "Investigate the clinical cause"],
            ["تحقق من البيانات المصدرية للمؤشر", "قارن مع الأشهر السابقة", "حقق في السبب السريري"],
            [a.indicator_code],
        )

    # 5) أضعف أبعاد الجودة
    if quality_drivers:
        worst = quality_drivers[0]
        if worst.status != "good":
            _ar_component = {
                "Rule Compliance": "الالتزام بالقواعد", "Completeness": "الاكتمال",
                "Consistency": "الاتساق", "Outlier Penalty": "جزاء الشذوذ",
            }.get(worst.component, worst.component)
            ar_rec = (f"{_ar_component} عند {worst.value:.1f}% دون الهدف — راجع الإجراءات ذات الصلة."
                      if worst.status != "critical"
                      else f"{_ar_component} عند {worst.value:.1f}% يتطلب انتباهاً عاجلاً — حقق في الأسباب الجذرية.")
            _add(
                "Data Quality", "جودة البيانات", "medium",
                f"Improve {worst.component} ({worst.value:.0f}%)",
                f"تحسين {_ar_component} ({worst.value:.0f}%)",
                worst.recommendation, ar_rec,
                f"Impact gap of {worst.impact:.0f} quality points.",
                f"فجوة أثر {worst.impact:.0f} نقطة جودة.",
                [worst.recommendation], [ar_rec], [],
            )

    # 6) فجوة النظير لكل مؤشر
    elevated = sorted(
        [c for c in peer_comparisons.values() if c.gap_pct > 20],
        key=lambda c: -c.gap_pct,
    )
    if elevated:
        top = elevated[0]
        _add(
            "Peer Comparison", "مقارنة النظير", "medium",
            f"{top.indicator_name} is {top.gap_pct:.0f}% above peer mean",
            f"{top.indicator_name} أعلى من متوسط النظير بـ {top.gap_pct:.0f}%",
            f"Hospital value {top.hospital_value} vs peer mean {top.peer_mean} (z={top.hospital_z_score}).",
            f"قيمة المستشفى {top.hospital_value} مقابل {top.peer_mean} للنظير (z={top.hospital_z_score}).",
            "Deviation from peers may signal a reporting issue or a genuine care difference.",
            "الانحراف عن النظير قد يشير إلى مشكلة إبلاغ أو اختلاف رعاية حقيقي.",
            ["Compare data entry practices with peers", "Review clinical practice differences"],
            ["قارن ممارسات الإدخال مع النظير", "راجع اختلافات الممارسة السريرية"],
            [top.indicator_code],
        )

    # 7) انحدار تاريخي
    declining = sorted(
        [(f, t) for f, t in historical_trends.items() if t.get("direction") == "declining"],
        key=lambda x: x[1].get("slope", 0),
    )
    if declining:
        f, t = declining[0]
        ar_label = _rule_arabic_labels([f])[0] if f.startswith("R") else INDICATOR_NAMES.get(f, f)
        _add(
            "Historical Decline", "الانحدار التاريخي", "high",
            f"{f} declining at {abs(t['slope']):.1f} points/month",
            f"{ar_label} في انحدار بمعدل {abs(t['slope']):.1f} شهرياً",
            f"Slope {t['slope']:.1f}/month, r²={t.get('r_squared', 0):.2f}.",
            f"الميل {t['slope']:.1f} شهرياً، التفسير {t.get('r_squared', 0):.2f}.",
            "Sustained decline predicts worsening without intervention.",
            "الانحدار المستمر يتنبأ بتدهور ما لم يُتدخل.",
            ["Investigate the last 3 months", "Compare with peer hospitals", "Monitor weekly until reversed"],
            ["حقق في آخر 3 أشهر", "قارن مع المستشفيات النظيرة", "راقب أسبوعياً حتى ينعكس الاتجاه"],
            [f],
        )

    # 8) ختامي عندما لا توجد مشاكل
    if not recs:
        _add(
            "Continuous Improvement", "التحسين المستمر", "low",
            "Maintain Data Quality Standards",
            "المحافظة على معايير جودة البيانات",
            "No critical issues detected. Continue regular monitoring and periodic reviews.",
            "لا توجد مشاكل حرجة. استمر في المراقبة الدورية والمراجعات.",
            "Sustained data quality requires ongoing attention even when no immediate issues exist.",
            "الجودة المستدامة تتطلب متابعة مستمرة حتى عند غياب مشاكل فورية.",
            ["Continue monthly quality reviews", "Document best practices for data entry", "Schedule quarterly training refreshers"],
            ["استمر في المراجعات الشهرية", "وثّق أفضل الممارسات للإدخال", "نظّم تدريبات تنشيطية ربع سنوية"],
            [],
        )

    return recs[:8]


def _has_arabic_script(val) -> bool:
    """هل يحتوي النص على حروف عربية (النطاق U+0600–U+06FF)؟"""
    return any("؀" <= ch <= "ۿ" for ch in str(val or ""))


def _has_real_arabic(r: Dict) -> bool:
    """هل تحمل التوصية وصفاً عربياً حقيقياً؟

    يشترط عربية في الوصف تحديداً (لا مجرد الفئة/العنوان): توصية بترجمة جزئية
    (عنوان عربي + وصف إنجليزي) قد تسرّب الإنجليزية إلى الواجهة العربية،
    لذا تُهمَل — المحلي ثنائي اللغة أخصّ وأكمل.
    """
    return _has_arabic_script(r.get("description_ar"))


def _ar_synthesis_for_ai_rec(r: Dict) -> Dict:
    """توليد حقول عربية لتوصية AI خالصة (عند غيابها من المزود الخارجي).

    لا تنسخ الإنجليزية أبداً إلى الحقول العربية — عند غياب الترجمة تُترك
    فارغة لتقع الواجهة على الحقل الإنجليزي في الوضع الإنجليزي فقط.
    """
    cat_ar = _AR_CATEGORY_NAMES.get(r.get("category", ""), r.get("category", ""))
    return {
        "category_ar": r.get("category_ar") or cat_ar,
        "title_ar": r.get("title_ar") or (f"توصية: {cat_ar}" if cat_ar else ""),
        "description_ar": r.get("description_ar") or "",
        "rationale_ar": r.get("rationale_ar") or "",
        "action_items_ar": r.get("action_items_ar") or [],
    }


def _build_peer_comparisons(session, hospital_id, month, peer_comparisons):
    """Build peer indicator comparisons for a hospital."""
    peer_groups = identify_peer_groups(session, hospital_id)
    if not peer_groups:
        return
    from app.engine.smart import _load_hospital_data
    month_data = _load_hospital_data(session, month)
    hospital_map = {}
    peer_values: Dict[str, List[float]] = {}
    peer_governorates: List[str] = []
    peer_governorate_counts: Dict[str, int] = {}
    peer_types: List[str] = []
    for name, entry in month_data.items():
        if entry["hospital_id"] == hospital_id:
            hospital_map = entry.get("values", {})
            continue
        gov = entry.get("governorate") or "unknown"
        peer_governorates.append(gov)
        peer_governorate_counts[gov] = peer_governorate_counts.get(gov, 0) + 1
        htype = entry.get("hospital_type") or "unknown"
        if htype not in peer_types:
            peer_types.append(htype)
        for code in FEATURE_KEYS:
            v = entry.get("values", {}).get(code)
            if v is not None:
                peer_values.setdefault(code, []).append(float(v))

    for code in FEATURE_KEYS:
        if code not in hospital_map or code not in peer_values or len(peer_values[code]) < 2:
            continue
        pvals = peer_values[code]
        mean = sum(pvals) / len(pvals)
        hv = hospital_map[code]
        if mean == 0 and hv == 0:
            continue
        std = (sum((v - mean) ** 2 for v in pvals) / len(pvals)) ** 0.5
        percentile = float(sum(1 for v in pvals if v <= hv) / len(pvals) * 100)
        z = (hv - mean) / std if std > 0 else 0.0
        gap_pct = ((hv - mean) / mean * 100) if mean != 0 else 0.0
        peer_comparisons[code] = PeerIndicatorComparison(
            indicator_code=code,
            indicator_name=INDICATOR_NAMES.get(code, code),
            hospital_value=round(hv, 2),
            peer_group=", ".join(sorted(peer_groups.keys())),
            peer_count=len(pvals),
            peer_mean=round(mean, 2),
            peer_std=round(std, 2),
            hospital_percentile=round(percentile, 1),
            hospital_z_score=round(z, 2),
            gap_pct=round(gap_pct, 2),
            peer_governorates=list(peer_governorates),
            peer_governorate_counts=dict(peer_governorate_counts),
            peer_types=list(peer_types),
        )


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

    try:
        rule_failures = analyze_rule_failures(session, hospital_id, month)
    except Exception:
        rule_failures = []
    try:
        quality_drivers = analyze_quality_drivers(quality_data)
    except Exception:
        quality_drivers = []
    try:
        confidence_gaps = analyze_confidence_gaps(session, hospital_id, month)
    except Exception:
        confidence_gaps = []
    try:
        anomaly_patterns = analyze_anomaly_patterns(session, hospital_id, month)
    except Exception:
        anomaly_patterns = []

    overall_quality = quality_data.get("score", 0) if quality_data else 0
    overall_confidence = confidence_data.get("overall_confidence", 0) if confidence_data else 0

    critical_count = len([f for f in rule_failures if f.severity == "CRITICAL"])
    critical_count += len([g for g in confidence_gaps if g.level == "CRITICAL"])

    causal_nodes = []
    for rf in rule_failures:
        history = []
        if include_history:
            try:
                history = get_rule_failure_history(session, hospital_id, rf.rule_code, months_back, month=month)
            except Exception:
                history = []

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

    # سلاسل متعدية عميقة من فشل القواعد (الأب ← الأبناء ← الأحفاد)
    transitive_chains = build_transitive_causal_chains(session, rule_failures)
    if transitive_chains:
        causal_chains = transitive_chains
    else:
        causal_chains = build_causal_chains(causal_nodes)

    peer_comparisons = {}
    if compare_peers:
        try:
            _build_peer_comparisons(session, hospital_id, month, peer_comparisons)
        except Exception as e:
            logger.warning(f"Peer comparison failed: {e}")

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
        if worst_gap.level == "CRITICAL":
            gap_phrase = "critically low"
        elif worst_gap.level == "LOW":
            gap_phrase = "low"
        else:
            gap_phrase = "moderate"
        summary_parts.append(
            f"Confidence is {gap_phrase} for {worst_gap.indicator_name} "
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
        hospital_name, month, overall_quality, overall_confidence,
        causal_chains, rule_failures, quality_drivers,
        confidence_gaps, anomaly_patterns, peer_comparisons,
    )

    priority_actions = []
    priority_action_details: List[PriorityActionDetail] = []

    def _add_action(action_text: str, source: str, severity: str, **metrics_kwargs) -> None:
        if len(priority_actions) >= 8:
            return
        priority_actions.append(action_text)
        m = _estimate_action_metrics(severity=severity, **metrics_kwargs)
        priority_action_details.append(PriorityActionDetail(
            action=action_text,
            source=source,
            severity=severity,
            impact=m["impact"],
            effort=m["effort"],
            roi=m["roi"],
        ))

    for chain in causal_chains[:3]:
        # impact_if_fixed يخرج على مقياس صغير (≈4-25) — نُطبعه على مقياس 0-100
        _add_action(
            f"[{chain.implementation_priority.upper()}] {chain.root_cause_arabic or chain.root_cause}: {chain.recommended_action}",
            "chain", chain.implementation_priority.upper(),
            impact_hint=min(100.0, chain.impact_if_fixed * 4),
        )
    for f in rule_failures[:3]:
        if f.severity in ("CRITICAL", "HIGH"):
            _add_action(
                f"[{f.severity}] {f.rule_code}: {f.recommendation[:100]}",
                "rule", f.severity,
                failure_rate=f.failure_rate, rule_type=f.rule_type,
            )
    for g in confidence_gaps[:3]:
        if g.level in ("CRITICAL", "LOW"):
            _add_action(
                f"[{g.level} Confidence] {g.indicator_name}: {g.recommendation[:100]}",
                "confidence", g.level,
                confidence=g.confidence,
            )
    for a in anomaly_patterns[:2]:
        if a.pattern_type == "severe":
            _add_action(
                f"[Anomaly] {a.description[:100]}",
                "anomaly", "HIGH",
                z_score=a.avg_z_score,
            )
    if quality_drivers:
        worst_q = quality_drivers[0]
        if worst_q.status != "good":
            _add_action(
                f"[Quality] {worst_q.recommendation[:100]}",
                "quality", "MEDIUM",
                impact_hint=worst_q.impact * 100 if worst_q.impact <= 1 else worst_q.impact,
            )

    # توصيات محلية محددة ثنائية اللغة — تعمل دائماً حتى دون مزود AI خارجي
    local_recs = _build_local_recommendations(
        hospital_name, month, overall_quality, overall_confidence,
        rule_failures, quality_drivers, confidence_gaps, anomaly_patterns,
        causal_chains, peer_comparisons, historical_trends,
    )

    ai_recs = []
    if _HAVE_AI:
        try:
            from app.plugins.ai.providers import AI_ENABLED as _AI_ENABLED, AI_API_KEY as _AI_API_KEY
        except ImportError:
            _AI_ENABLED, _AI_API_KEY = False, ""
        # المزود الخارجي يُستدعى عند التفعيل الفعلي بمفتاح فقط — خلاف ذلك
        # تبقى التوصيات المحلية ثنائية اللغة وحدها (محددة وموثوقة)
        if _AI_ENABLED and _AI_API_KEY:
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
                    "historical_trends": historical_trends,
                    "peer_comparisons": {
                        k: {
                            "indicator_code": v.indicator_code,
                            "indicator_name": v.indicator_name,
                            "hospital_value": v.hospital_value,
                            "peer_group": v.peer_group,
                            "peer_mean": v.peer_mean,
                            "hospital_percentile": v.hospital_percentile,
                            "hospital_z_score": v.hospital_z_score,
                            "gap_pct": v.gap_pct,
                        }
                        for k, v in peer_comparisons.items()
                    },
                }
                rc_ai_results = _generate_rc_ai(report_data_for_ai, session=session)
                ai_recs = [
                    {
                        "category": r.category, "category_ar": r.category_ar,
                        "priority": r.priority,
                        "title": r.title, "title_ar": r.title_ar,
                        "description": r.description, "description_ar": r.description_ar,
                        "rationale": r.rationale, "rationale_ar": r.rationale_ar,
                        "action_items": r.action_items, "action_items_ar": r.action_items_ar,
                        "affected_indicators": r.indicators_monitored,
                    }
                    for r in rc_ai_results
                ]
            except Exception as e:
                logger.error(f"Failed to generate AI root cause recommendations: {e}")

    # الدمج: المحلية أولاً (محددة وثنائية اللغة)، ثم توصيات AI غير المكررة،
    # مرتبة بالأولوية ثم مقطوعة عند السقف. البوابة _has_real_arabic تمنع أي
    # توصية بلا وصف عربي حقيقي (مثل ردود Gemini السابقة المخزنة إنجليزياً أو
    # مزود تجاهل تعليمات العربية) من التسرب للواجهة العربية — المحلي أخصّ وأفضل.
    merged = list(local_recs)
    for r in ai_recs:
        if len(merged) >= 8:
            break
        if not _has_real_arabic(r):
            continue
        if any(m["category"] == r["category"] for m in merged):
            continue
        ar = _ar_synthesis_for_ai_rec(r)
        merged.append({**r, **ar})
    merged.sort(key=lambda r: _rec_priority_rank(r["priority"]))
    ai_recommendations = merged[:8]

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
        priority_action_details=priority_action_details[:8],
        ai_recommendations=ai_recommendations,
        causal_tree=causal_nodes,
        causal_chains=causal_chains,
        historical_trends=historical_trends,
        peer_comparisons=peer_comparisons,
        summary_arabic=summary_arabic,
    )


def _generate_arabic_summary(
    hospital: str,
    month: str,
    overall_quality: float,
    overall_confidence: float,
    causal_chains,
    rule_failures,
    quality_drivers,
    confidence_gaps,
    anomaly_patterns,
    peer_comparisons,
) -> str:
    """سرد عربي تنفيذي متماسك لنتائج تحليل السبب الجذري.

    البنية: حالة عامة ← السبب الجذري ← الأدلة ← مقارنة النظير ←
    أبعاد الجودة والثقة ← الشذوذ ← الإجراء الموصى به أولاً.
    """
    parts = []

    # 1) افتتاحية الحالة العامة بسياق المستشفى والشهر —
    #    البوابة تعتمد على الإشارات الحرجة الفعلية لا على وجود السلاسل السببية
    #    (السلاسل لا تُبنى إلا عند توفر بنية params للقواعد وترابطها)
    has_critical = (
        any(str(r.severity).upper() == "CRITICAL" for r in rule_failures)
        or any(str(g.level).upper() == "CRITICAL" for g in confidence_gaps)
        or any(a.pattern_type == "severe" for a in anomaly_patterns)
    )
    if (overall_quality >= 80 and overall_confidence >= 80 and not has_critical):
        parts.append(
            f"تقرير {hospital} لشهر {month}: لا توجد مشاكل حرجة — "
            f"جودة البيانات ({overall_quality:.0f}%) والثقة ({overall_confidence:.0f}%) ضمن النطاق المقبول."
        )
    else:
        urgent = overall_quality < 50 or overall_confidence < 50 or has_critical
        status = "تتطلب تدخلاً عاجلاً" if urgent else "تحتاج متابعة"
        parts.append(
            f"تقرير {hospital} لشهر {month}: الحالة {status} — "
            f"جودة البيانات {overall_quality:.0f}% والثقة {overall_confidence:.0f}%."
        )

    # 2) السبب الجذري الرئيسي
    if causal_chains:
        top = causal_chains[0]
        parts.append(f"السبب الجذري الرئيسي: {top.root_cause_arabic} (بثقة {top.confidence:.0%})")

    # 3) أدلة قواعد التحقق
    if rule_failures:
        critical = [r for r in rule_failures if r.severity == "CRITICAL"]
        top = rule_failures[0]
        label = _rule_arabic_labels([top.rule_code])[0]
        if critical:
            parts.append(
                f"توجد {len(critical)} قواعد تحقق حرجة، أبرزها {top.rule_code} "
                f"({label}) بنسبة فشل {top.failure_rate:.0f}%"
            )
        else:
            parts.append(f"أبرز فشل تحقق: {top.rule_code} ({label}) بنسبة {top.failure_rate:.0f}%")

    # 4) مقارنة النظير لكل مؤشر
    if peer_comparisons:
        elevated = [c for c in peer_comparisons.values() if c.gap_pct > 20]
        if elevated:
            top = max(elevated, key=lambda c: c.gap_pct)
            parts.append(
                f"مقارنة بالنظراء: {top.indicator_name} أعلى من متوسط النظير بـ {top.gap_pct:.0f}% "
                f"(قيمة المستشفى {top.hospital_value} مقابل {top.peer_mean} للنظير)"
            )

    # 5) أضعف أبعاد الجودة
    if quality_drivers:
        worst = quality_drivers[0]
        if worst.status == "critical":
            parts.append(f"الجودة متأثرة بشدة ببعد {worst.component} ({worst.value:.1f}%)")
        elif worst.status == "needs_improvement":
            parts.append(f"أضعف أبعاد الجودة: {worst.component} ({worst.value:.1f}%)")

    # 6) فجوات الثقة
    if confidence_gaps:
        critical_gaps = [g for g in confidence_gaps if g.level in ("CRITICAL", "LOW")]
        if critical_gaps:
            names = "، ".join(g.indicator_name for g in critical_gaps[:3])
            parts.append(f"الثقة منخفضة لمؤشرات: {names}")

    # 7) الشذوذ الحاد
    if anomaly_patterns:
        severe = [a for a in anomaly_patterns if a.pattern_type == "severe"]
        if severe:
            parts.append(
                f"رصد {len(severe)} شذوذ حاد، أبرزها {severe[0].rate_name} (z={severe[0].avg_z_score})"
            )

    # 8) الإجراء الأول الموصى به
    if causal_chains:
        parts.append(f"أولوية التنفيذ المقترحة: {causal_chains[0].recommended_action}")

    # الجملة الافتتاحية تُضاف دائماً في كل الفرعين — لا حاجة لبديل احتياطي
    return ". ".join(parts)
