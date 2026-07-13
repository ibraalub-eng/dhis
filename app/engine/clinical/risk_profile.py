from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class RiskMetric:
    metric_name: str
    description: str
    value: Optional[float]
    unit: str
    numerator: float
    denominator: float
    interpretation: str
    severity: str


@dataclass
class RiskProfile:
    hospital: str
    month: str
    total_deliveries: int
    metrics: List[RiskMetric] = field(default_factory=list)
    overall_risk_level: str = "low"
    key_findings: List[str] = field(default_factory=list)


def _interpret_rate(value: float, moderate_thresh: float, high_thresh: float, critical_thresh: float, higher_is_worse: bool) -> str:
    sev = _rate_severity(value, moderate_thresh, high_thresh, critical_thresh, higher_is_worse)
    if sev == "low":
        return "Acceptable level"
    elif sev == "moderate":
        return "Moderate - requires monitoring"
    elif sev == "high":
        return "High - clinical review recommended"
    elif sev == "critical":
        return "Critical - immediate action required"
    return "Unable to assess"


def _rate_severity(value: float, moderate_thresh: float, high_thresh: float, critical_thresh: float, higher_is_worse: bool) -> str:
    if value is None:
        return "unknown"
    if higher_is_worse:
        if value >= critical_thresh:
            return "critical"
        if value >= high_thresh:
            return "high"
        if value >= moderate_thresh:
            return "moderate"
        return "low"
    else:
        if value <= critical_thresh:
            return "critical"
        if value <= high_thresh:
            return "high"
        if value <= moderate_thresh:
            return "moderate"
        return "low"


def _build_key_findings(profile: RiskProfile):
    for m in profile.metrics:
        if m.severity in ("high", "critical"):
            profile.key_findings.append(f"{m.metric_name}: {m.value:.1f}{m.unit} ({m.interpretation})")
    if profile.overall_risk_level == "critical":
        profile.key_findings.insert(0, f"Overall risk profile CRITICAL for {profile.hospital}")
    elif profile.overall_risk_level == "high":
        profile.key_findings.insert(0, f"Overall risk profile HIGH for {profile.hospital}")


def compute_risk_profile(hospital: str, month: str, values: Dict[str, float]) -> RiskProfile:
    profile = RiskProfile(hospital=hospital, month=month, total_deliveries=int(values.get("2", 0) or 0))
    total = values.get("2", 0) or 0
    live_births = values.get("6", 0) or 0

    if total == 0:
        profile.overall_risk_level = "unknown"
        return profile

    high_risk = values.get("2.n", 0) or 0
    high_risk_rate = (high_risk / total) * 100
    profile.metrics.append(RiskMetric(
        metric_name="High-Risk Delivery Rate",
        description="Deliveries flagged as high-risk",
        value=high_risk_rate, unit="%",
        numerator=high_risk, denominator=total,
        interpretation=_interpret_rate(high_risk_rate, 20, 35, 50, higher_is_worse=True),
        severity=_rate_severity(high_risk_rate, 20, 35, 50, higher_is_worse=True),
    ))

    teen_codes = ["2.c", "2.d"]
    teen_sum = sum(values.get(c, 0) or 0 for c in teen_codes)
    teen_rate = (teen_sum / total) * 100
    profile.metrics.append(RiskMetric(
        metric_name="Adolescent Pregnancy Rate (10-19)",
        description="Deliveries to mothers aged 10-19",
        value=teen_rate, unit="%",
        numerator=teen_sum, denominator=total,
        interpretation=_interpret_rate(teen_rate, 10, 20, 30, higher_is_worse=True),
        severity=_rate_severity(teen_rate, 10, 20, 30, higher_is_worse=True),
    ))

    ama_codes = ["2.h", "2.i", "2.j"]
    ama_sum = sum(values.get(c, 0) or 0 for c in ama_codes)
    ama_rate = (ama_sum / total) * 100
    profile.metrics.append(RiskMetric(
        metric_name="Advanced Maternal Age Rate (35+)",
        description="Deliveries to mothers aged 35+",
        value=ama_rate, unit="%",
        numerator=ama_sum, denominator=total,
        interpretation=_interpret_rate(ama_rate, 15, 25, 35, higher_is_worse=True),
        severity=_rate_severity(ama_rate, 15, 25, 35, higher_is_worse=True),
    ))

    primigravida = values.get("2.a", 0) or 0
    primi_rate = (primigravida / total) * 100
    profile.metrics.append(RiskMetric(
        metric_name="Primigravida Rate",
        description="First-time mothers",
        value=primi_rate, unit="%",
        numerator=primigravida, denominator=total,
        interpretation=_interpret_rate(primi_rate, 25, 40, 50, higher_is_worse=False),
        severity=_rate_severity(primi_rate, 25, 40, 50, higher_is_worse=False),
    ))

    cs_total = values.get("5", 0) or 0
    cs_emergency = values.get("5.b.1", 0) or 0
    cs_emergency_rate = (cs_emergency / cs_total * 100) if cs_total > 0 else None
    if cs_emergency_rate is not None:
        profile.metrics.append(RiskMetric(
            metric_name="Emergency C/S Proportion",
            description="Emergency C-sections as % of all C-sections",
            value=cs_emergency_rate, unit="%",
            numerator=cs_emergency, denominator=cs_total,
            interpretation=_interpret_rate(cs_emergency_rate, 50, 70, 85, higher_is_worse=True),
            severity=_rate_severity(cs_emergency_rate, 50, 70, 85, higher_is_worse=True),
        ))

    cs_primary = values.get("5.c", 0) or 0
    cs_primary_rate = (cs_primary / cs_total * 100) if cs_total > 0 else None
    if cs_primary_rate is not None:
        profile.metrics.append(RiskMetric(
            metric_name="Primary C/S Proportion",
            description="First-time C-sections as % of all C-sections",
            value=cs_primary_rate, unit="%",
            numerator=cs_primary, denominator=cs_total,
            interpretation=_interpret_rate(cs_primary_rate, 40, 60, 75, higher_is_worse=False),
            severity=_rate_severity(cs_primary_rate, 40, 60, 75, higher_is_worse=False),
        ))

    in_facility = values.get("2.k", 0) or 0
    out_facility = values.get("2.l", 0) or 0
    facility_rate = (in_facility / total * 100) if total > 0 else 0
    profile.metrics.append(RiskMetric(
        metric_name="In-Facility Delivery Rate",
        description="Deliveries occurring in health facility",
        value=facility_rate, unit="%",
        numerator=in_facility, denominator=total,
        interpretation=_interpret_rate(facility_rate, 80, 60, 40, higher_is_worse=False),
        severity=_rate_severity(facility_rate, 80, 60, 40, higher_is_worse=False),
    ))

    preterm = values.get("6.f", 0) or 0
    lbw = values.get("6.g", 0) or 0
    preterm_rate = (preterm / live_births * 100) if live_births > 0 else 0
    lbw_rate = (lbw / live_births * 100) if live_births > 0 else 0
    profile.metrics.append(RiskMetric(
        metric_name="Preterm Birth Rate",
        description="Live births before 37 weeks",
        value=preterm_rate, unit="%",
        numerator=preterm, denominator=live_births,
        interpretation=_interpret_rate(preterm_rate, 10, 15, 20, higher_is_worse=True),
        severity=_rate_severity(preterm_rate, 10, 15, 20, higher_is_worse=True),
    ))
    profile.metrics.append(RiskMetric(
        metric_name="Low Birth Weight Rate",
        description="Live births <2500g",
        value=lbw_rate, unit="%",
        numerator=lbw, denominator=live_births,
        interpretation=_interpret_rate(lbw_rate, 10, 15, 20, higher_is_worse=True),
        severity=_rate_severity(lbw_rate, 10, 15, 20, higher_is_worse=True),
    ))

    stillbirth = values.get("7", 0) or 0
    fresh_sb = values.get("7.a", 0) or 0
    macerated_sb = values.get("7.b", 0) or 0
    if stillbirth > 0 and fresh_sb > 0:
        fresh_proportion = (fresh_sb / stillbirth) * 100
        profile.metrics.append(RiskMetric(
            metric_name="Fresh Stillbirth Proportion",
            description="Fresh stillbirths as % of all stillbirths (intrapartum deaths)",
            value=fresh_proportion, unit="%",
            numerator=fresh_sb, denominator=stillbirth,
            interpretation=_interpret_rate(fresh_proportion, 30, 50, 70, higher_is_worse=True),
            severity=_rate_severity(fresh_proportion, 30, 50, 70, higher_is_worse=True),
        ))

    nd_total = values.get("17", 0) or 0
    if nd_total > 0:
        nd_preterm = values.get("17.c", 0) or 0
        nd_asphyxia = values.get("17.d", 0) or 0
        nd_sepsis = values.get("17.f", 0) or 0
        nd_asphyxia_rate = (nd_asphyxia / nd_total * 100) if nd_total > 0 else 0
        profile.metrics.append(RiskMetric(
            metric_name="Birth Asphyxia % of Neonatal Deaths",
            description="Neonatal deaths due to birth asphyxia",
            value=nd_asphyxia_rate, unit="%",
            numerator=nd_asphyxia, denominator=nd_total,
            interpretation=_interpret_rate(nd_asphyxia_rate, 20, 30, 40, higher_is_worse=True),
            severity=_rate_severity(nd_asphyxia_rate, 20, 30, 40, higher_is_worse=True),
        ))

    severity_scores = {
        "low": 0, "moderate": 1, "high": 2, "critical": 3, "unknown": 0
    }
    avg_severity = 0
    count = 0
    for m in profile.metrics:
        s = severity_scores.get(m.severity, 0)
        avg_severity += s
        count += 1
    avg_severity = avg_severity / count if count > 0 else 0

    if avg_severity >= 2.5:
        profile.overall_risk_level = "critical"
    elif avg_severity >= 1.5:
        profile.overall_risk_level = "high"
    elif avg_severity >= 0.5:
        profile.overall_risk_level = "moderate"
    else:
        profile.overall_risk_level = "low"

    _build_key_findings(profile)
    return profile


def correlate_risk_outcomes(values: Dict[str, float], all_hospital_data: Dict[str, Dict[str, float]]) -> List[Dict]:
    findings = []
    total = values.get("2", 0) or 0
    if total == 0:
        return findings

    high_risk = values.get("2.n", 0) or 0
    high_risk_rate = (high_risk / total) * 100

    other_hospitals = {h: v for h, v in all_hospital_data.items()}
    if len(other_hospitals) >= 2:
        risk_rates = []
        preterm_rates = []
        for h, v in other_hospitals.items():
            ht = v.get("2", 0) or 0
            if ht > 0:
                hr = v.get("2.n", 0) or 0
                risk_rates.append((hr / ht) * 100)
                lb = v.get("6", 0) or 0
                pt = v.get("6.f", 0) or 0
                preterm_rates.append((pt / lb * 100) if lb > 0 else 0)

        if risk_rates and preterm_rates:
            avg_risk = sum(risk_rates) / len(risk_rates)
            avg_preterm = sum(preterm_rates) / len(preterm_rates)
            if high_risk_rate > avg_risk * 1.2:
                findings.append({
                    "finding": "High-risk proportion significantly above peer average",
                    "detail": f"{high_risk_rate:.1f}% vs peer avg {avg_risk:.1f}%",
                    "severity": "high" if high_risk_rate > avg_risk * 1.5 else "moderate",
                })

    return findings
