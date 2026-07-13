import json
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
from app.engine.quality import RuleResult, RuleStatus, Severity, RuleType
from app.engine.anomaly_trends import compute_rate, RATE_DEFINITIONS


INDICATOR_CLINICAL_WEIGHTS: Dict[str, float] = {
    "11": 5.0,
    "17": 5.0,
    "2":  3.0,
    "6":  3.0,
    "5":  2.5,
    "10": 2.0,
    "7":  2.0,
    "6.f": 2.0,
    "6.g": 2.0,
    "16": 1.5,
    "8":  1.0,
    "3":  1.5,
    "4":  1.5,
    "9":  1.0,
    "12": 1.0,
    "13": 1.0,
    "14": 0.5,
    "18": 0.5,
    "26": 1.5,
}

INDICATOR_GROUPS: Dict[str, List[str]] = {
    "Deliveries": ["2", "3", "4", "5"],
    "Newborn Outcomes": ["6", "6.f", "6.g", "9", "16", "17", "26"],
    "Maternal Complications": ["10", "10.a", "10.e", "10.f", "12"],
    "Mortality": ["11", "17"],
    "Pregnancy Outcomes": ["7", "8"],
    "Other Services": ["13", "14", "18", "19", "20", "21", "22", "23", "24", "25"],
}

SIGNAL_WEIGHTS: Dict[str, float] = {
    "rule_compliance": 0.55,
    "historical": 0.10,
    "cross_hospital": 0.10,
    "trend": 0.10,
    "completeness": 0.15,
}

RATE_NUM_CODES: Set[str] = set()
for _, num, den, _ in RATE_DEFINITIONS:
    RATE_NUM_CODES.add(num)
    RATE_NUM_CODES.add(den)


@dataclass
class ConfidenceSignal:
    factor: str
    passed: bool
    score: float
    detail: str


@dataclass
class IndicatorConfidence:
    indicator_code: str
    indicator_name: str
    value: Optional[float]
    confidence: float
    level: str
    signals: List[ConfidenceSignal] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "indicator_code": self.indicator_code,
            "indicator_name": self.indicator_name,
            "value": float(self.value) if self.value is not None else None,
            "confidence": round(float(self.confidence), 1),
            "level": self.level,
            "signals": [
                {
                    "factor": s.factor,
                    "passed": bool(s.passed),
                    "score": round(float(s.score), 3),
                    "detail": s.detail,
                }
                for s in self.signals
            ],
            "recommendations": self.recommendations,
        }


@dataclass
class HospitalConfidenceResult:
    hospital: str
    month: str
    overall_confidence: float
    level: str
    indicator_count: int
    by_level: Dict[str, int]
    by_group: Dict[str, float]
    indicators: List[IndicatorConfidence]
    priority_verify: List[IndicatorConfidence]
    summary: str

    def to_dict(self) -> dict:
        return {
            "hospital": self.hospital,
            "month": self.month,
            "overall_confidence": round(float(self.overall_confidence), 1),
            "level": self.level,
            "indicator_count": int(self.indicator_count),
            "by_level": {k: int(v) for k, v in self.by_level.items()},
            "by_group": {k: round(float(v), 1) for k, v in self.by_group.items()},
            "indicators": [i.to_dict() for i in self.indicators],
            "priority_verify": [i.to_dict() for i in self.priority_verify],
            "summary": self.summary,
        }


def _extract_codes_from_params(expr_type: str, params: dict) -> List[str]:
    codes = []
    if expr_type in ("ge", "eq"):
        codes.append(params.get("parent", ""))
        codes.extend(params.get("children", []))
    elif expr_type == "le":
        codes.append(params.get("child", ""))
        codes.append(params.get("parent", ""))
    elif expr_type == "le_sum":
        codes.append(params.get("child", ""))
        codes.extend(params.get("children", []))
    elif expr_type in ("benchmark_rate", "benchmark_low_rate", "cross_hospital_rate"):
        codes.append(params.get("num_code", ""))
        codes.append(params.get("den_code", ""))
    elif expr_type in ("month_over", "month_under"):
        codes.append(params.get("code", ""))
    elif expr_type in ("neg_check", "decimal_check"):
        codes.extend(params.get("codes", []))
    elif expr_type == "missing":
        codes.append(params.get("code", ""))
    elif expr_type == "all_zero":
        codes.extend(params.get("codes", ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]))
    return [c for c in codes if c]


def build_indicator_rule_map(session) -> Dict[str, List[str]]:
    from app.models import Rule
    rules = session.query(Rule).filter(Rule.enabled == True).all()
    mapping: Dict[str, List[str]] = {}
    for rule in rules:
        params = json.loads(rule.params) if isinstance(rule.params, str) else (rule.params or {})
        codes = _extract_codes_from_params(rule.expression_type, params)
        for code in codes:
            mapping.setdefault(code, []).append(rule.code)
    return mapping


def _get_relevant_rule_results(
    indicator_code: str,
    rule_results: List[RuleResult],
    indicator_rule_map: Dict[str, List[str]],
) -> List[RuleResult]:
    relevant_codes = set(indicator_rule_map.get(indicator_code, []))
    if not relevant_codes:
        return []
    return [r for r in rule_results if r.rule_code in relevant_codes]


def _signal_rule_compliance(
    indicator_code: str,
    rule_results: List[RuleResult],
    indicator_rule_map: Dict[str, List[str]],
) -> ConfidenceSignal:
    relevant = _get_relevant_rule_results(indicator_code, rule_results, indicator_rule_map)
    if not relevant:
        return ConfidenceSignal("rule_compliance", True, 1.0, "No rules reference this indicator")
    passed = sum(1 for r in relevant if r.status == RuleStatus.PASS)
    total = len(relevant)
    score = passed / total if total > 0 else 1.0
    failed = [r for r in relevant if r.status == RuleStatus.FAIL]
    detail = f"{passed}/{total} rules passed"
    if failed:
        sev_counts: Dict[str, int] = {}
        for f in failed:
            sev = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
        detail += f" ({', '.join(f'{v}x{k}' for k, v in sev_counts.items())} failed)"
    return ConfidenceSignal("rule_compliance", score >= 1.0, score, detail)


def _signal_historical(
    indicator_code: str,
    value: Optional[float],
    historical_data: Dict[str, Dict[str, float]],
    z_thresh: float = 2.5,
) -> ConfidenceSignal:
    if value is None:
        return ConfidenceSignal("historical", False, 0.0, "No current value to assess")
    hist_values: List[float] = []
    for month_vals in historical_data.values():
        v = month_vals.get(indicator_code)
        if v is not None:
            hist_values.append(v)
    if len(hist_values) < 2:
        return ConfidenceSignal("historical", True, 0.7, "Insufficient history (<2 months), neutral confidence")
    mean_h = float(np.mean(hist_values))
    std_h = float(np.std(hist_values))
    if std_h == 0:
        diff_pct = abs((value - mean_h) / mean_h * 100) if mean_h != 0 else 0
        score = 1.0 if diff_pct < 5 else 0.5
        return ConfidenceSignal("historical", score >= 0.8, score,
                                f"Value={value}, mean={mean_h:.1f}, no variation (diff {diff_pct:.1f}%)")
    z = abs((value - mean_h) / std_h)
    score = max(0.0, 1.0 - z / 3.0)
    pct_dev = ((value - mean_h) / mean_h * 100) if mean_h != 0 else 0
    return ConfidenceSignal(
        "historical", z < z_thresh, score,
        f"z={z:.2f}, {pct_dev:+.1f}% vs historical mean={mean_h:.1f} (std={std_h:.1f})",
    )


def _signal_cross_hospital(
    indicator_code: str,
    value: Optional[float],
    all_hospital_data: Dict[str, Dict[str, float]],
    current_hospital: str,
    z_thresh: float = 2.5,
) -> ConfidenceSignal:
    if value is None:
        return ConfidenceSignal("cross_hospital", False, 0.0, "No current value to assess")
    rate_info = None
    for rate_name, num_code, den_code, _ in RATE_DEFINITIONS:
        if num_code == indicator_code or den_code == indicator_code:
            rate_info = (rate_name, num_code, den_code)
            break
    if rate_info is None:
        other_vals = []
        for h_name, h_vals in all_hospital_data.items():
            if h_name == current_hospital:
                continue
            v = h_vals.get(indicator_code)
            if v is not None:
                other_vals.append(v)
        if len(other_vals) < 2:
            return ConfidenceSignal("cross_hospital", True, 0.7, "Few hospitals for comparison, neutral")
        mean_o = float(np.mean(other_vals))
        std_o = float(np.std(other_vals))
        if std_o == 0:
            return ConfidenceSignal("cross_hospital", True, 0.8, "No variation across hospitals")
        z = abs((value - mean_o) / std_o)
        score = max(0.0, 1.0 - z / 3.0)
        return ConfidenceSignal("cross_hospital", z < z_thresh, score,
                                f"z={z:.2f} vs peer mean={mean_o:.1f} (std={std_o:.1f})")
    rate_name, num_code, den_code = rate_info
    rates: Dict[str, float] = {}
    for h_name, h_vals in all_hospital_data.items():
        r = compute_rate(h_vals, num_code, den_code)
        if r is not None:
            rates[h_name] = r
    if len(rates) < 2:
        return ConfidenceSignal("cross_hospital", True, 0.7, "Insufficient hospitals for rate comparison")
    current_rate = compute_rate(
        all_hospital_data.get(current_hospital, {}), num_code, den_code
    )
    if current_rate is None:
        return ConfidenceSignal("cross_hospital", False, 0.0, "Cannot compute rate for comparison")
    rate_vals = list(rates.values())
    mean_r = float(np.mean(rate_vals))
    std_r = float(np.std(rate_vals))
    if std_r == 0:
        return ConfidenceSignal("cross_hospital", True, 0.9, f"Rate={current_rate:.1f}, no variation across hospitals")
    z = abs((current_rate - mean_r) / std_r)
    score = max(0.0, 1.0 - z / 3.0)
    return ConfidenceSignal(
        "cross_hospital", z < z_thresh, score,
        f"Rate={current_rate:.1f}, peer mean={mean_r:.1f} (std={std_r:.1f}), z={z:.2f}",
    )


def _signal_trend(
    indicator_code: str,
    value: Optional[float],
    historical_data: Dict[str, Dict[str, float]],
) -> ConfidenceSignal:
    if value is None:
        return ConfidenceSignal("trend", False, 0.0, "No current value to assess")
    sorted_months = sorted(historical_data.keys())
    hist_vals: List[float] = []
    for m in sorted_months:
        v = historical_data[m].get(indicator_code)
        if v is not None:
            hist_vals.append(v)
    if len(hist_vals) < 3:
        return ConfidenceSignal("trend", True, 0.7, "Insufficient history for trend (<3 months)")
    x = list(range(len(hist_vals)))
    x_arr = np.array(x, dtype=float)
    y_arr = np.array(hist_vals, dtype=float)
    x_mean = np.mean(x_arr)
    y_mean = np.mean(y_arr)
    ss_xy = np.sum((x_arr - x_mean) * (y_arr - y_mean))
    ss_xx = np.sum((x_arr - x_mean) ** 2)
    if ss_xx == 0:
        return ConfidenceSignal("trend", True, 0.7, "Cannot compute trend (no x variation)")
    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    projected = slope * len(hist_vals) + intercept
    std_h = float(np.std(hist_vals))
    if std_h == 0:
        diff_pct = abs((value - projected) / projected * 100) if projected != 0 else 0
        score = 1.0 if diff_pct < 5 else 0.6
        return ConfidenceSignal("trend", score >= 0.8, score,
                                f"Projected={projected:.1f}, actual={value}, diff {diff_pct:.1f}%")
    deviation = abs(value - projected)
    score = max(0.0, 1.0 - deviation / (2 * std_h))
    pct_change = ((value - hist_vals[-1]) / hist_vals[-1] * 100) if hist_vals[-1] != 0 else 0
    return ConfidenceSignal(
        "trend", score >= 0.5, score,
        f"Projected={projected:.1f}, actual={value}, {pct_change:+.1f}% vs last month",
    )


def _signal_completeness(
    indicator_code: str,
    value: Optional[float],
    values: Dict[str, float],
    indicator_children: Dict[str, List[str]],
) -> ConfidenceSignal:
    if value is None:
        return ConfidenceSignal("completeness", False, 0.0, "Indicator value is missing")
    children = indicator_children.get(indicator_code, [])
    if not children:
        return ConfidenceSignal("completeness", True, 1.0, "No child indicators to verify")
    present = sum(1 for c in children if values.get(c) is not None)
    total = len(children)
    score = present / total if total > 0 else 1.0
    missing = [c for c in children if values.get(c) is None]
    detail = f"{present}/{total} child indicators present"
    if missing:
        missing_str = ", ".join(missing[:5])
        detail += f" (missing: {missing_str}"
        if len(missing) > 5:
            detail += f" +{len(missing)-5} more"
        detail += ")"
    return ConfidenceSignal("completeness", score >= 0.8, score, detail)


def _compute_level(confidence: float, config: dict = None) -> str:
    cfg = config or {}
    high_cutoff = cfg.get("confidence_high", 80.0)
    medium_cutoff = cfg.get("confidence_medium", 50.0)
    low_cutoff = cfg.get("confidence_low", 25.0)
    if confidence >= high_cutoff:
        return "HIGH"
    if confidence >= medium_cutoff:
        return "MEDIUM"
    if confidence >= low_cutoff:
        return "LOW"
    return "CRITICAL"


def _build_recommendations(
    indicator_code: str,
    indicator_name: str,
    value: Optional[float],
    signals: List[ConfidenceSignal],
    level: str,
) -> List[str]:
    recs: List[str] = []
    if value is None:
        if level in ("CRITICAL", "LOW"):
            recs.append(f"DATA MISSING: {indicator_name} has no value reported â€” verify source register")
        return recs
    if level == "CRITICAL":
        recs.append(f"IMMEDIATE VERIFICATION REQUIRED: {indicator_name} (value={value}) has very low confidence")
    elif level == "LOW":
        recs.append(f"Verify {indicator_name} (value={value}) before using in reports")
    for s in signals:
        if not s.passed and s.score < 0.3:
            if s.factor == "historical":
                recs.append(f"Check source register: {indicator_name} deviates significantly from historical pattern")
            elif s.factor == "cross_hospital":
                recs.append(f"Cross-check with other facilities: {indicator_name} is an outlier across hospitals")
            elif s.factor == "rule_compliance":
                recs.append(f"Review data entry: {indicator_name} failed validation rules")
            elif s.factor == "trend":
                recs.append(f"Investigate sudden change: {indicator_name} breaks expected trend")
            elif s.factor == "completeness":
                recs.append(f"Complete missing sub-indicators for {indicator_name}")
    return recs


def _build_summary(
    hospital: str,
    overall: float,
    level: str,
    by_level: Dict[str, int],
    priority: List[IndicatorConfidence],
) -> str:
    parts: List[str] = []
    parts.append(f"Hospital '{hospital}' overall confidence: {overall:.1f}% ({level})")
    if by_level.get("CRITICAL", 0) > 0:
        parts.append(f"{by_level['CRITICAL']} indicator(s) at CRITICAL confidence")
    if by_level.get("LOW", 0) > 0:
        parts.append(f"{by_level['LOW']} indicator(s) at LOW confidence")
    if priority:
        names = [f"{i.indicator_name} ({i.confidence:.0f}%)" for i in priority[:3]]
        parts.append(f"Priority verification: {', '.join(names)}")
    return " | ".join(parts)


def calculate_confidence(
    hospital_name: str,
    month: str,
    values: Dict[str, float],
    rule_results: List[RuleResult],
    historical_data: Dict[str, Dict[str, float]],
    all_hospital_data: Dict[str, Dict[str, float]],
    indicator_map: Dict[str, str],
    indicator_children: Dict[str, List[str]],
    indicator_rule_map: Optional[Dict[str, List[str]]] = None,
    key_indicator_codes: Optional[List[str]] = None,
    session=None,
) -> HospitalConfidenceResult:
    global SIGNAL_WEIGHTS
    threshold_config = {}
    if session is not None:
        try:
            from app.models import ConfidenceWeights
            cw = session.query(ConfidenceWeights).first()
            if cw:
                SIGNAL_WEIGHTS = {
                    "rule_compliance": cw.rule_compliance,
                    "historical": cw.historical,
                    "cross_hospital": cw.cross_hospital,
                    "trend": cw.trend,
                    "completeness": cw.completeness,
                }
            from app.config_utils import get_config_dict
            threshold_config = get_config_dict(session, "thresholds")
        except Exception:
            pass

    if key_indicator_codes is None:
        key_indicator_codes = sorted(values.keys(), key=lambda c: (len(c), c))

    assessed: List[str] = []
    for code in values.keys():
        if code not in assessed:
            assessed.append(code)
    for code in key_indicator_codes:
        if code not in assessed:
            assessed.append(code)

    indicators: List[IndicatorConfidence] = []
    for code in assessed:
        name = indicator_map.get(code, code)
        value = values.get(code)

        signals: List[ConfidenceSignal] = []
        signals.append(_signal_rule_compliance(code, rule_results, indicator_rule_map or {}))
        z_thresh = threshold_config.get("zscore_threshold", 2.5)
        signals.append(_signal_historical(code, value, historical_data, z_thresh))
        signals.append(_signal_cross_hospital(code, value, all_hospital_data, hospital_name, z_thresh))
        signals.append(_signal_trend(code, value, historical_data))
        signals.append(_signal_completeness(code, value, values, indicator_children))

        raw = sum(s.score * SIGNAL_WEIGHTS.get(s.factor, 0) for s in signals)
        confidence = max(0, min(100, round(raw * 100, 1)))
        level = _compute_level(confidence, threshold_config)
        recs = _build_recommendations(code, name, value, signals, level)

        indicators.append(IndicatorConfidence(
            indicator_code=code,
            indicator_name=name,
            value=value,
            confidence=confidence,
            level=level,
            signals=signals,
            recommendations=recs,
        ))

    indicators.sort(key=lambda i: i.confidence)

    by_level: Dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "CRITICAL": 0}
    for ind in indicators:
        by_level[ind.level] += 1

    by_group: Dict[str, float] = {}
    for group_name, group_codes in INDICATOR_GROUPS.items():
        group_inds = [i for i in indicators if i.indicator_code in group_codes]
        if not group_inds:
            continue
        total_weight = 0.0
        weighted_sum = 0.0
        for ind in group_inds:
            w = INDICATOR_CLINICAL_WEIGHTS.get(ind.indicator_code, 1.0)
            weighted_sum += ind.confidence * w
            total_weight += w
        by_group[group_name] = (weighted_sum / total_weight) if total_weight > 0 else 0

    total_w = 0.0
    weighted_sum = 0.0
    for ind in indicators:
        w = INDICATOR_CLINICAL_WEIGHTS.get(ind.indicator_code, 1.0)
        weighted_sum += ind.confidence * w
        total_w += w
    overall = (weighted_sum / total_w) if total_w > 0 else 0
    overall_level = _compute_level(overall, threshold_config)

    priority = [i for i in indicators]

    summary = _build_summary(hospital_name, overall, overall_level, by_level, priority)

    return HospitalConfidenceResult(
        hospital=hospital_name,
        month=month,
        overall_confidence=overall,
        level=overall_level,
        indicator_count=len(indicators),
        by_level=by_level,
        by_group=by_group,
        indicators=indicators,
        priority_verify=priority,
        summary=summary,
    )
