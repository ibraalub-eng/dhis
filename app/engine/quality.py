# =============================================================================
# engine/quality.py -- Merged rules + quality_score module
# =============================================================================

# Source: rules.py

import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum
from sqlalchemy.orm import Session

_RULES_CONFIG = {
    "eq_tolerance": 0.01,
    "cs_rate_threshold": 80.0,
    "nvd_rate_threshold": 10.0,
    "zscore_threshold": 2.5,
    "month_over_factor": 2.0,
    "month_under_factor": 0.5,
    "maternal_over_factor": 4.0,
    "neonatal_over_factor": 4.0,
}


def set_rules_config(config: dict):
    _RULES_CONFIG.update(config)


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RuleType(str, Enum):
    LOGIC = "LOGIC"
    CLINICAL = "CLINICAL"
    BENCHMARK = "BENCHMARK"
    DATA_QUALITY = "DATA_QUALITY"


class RuleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass
class RuleResult:
    rule_code: str
    description: str
    status: RuleStatus
    severity: Severity
    rule_type: RuleType
    details: str = ""


@dataclass
class ValidationContext:
    values: Dict[str, float]
    hospital_name: str
    month: str
    all_hospital_data: Optional[Dict[str, Dict[str, float]]] = None
    historical_data: Optional[Dict[str, Dict[str, float]]] = None
    disabled_codes: set = field(default_factory=set)


RULE_REF_CODES = {
    "R001": ["2", "3", "4", "5"],
    "R002": ["2", "2.a", "2.b"],
    "R003": ["2", "2.c", "2.d", "2.e", "2.f", "2.g", "2.h", "2.i", "2.j"],
    "R004": ["2", "2.k", "2.l"],
    "R005": ["2", "2.m", "2.n"],
    "R006": ["5", "5.b.1", "5.b.2"],
    "R007": ["5", "5.c", "5.d"],
    "R008": ["5.b.1", "5"],
    "R009": ["5.b.2", "5"],
    "R010": ["5.d", "5"],
    "R011": ["6", "6.a", "6.b", "6.c"],
    "R012": ["6.d", "6"],
    "R013": ["6.e", "6"],
    "R014": ["6.f", "6"],
    "R015": ["6.g", "6"],
    "R016": ["7", "7.a", "7.b"],
    "R017": ["8", "8.a", "8.b"],
    "R018": ["7", "2"],
    "R019": ["8", "2"],
    "R020": ["9", "6"],
    "R021": ["10.a.1", "10.a"],
    "R022": ["10.a.2", "10.a"],
    "R023": ["10.a.3", "10.a"],
    "R024": ["10.a.1", "10.a.1.1", "10.a.1.2"],
    "R025": ["10.a.2", "10.a.2.1", "10.a.2.2"],
    "R026": ["10.a.3", "10.a.3.1", "10.a.3.2", "10.a.3.3"],
    "R027": ["10.e.1", "10.e"],
    "R028": ["10.e.2", "10.e"],
    "R029": ["10.e.3", "10.e"],
    "R030": ["10.e", "10.e.1", "10.e.2", "10.e.3"],
    "R031": ["10.a", "10"],
    "R032": ["10.e", "10"],
    "R033": ["10.f", "10"],
    "R034": ["10.m", "10"],
    "R035": ["10.d", "10"],
    "R036": ["10.c", "10"],
    "R037": ["10.b", "10"],
    "R038": ["10.l", "10"],
    "R039": ["10.h", "10"],
    "R040": ["10.i", "10"],
    "R041": ["5", "2"],
    "R042": ["3", "2"],
    "R043": ["6.f", "6"],
    "R044": ["6.g", "6"],
    "R045": ["11", "6"],
    "R046": ["17", "6"],
    "R047": ["7", "2"],
    "R048": ["16", "6"],
    "R049": ["10", "2"],
    "R050": ["10.a", "2"],
    "R051": ["2"],
    "R052": ["2"],
    "R053": ["6"],
    "R054": ["11"],
    "R055": ["17"],
    "R056": ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"],
    "R057": ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"],
    "R058": ["2"],
    "R059": ["6"],
    "R060": ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"],
}


def _v(ctx: ValidationContext, code: str) -> Optional[float]:
    return ctx.values.get(code)


def _vs(ctx: ValidationContext, codes: List[str]) -> float:
    total = 0.0
    for c in codes:
        val = ctx.values.get(c)
        if val is not None:
            total += val
    return total


def _has_any(ctx: ValidationContext, codes: List[str]) -> bool:
    return any(ctx.values.get(c) is not None for c in codes)


def _rate(ctx: ValidationContext, num_code: str, den_code: str) -> Optional[float]:
    num = _v(ctx, num_code)
    den = _v(ctx, den_code)
    if num is None or den is None or den == 0:
        return None
    return (num / den) * 100


def _ge(parent: str, children: List[str], code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    pv = _v(ctx, parent)
    cs = _vs(ctx, children)
    if pv is None and cs == 0:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "No data available")
    if pv is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Parent value missing")
    if cs > pv:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{parent}={pv} but children sum={cs}")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{parent}={pv} >= children sum={cs}")


def _eq(parent: str, children: List[str], code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    pv = _v(ctx, parent)
    cs = _vs(ctx, children)
    if pv is None and cs == 0:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "No data available")
    if pv is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Parent value missing")
    if not _has_any(ctx, children):
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "No child data to compare")
    if abs(pv - cs) > _RULES_CONFIG["eq_tolerance"]:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{parent}={pv} but children sum={cs}, diff={abs(pv - cs):.2f}")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{parent}={pv} == children sum={cs}")


def _le(child: str, parent: str, code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    cv = _v(ctx, child)
    pv = _v(ctx, parent)
    if cv is None or pv is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Missing data")
    if cv > pv:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"{child}={cv} > {parent}={pv}")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"{child}={cv} <= {parent}={pv}")


def _month_over(month_code: str, prev_data: Optional[Dict[str, float]], factor: float, code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    cur = _v(ctx, month_code)
    if cur is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "No current data")
    if prev_data is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "No previous month data")
    prev = prev_data.get(month_code)
    if prev is None or prev == 0:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "Previous value missing or zero")
    change_pct = ((cur - prev) / prev) * 100
    if change_pct > factor * 100:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.DATA_QUALITY, f"{cur} is {change_pct:+.0f}% vs previous {prev} (>{factor*100:.0f}%)")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, f"Change {change_pct:+.0f}% (OK)")


def _month_under(month_code: str, prev_data: Optional[Dict[str, float]], factor: float, code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    cur = _v(ctx, month_code)
    if cur is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "No current data")
    if prev_data is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "No previous month data")
    prev = prev_data.get(month_code)
    if prev is None or prev == 0:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "Previous value missing or zero")
    change_pct = ((prev - cur) / prev) * 100
    if change_pct > factor * 100:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.DATA_QUALITY, f"{cur} is {-(change_pct):.0f}% drop vs previous {prev} (<{factor*100:.0f}%)")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, f"Change {((cur-prev)/prev)*100:+.0f}% (OK)")


def _neg_check(codes: List[str], code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    for c in codes:
        val = _v(ctx, c)
        if val is not None and val < 0:
            return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.DATA_QUALITY, f"{c}={val} is negative")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, "All values non-negative")


def _decimal_check(codes: List[str], code: str, desc: str, ctx: ValidationContext) -> RuleResult:
    for c in codes:
        val = _v(ctx, c)
        if val is not None and val != int(val):
            return RuleResult(code, desc, RuleStatus.FAIL, Severity.LOW, RuleType.DATA_QUALITY, f"{c}={val} is decimal (counts should be integers)")
    return RuleResult(code, desc, RuleStatus.PASS, Severity.LOW, RuleType.DATA_QUALITY, "All values are integers")


def _missing(indicator_code: str, code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    val = _v(ctx, indicator_code)
    if val is None:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.DATA_QUALITY, f"Missing value for indicator {indicator_code}")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.DATA_QUALITY, f"{indicator_code}={val}")


def _benchmark_rate(num_code: str, den_code: str, threshold: float, code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    rate = _rate(ctx, num_code, den_code)
    if rate is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.BENCHMARK, "Missing data for rate calculation")
    if rate > threshold:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.BENCHMARK, f"Rate={rate:.1f}% exceeds threshold {threshold:.1f}%")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.BENCHMARK, f"Rate={rate:.1f}% (<= {threshold:.1f}%)")


def _cross_hospital_rate(num_code: str, den_code: str, z_thresh: float, code: str, desc: str, sev: Severity, ctx: ValidationContext) -> RuleResult:
    import numpy as np
    if ctx.all_hospital_data is None or len(ctx.all_hospital_data) < 2:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.BENCHMARK, "Not enough hospitals for comparison")
    rates = {}
    for name, vals in ctx.all_hospital_data.items():
        r = _rate(ValidationContext(values=vals, hospital_name=name, month=ctx.month), num_code, den_code)
        if r is not None:
            rates[name] = r
    cur_rate = _rate(ctx, num_code, den_code)
    if cur_rate is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.BENCHMARK, "Missing data for rate")
    if len(rates) < 2:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.BENCHMARK, "Not enough hospital data for comparison")
    vals_list = list(rates.values())
    mean_r = float(np.mean(vals_list))
    std_r = float(np.std(vals_list))
    if std_r == 0:
        return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.BENCHMARK, f"Rate={cur_rate:.1f}%, no variation across hospitals")
    z = (cur_rate - mean_r) / std_r
    if abs(z) > z_thresh:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, RuleType.BENCHMARK, f"Rate={cur_rate:.1f}%, mean={mean_r:.1f}%, z={z:.2f} (outlier)")
    return RuleResult(code, desc, RuleStatus.PASS, sev, RuleType.BENCHMARK, f"Rate={cur_rate:.1f}%, z={z:.2f} (OK)")


def run_all_rules(ctx: ValidationContext) -> List[RuleResult]:
    results = []
    for rule_func in ALL_RULES:
        result = rule_func(ctx)
        ref_codes = RULE_REF_CODES.get(result.rule_code)
        if ref_codes is not None and ctx.disabled_codes:
            all_disabled = True
            for c in ref_codes:
                if c.strip() not in ctx.disabled_codes:
                    all_disabled = False
                    break
            if all_disabled:
                continue
        results.append(result)
    return results


ALL_RULES = []


def _build_rules():

    # =============================================
    # GROUP 1: Basic Logic Rules (R001-R020)
    # =============================================

    # Deliveries
    ALL_RULES.append(lambda ctx: _ge("2", ["3", "4", "5"], "R001", "Total Deliveries >= NVD + Assisted + C-sections", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _eq("2", ["2.a", "2.b"], "R002", "Primigravida + Multigravida ≈ Total Deliveries", Severity.MEDIUM, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _eq("2", ["2.c", "2.d", "2.e", "2.f", "2.g", "2.h", "2.i", "2.j"], "R003", "Age group sum ≈ Total Deliveries", Severity.LOW, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _eq("2", ["2.k", "2.l"], "R004", "In-facility + Out-of-facility ≈ Total Deliveries", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _eq("2", ["2.m", "2.n"], "R005", "Low Risk + High Risk ≈ Total Deliveries", Severity.MEDIUM, RuleType.LOGIC, ctx))

    # C-sections
    ALL_RULES.append(lambda ctx: _eq("5", ["5.b.1", "5.b.2"], "R006", "Emergency + Planned C/S = Total C-sections", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _eq("5", ["5.c", "5.d"], "R007", "Primary + Repeat C/S = Total C-sections", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("5.b.1", "5", "R008", "Emergency C/S <= Total C-sections", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("5.b.2", "5", "R009", "Planned C/S <= Total C-sections", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("5.d", "5", "R010", "Repeat C/S <= Total C-sections", Severity.HIGH, RuleType.LOGIC, ctx))

    # Live births
    ALL_RULES.append(lambda ctx: _eq("6", ["6.a", "6.b", "6.c"], "R011", "Male + Female + Unknown sex = Live Births", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("6.d", "6", "R012", "Multiple Pregnancy <= Live Births", Severity.MEDIUM, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("6.e", "6", "R013", "Twins/Multiples count <= Live Births", Severity.MEDIUM, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("6.f", "6", "R014", "Preterm Births <= Live Births", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("6.g", "6", "R015", "Low Birth Weight <= Live Births", Severity.HIGH, RuleType.LOGIC, ctx))

    # Stillbirths & Abortions
    ALL_RULES.append(lambda ctx: _eq("7", ["7.a", "7.b"], "R016", "Fresh + Macerated Stillbirth = Fetal Deaths >24w", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _eq("8", ["8.a", "8.b"], "R017", "First + Second Trimester = Abortions", Severity.MEDIUM, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("7", "2", "R018", "Fetal Deaths <= Total Deliveries", Severity.HIGH, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("8", "2", "R019", "Abortions <= Total Deliveries", Severity.MEDIUM, RuleType.LOGIC, ctx))
    ALL_RULES.append(lambda ctx: _le("9", "6", "R020", "Congenital Anomalies <= Live Births", Severity.MEDIUM, RuleType.LOGIC, ctx))

    # =============================================
    # GROUP 2: Clinical Consistency Rules (R021-R040)
    # =============================================

    # Hemorrhage
    ALL_RULES.append(lambda ctx: _le("10.a.1", "10.a", "R021", "Postpartum Hemorrhage <= Hemorrhage", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.a.2", "10.a", "R022", "Antepartum Hemorrhage <= Hemorrhage", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.a.3", "10.a", "R023", "Early Pregnancy Hemorrhage <= Hemorrhage", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _ge("10.a.1", ["10.a.1.1", "10.a.1.2"], "R024", "Primary + Secondary Severe <= Postpartum Hemorrhage", Severity.MEDIUM, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _ge("10.a.2", ["10.a.2.1", "10.a.2.2"], "R025", "Placental Abruption + Previa <= Antepartum Hemorrhage", Severity.MEDIUM, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _ge("10.a.3", ["10.a.3.1", "10.a.3.2", "10.a.3.3"], "R026", "Ectopic + Abortion Bleeding + Molar <= Early Pregnancy Hemorrhage", Severity.MEDIUM, RuleType.CLINICAL, ctx))

    # Hypertensive disorders
    ALL_RULES.append(lambda ctx: _le("10.e.1", "10.e", "R027", "Severe Preeclampsia <= Hypertensive Disorders", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.e.2", "10.e", "R028", "HELLP Syndrome <= Hypertensive Disorders", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.e.3", "10.e", "R029", "Eclampsia <= Hypertensive Disorders", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _ge("10.e", ["10.e.1", "10.e.2", "10.e.3"], "R030", "Preeclampsia + HELLP + Eclampsia <= Hypertensive Disorders", Severity.HIGH, RuleType.CLINICAL, ctx))

    # SMM sub-conditions
    ALL_RULES.append(lambda ctx: _le("10.a", "10", "R031", "Hemorrhage <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.e", "10", "R032", "Hypertensive Disorders <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.f", "10", "R033", "Sepsis <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.m", "10", "R034", "Unplanned ICU Admission <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.d", "10", "R035", "Hysterectomy <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.c", "10", "R036", "Relaparotomy <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.b", "10", "R037", "Uterine Rupture <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.l", "10", "R038", "Anaesthesia Complications <= SMM", Severity.MEDIUM, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.h", "10", "R039", "Cardiac ICU Admission <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))
    ALL_RULES.append(lambda ctx: _le("10.i", "10", "R040", "Renal Failure/Dialysis <= SMM", Severity.HIGH, RuleType.CLINICAL, ctx))

    # =============================================
    # GROUP 3: Statistical & Benchmark Rules (R041-R050)
    # =============================================

    ALL_RULES.append(lambda ctx: _benchmark_rate("5", "2", _RULES_CONFIG["cs_rate_threshold"], "R041", "C-section rate > 80%", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _rate_low("3", "2", _RULES_CONFIG["nvd_rate_threshold"], "R042", "Normal Vaginal Delivery Rate < 10%", Severity.HIGH, RuleType.BENCHMARK, ctx))
    ALL_RULES.append(lambda ctx: _cross_hospital_rate("6.f", "6", _RULES_CONFIG["zscore_threshold"], "R043", "Preterm Birth Rate outlier across hospitals", Severity.MEDIUM, ctx))
    ALL_RULES.append(lambda ctx: _cross_hospital_rate("6.g", "6", _RULES_CONFIG["zscore_threshold"], "R044", "Low Birth Weight Rate outlier across hospitals", Severity.MEDIUM, ctx))
    ALL_RULES.append(lambda ctx: _cross_hospital_rate("11", "6", _RULES_CONFIG["zscore_threshold"], "R045", "Maternal Mortality Ratio outlier across hospitals", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _cross_hospital_rate("17", "6", _RULES_CONFIG["zscore_threshold"], "R046", "Neonatal Mortality Rate outlier across hospitals", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _cross_hospital_rate("7", "2", _RULES_CONFIG["zscore_threshold"], "R047", "Stillbirth Rate outlier across hospitals", Severity.MEDIUM, ctx))
    ALL_RULES.append(lambda ctx: _cross_hospital_rate("16", "6", _RULES_CONFIG["zscore_threshold"], "R048", "NICU Admission Rate outlier across hospitals", Severity.MEDIUM, ctx))
    ALL_RULES.append(lambda ctx: _cross_hospital_rate("10", "2", _RULES_CONFIG["zscore_threshold"], "R049", "SMM Rate outlier across hospitals", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _cross_hospital_rate("10.a", "2", _RULES_CONFIG["zscore_threshold"], "R050", "Hemorrhage Rate outlier across hospitals", Severity.HIGH, ctx))

    # =============================================
    # GROUP 4: Trend & Data Quality Rules (R051-R060)
    # =============================================

    ALL_RULES.append(lambda ctx: _month_over("2", ctx.historical_data, _RULES_CONFIG["month_over_factor"], "R051", "Deliveries > 2x previous month", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _month_under("2", ctx.historical_data, _RULES_CONFIG["month_under_factor"], "R052", "Deliveries < 50% of previous month", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _month_over("6", ctx.historical_data, _RULES_CONFIG["month_over_factor"], "R053", "Live Births > 2x previous month", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _month_over("11", ctx.historical_data, _RULES_CONFIG["maternal_over_factor"], "R054", "Maternal Deaths increased by >300%", Severity.CRITICAL, ctx))
    ALL_RULES.append(lambda ctx: _month_over("17", ctx.historical_data, _RULES_CONFIG["neonatal_over_factor"], "R055", "Neonatal Deaths increased by >300%", Severity.CRITICAL, ctx))

    KEY_INDICATORS = ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]
    ALL_RULES.append(lambda ctx: _neg_check(KEY_INDICATORS, "R056", "Negative indicator value found", Severity.HIGH, ctx))

    ALL_RULES.append(lambda ctx: _decimal_check(["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"], "R057", "Decimal value found for count indicator", ctx))

    ALL_RULES.append(lambda ctx: _missing("2", "R058", "Missing Total Deliveries", Severity.HIGH, ctx))
    ALL_RULES.append(lambda ctx: _missing("6", "R059", "Missing Live Births", Severity.HIGH, ctx))

    ALL_RULES.append(lambda ctx: _all_zero_check(ctx, "R060", "All indicators are zero for a working facility"))


def _rate_low(num_code: str, den_code: str, threshold: float, code: str, desc: str, sev: Severity, rtype: RuleType, ctx: ValidationContext) -> RuleResult:
    rate = _rate(ctx, num_code, den_code)
    if rate is None:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, "Missing data for rate calculation")
    if rate < threshold:
        return RuleResult(code, desc, RuleStatus.FAIL, sev, rtype, f"Rate={rate:.1f}% is below {threshold:.1f}%")
    return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"Rate={rate:.1f}% (>= {threshold:.1f}%)")


def _all_zero_check(ctx: ValidationContext, code: str, desc: str) -> RuleResult:
    key_codes = ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]
    all_zero = True
    has_data = False
    for c in key_codes:
        val = _v(ctx, c)
        if val is not None:
            has_data = True
            if val != 0:
                all_zero = False
                break
    if not has_data:
        return RuleResult(code, desc, RuleStatus.PASS, Severity.CRITICAL, RuleType.DATA_QUALITY, "No indicator data available")
    if all_zero:
        return RuleResult(code, desc, RuleStatus.FAIL, Severity.CRITICAL, RuleType.DATA_QUALITY, "All key indicators are zero - facility may be non-operational or data missing")
    return RuleResult(code, desc, RuleStatus.PASS, Severity.CRITICAL, RuleType.DATA_QUALITY, "Facility has non-zero indicator data")


_build_rules()


def load_rules_from_db(session: Session) -> list:
    from app.models import Rule
    return session.query(Rule).filter(Rule.enabled == True).order_by(Rule.sort_order, Rule.code).all()


def _get_rule_ref_codes_from_expr(expr: str, params: dict) -> list:
    if expr in ("ge", "eq"):
        codes = [params.get("parent")]
        codes.extend(params.get("children", []))
        return [c for c in codes if c]
    if expr in ("le", "le_sum"):
        return [params.get("child"), params.get("parent")] if params.get("parent") else [params.get("child")]
    if expr in ("benchmark_rate", "benchmark_low_rate", "cross_hospital_rate"):
        return [params.get("num_code"), params.get("den_code")]
    if expr in ("month_over", "month_under", "missing"):
        return [params.get("code")]
    if expr in ("neg_check", "decimal_check"):
        return params.get("codes", [])
    if expr == "all_zero":
        return ["2", "3", "4", "5", "6", "7", "8", "10", "11", "16", "17"]
    return []


def _all_codes_disabled(ctx: ValidationContext, codes: list) -> bool:
    if not codes or not ctx.disabled_codes:
        return False
    for c in codes:
        if c not in ctx.disabled_codes:
            return False
    return True


def dispatch_rule(rule, ctx: ValidationContext) -> Optional[RuleResult]:
    params = json.loads(rule.params) if isinstance(rule.params, str) else (rule.params or {})
    code = rule.code
    desc = rule.name
    sev = Severity(rule.severity)
    rtype = RuleType(rule.rule_type)
    expr = rule.expression_type

    ref_codes = _get_rule_ref_codes_from_expr(expr, params)
    if _all_codes_disabled(ctx, ref_codes):
        return None

    if expr == "ge":
        return _ge(params["parent"], params["children"], code, desc, sev, rtype, ctx)
    elif expr == "eq":
        return _eq(params["parent"], params["children"], code, desc, sev, rtype, ctx)
    elif expr == "le":
        return _le(params["child"], params["parent"], code, desc, sev, rtype, ctx)
    elif expr == "le_sum":
        return _ge(params["child"], params["children"], code, desc, sev, rtype, ctx)
    elif expr == "benchmark_rate":
        return _benchmark_rate(params["num_code"], params["den_code"], params["threshold"], code, desc, sev, ctx)
    elif expr == "benchmark_low_rate":
        return _rate_low(params["num_code"], params["den_code"], params["threshold"], code, desc, sev, rtype, ctx)
    elif expr == "cross_hospital_rate":
        return _cross_hospital_rate(params["num_code"], params["den_code"], params["z_threshold"], code, desc, sev, ctx)
    elif expr == "month_over":
        return _month_over(params["code"], ctx.historical_data, params["factor"], code, desc, sev, ctx)
    elif expr == "month_under":
        return _month_under(params["code"], ctx.historical_data, params["factor"], code, desc, sev, ctx)
    elif expr == "neg_check":
        return _neg_check(params["codes"], code, desc, sev, ctx)
    elif expr == "decimal_check":
        return _decimal_check(params["codes"], code, desc, ctx)
    elif expr == "missing":
        return _missing(params["code"], code, desc, sev, ctx)
    elif expr == "all_zero":
        return _all_zero_check(ctx, code, desc)
    else:
        return RuleResult(code, desc, RuleStatus.PASS, sev, rtype, f"Unknown expression type: {expr}")


def run_rules_from_db(session: Session, ctx: ValidationContext) -> List[RuleResult]:
    results = []
    db_rules = load_rules_from_db(session)
    for rule in db_rules:
        try:
            result = dispatch_rule(rule, ctx)
            if result is not None:
                results.append(result)
        except Exception as e:
            results.append(RuleResult(rule.code, rule.name, RuleStatus.PASS, Severity(rule.severity), RuleType(rule.rule_type), f"Execution error: {e}"))
    return results


RULE_CATALOG = [
    {"code": "R001", "name": "Total Deliveries >= NVD + Assisted + C-sections", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R002", "name": "Primigravida + Multigravida ≈ Total Deliveries", "type": "LOGIC", "severity": "MEDIUM"},
    {"code": "R003", "name": "Age group sum ≈ Total Deliveries", "type": "LOGIC", "severity": "LOW"},
    {"code": "R004", "name": "In-facility + Out-of-facility ≈ Total Deliveries", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R005", "name": "Low Risk + High Risk ≈ Total Deliveries", "type": "LOGIC", "severity": "MEDIUM"},
    {"code": "R006", "name": "Emergency + Planned C/S = Total C-sections", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R007", "name": "Primary + Repeat C/S = Total C-sections", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R008", "name": "Emergency C/S <= Total C-sections", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R009", "name": "Planned C/S <= Total C-sections", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R010", "name": "Repeat C/S <= Total C-sections", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R011", "name": "Male + Female + Unknown = Live Births", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R012", "name": "Multiple Pregnancy <= Live Births", "type": "LOGIC", "severity": "MEDIUM"},
    {"code": "R013", "name": "Twins/Multiples count <= Live Births", "type": "LOGIC", "severity": "MEDIUM"},
    {"code": "R014", "name": "Preterm Births <= Live Births", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R015", "name": "Low Birth Weight <= Live Births", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R016", "name": "Fresh + Macerated Stillbirth = Fetal Deaths", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R017", "name": "1st + 2nd Trimester = Abortions", "type": "LOGIC", "severity": "MEDIUM"},
    {"code": "R018", "name": "Fetal Deaths <= Total Deliveries", "type": "LOGIC", "severity": "HIGH"},
    {"code": "R019", "name": "Abortions <= Total Deliveries", "type": "LOGIC", "severity": "MEDIUM"},
    {"code": "R020", "name": "Congenital Anomalies <= Live Births", "type": "LOGIC", "severity": "MEDIUM"},
    {"code": "R021", "name": "Postpartum Hemorrhage <= Hemorrhage", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R022", "name": "Antepartum Hemorrhage <= Hemorrhage", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R023", "name": "Early Pregnancy Hemorrhage <= Hemorrhage", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R024", "name": "Primary + Secondary Severe <= PPH", "type": "CLINICAL", "severity": "MEDIUM"},
    {"code": "R025", "name": "Placental Abruption + Previa <= APH", "type": "CLINICAL", "severity": "MEDIUM"},
    {"code": "R026", "name": "Ectopic + Abortion Bleeding + Molar <= EPH", "type": "CLINICAL", "severity": "MEDIUM"},
    {"code": "R027", "name": "Severe Preeclampsia <= Hypertensive Disorders", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R028", "name": "HELLP Syndrome <= Hypertensive Disorders", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R029", "name": "Eclampsia <= Hypertensive Disorders", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R030", "name": "Preeclampsia + HELLP + Eclampsia <= Hypertensive Disorders", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R031", "name": "Hemorrhage <= SMM", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R032", "name": "Hypertensive Disorders <= SMM", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R033", "name": "Sepsis <= SMM", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R034", "name": "Unplanned ICU Admission <= SMM", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R035", "name": "Hysterectomy <= SMM", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R036", "name": "Relaparotomy <= SMM", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R037", "name": "Uterine Rupture <= SMM", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R038", "name": "Anaesthesia Complications <= SMM", "type": "CLINICAL", "severity": "MEDIUM"},
    {"code": "R039", "name": "Cardiac ICU Admission <= SMM", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R040", "name": "Renal Failure/Dialysis <= SMM", "type": "CLINICAL", "severity": "HIGH"},
    {"code": "R041", "name": "C-Section Rate > 80%", "type": "BENCHMARK", "severity": "HIGH"},
    {"code": "R042", "name": "NVD Rate < 10%", "type": "BENCHMARK", "severity": "HIGH"},
    {"code": "R043", "name": "Preterm Birth Rate outlier", "type": "BENCHMARK", "severity": "MEDIUM"},
    {"code": "R044", "name": "Low Birth Weight Rate outlier", "type": "BENCHMARK", "severity": "MEDIUM"},
    {"code": "R045", "name": "Maternal Mortality Ratio outlier", "type": "BENCHMARK", "severity": "HIGH"},
    {"code": "R046", "name": "Neonatal Mortality Rate outlier", "type": "BENCHMARK", "severity": "HIGH"},
    {"code": "R047", "name": "Stillbirth Rate outlier", "type": "BENCHMARK", "severity": "MEDIUM"},
    {"code": "R048", "name": "NICU Admission Rate outlier", "type": "BENCHMARK", "severity": "MEDIUM"},
    {"code": "R049", "name": "SMM Rate outlier", "type": "BENCHMARK", "severity": "HIGH"},
    {"code": "R050", "name": "Hemorrhage Rate outlier", "type": "BENCHMARK", "severity": "HIGH"},
    {"code": "R051", "name": "Deliveries > 2x previous month", "type": "DATA_QUALITY", "severity": "HIGH"},
    {"code": "R052", "name": "Deliveries < 50% of previous month", "type": "DATA_QUALITY", "severity": "HIGH"},
    {"code": "R053", "name": "Live Births > 2x previous month", "type": "DATA_QUALITY", "severity": "HIGH"},
    {"code": "R054", "name": "Maternal Deaths increased >300%", "type": "DATA_QUALITY", "severity": "CRITICAL"},
    {"code": "R055", "name": "Neonatal Deaths increased >300%", "type": "DATA_QUALITY", "severity": "CRITICAL"},
    {"code": "R056", "name": "Negative indicator value", "type": "DATA_QUALITY", "severity": "HIGH"},
    {"code": "R057", "name": "Decimal value for count indicator", "type": "DATA_QUALITY", "severity": "LOW"},
    {"code": "R058", "name": "Missing Total Deliveries", "type": "DATA_QUALITY", "severity": "HIGH"},
    {"code": "R059", "name": "Missing Live Births", "type": "DATA_QUALITY", "severity": "HIGH"},
    {"code": "R060", "name": "All indicators zero (possible non-operational facility)", "type": "DATA_QUALITY", "severity": "CRITICAL"},
]


from typing import List, Dict, Tuple, Optional


def calculate_quality_score(
    rule_results: List[RuleResult],
    values: Dict[str, float],
    anomaly_results: list,
    active_indicator_count: int,
    config: Optional[Dict[str, float]] = None,
) -> Dict:
    cfg = config or {}
    w_rc = cfg.get("quality_rule_compliance", 0.35)
    w_cp = cfg.get("quality_completeness", 0.25)
    w_co = cfg.get("quality_consistency", 0.25)
    w_op = cfg.get("quality_outlier_penalty", 0.15)

    rule_compliance = _calc_rule_compliance(rule_results)
    completeness = _calc_completeness(values, active_indicator_count)
    consistency = _calc_consistency(rule_results, cfg)
    outlier_penalty = _calc_outlier_penalty(anomaly_results, cfg)

    raw_score = (
        rule_compliance * w_rc
        + completeness * w_cp
        + consistency * w_co
        + (1.0 - outlier_penalty) * w_op
    ) * 100

    score = max(0, min(100, round(raw_score, 1)))

    issues = []
    for r in rule_results:
        if r.status == RuleStatus.FAIL:
            issues.append(f"{r.rule_code}: {r.description}")
    for a in anomaly_results:
        if hasattr(a, "is_outlier") and a.is_outlier:
            issues.append(f"Anomaly: {a.rate_name} (z={a.z_score})")

    return {
        "score": score,
        "rule_compliance": round(rule_compliance * 100, 1),
        "completeness": round(completeness * 100, 1),
        "consistency": round(consistency * 100, 1),
        "outlier_penalty": round(outlier_penalty * 100, 1),
        "issues": issues,
    }


def _calc_rule_compliance(rule_results: List[RuleResult]) -> float:
    if not rule_results:
        return 1.0
    passed = sum(1 for r in rule_results if r.status == RuleStatus.PASS)
    total = len(rule_results)
    return passed / total


def _calc_completeness(values: Dict[str, float], active_indicator_count: int) -> float:
    if active_indicator_count == 0:
        return 0.0
    filled = sum(1 for v in values.values() if v is not None)
    return filled / active_indicator_count


def _calc_consistency(rule_results: List[RuleResult], config: Optional[Dict[str, float]] = None) -> float:
    if not rule_results:
        return 1.0
    cfg = config or {}
    severity_weights = {
        Severity.HIGH: cfg.get("severity_high", 3),
        Severity.MEDIUM: cfg.get("severity_medium", 2),
        Severity.LOW: cfg.get("severity_low", 1),
    }
    total_weight = 0
    fail_weight = 0
    for r in rule_results:
        w = severity_weights.get(r.severity, 1)
        total_weight += w
        if r.status == RuleStatus.FAIL:
            fail_weight += w
    if total_weight == 0:
        return 1.0
    return 1.0 - (fail_weight / total_weight)


def _calc_outlier_penalty(anomaly_results: list, config: Optional[Dict[str, float]] = None) -> float:
    if not anomaly_results:
        return 0.0
    cfg = config or {}
    multiplier = cfg.get("outlier_multiplier", 2.0)
    outlier_count = sum(1 for a in anomaly_results if hasattr(a, "is_outlier") and a.is_outlier)
    total = len(anomaly_results)
    if total == 0:
        return 0.0
    ratio = outlier_count / total
    return min(1.0, ratio * multiplier)
