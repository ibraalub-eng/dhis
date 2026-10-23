"""Tests for quality score calculation (engine.quality)."""
from app.engine.quality import (
    calculate_quality_score,
    RuleResult,
    RuleStatus,
    Severity,
    RuleType,
)


def _rr(code, desc, status, sev, rtype=RuleType.LOGIC):
    return RuleResult(code, desc, status, sev, rtype, "detail")


def test_perfect_score():
    results = [_rr("R01", "Test rule", RuleStatus.PASS, Severity.HIGH)]
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["score"] >= 70
    assert score["rule_compliance"] == 100.0


def test_all_fail():
    results = [
        _rr("R01", "Test", RuleStatus.FAIL, Severity.HIGH),
        _rr("R02", "Test", RuleStatus.FAIL, Severity.MEDIUM),
    ]
    values = {"2": 100.0, "6": 100.0}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["score"] < 80
    assert score["rule_compliance"] == 0.0
    assert len(score["issues"]) == 2


def test_completeness_low():
    results = []
    values = {"2": 100.0}
    required = {str(i) for i in range(100)}
    score = calculate_quality_score(results, values, [], required)
    assert score["completeness"] == 1.0


def test_completeness_high():
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["completeness"] == 100.0


def test_completeness_zero_indicators():
    results = []
    values = {"2": 100.0}
    score = calculate_quality_score(results, values, [], set())
    assert score["completeness"] == 0.0


def test_completeness_covered_children_not_penalized():
    # required = total "2" + siblings "2.a", "2.b"; "2.b" missing but covered.
    results = []
    values = {"2": 100.0, "2.a": 100.0}
    score = calculate_quality_score(results, values, [], {"2", "2.a", "2.b"}, covered_codes={"2.b"})
    assert score["completeness"] == 100.0


def test_completeness_covered_counted_from_required():
    # 3 required, 1 filled, 1 covered -> denominator 2 -> 50%.
    results = []
    values = {"2": 10.0}
    score = calculate_quality_score(results, values, [], {"2", "2.a", "2.b"}, covered_codes={"2.a"})
    assert score["completeness"] == 50.0


def test_completeness_no_covered_change():
    results = []
    values = {"2": 10.0}
    required = {"2", "2.a", "2.b"}
    before = calculate_quality_score(results, values, [], required)
    after = calculate_quality_score(results, values, [], required, covered_codes=set())
    assert before["completeness"] == after["completeness"]


def test_score_clamps_to_100():
    results = [_rr("R01", "Test", RuleStatus.PASS, Severity.HIGH)]
    values = {str(i): float(i) for i in range(100)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["score"] <= 100.0


def test_score_never_negative():
    results = [_rr(f"R{i}", "Test", RuleStatus.FAIL, Severity.CRITICAL) for i in range(30)]
    values = {}
    score = calculate_quality_score(results, values, [], set())
    assert score["score"] >= 0.0


def test_outlier_penalty_zero():
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, [], set(values))
    assert score["outlier_penalty"] == 0.0


def test_outlier_penalty_with_anomalies():
    from app.engine.anomaly import AnomalyResultData
    anomalies = [
        AnomalyResultData("5", "C-section rate", 50.0, 25.0, 3.5, True),
        AnomalyResultData("10", "SMM rate", 30.0, 10.0, 2.8, True),
    ]
    results = []
    values = {str(i): float(i) for i in range(60)}
    score = calculate_quality_score(results, values, anomalies, set(values))
    assert score["outlier_penalty"] > 0.0


def test_issues_list_from_failures():
    results = [
        _rr("R001", "Total deliveries", RuleStatus.FAIL, Severity.HIGH),
        _rr("R041", "CS rate high", RuleStatus.FAIL, Severity.CRITICAL),
    ]
    values = {"2": 100}
    score = calculate_quality_score(results, values, [], {str(i) for i in range(60)})
    assert any("R001" in i for i in score["issues"])
    assert any("R041" in i for i in score["issues"])


# ── Consistency severity weighting ─────────────────────────────────────────
# CRITICAL is a real severity in app.engine.quality.rules (R050 facility
# not operational, R054/R055 maternal/neonatal surges). It used to have no
# entry in the consistency weight map, so it fell through to the generic 1 —
# less than HIGH (3). It now reads severity_critical, whose default 1 keeps
# every existing score unchanged until an operator raises it.

def _consistency(rule_results, **cfg):
    return calculate_quality_score(rule_results, {}, [], set(), cfg or None)["consistency"]


def test_critical_failure_reads_its_own_weight_setting():
    results = [
        _rr("R001", "low pass", RuleStatus.PASS, Severity.LOW),
        _rr("R050", "facility not operational", RuleStatus.FAIL, Severity.CRITICAL),
    ]
    # Default (severity_critical = 1): one CRITICAL failure against one LOW pass.
    assert _consistency(results) == 50.0
    # Configured: the blocking failure now weighs four times the LOW pass.
    assert _consistency(results, severity_critical=4) == 20.0
    assert _consistency(results, severity_critical=4) < _consistency(
        results, severity_high=4)


def test_critical_can_outweigh_high_once_configured():
    crit = [
        _rr("R001", "low pass", RuleStatus.PASS, Severity.LOW),
        _rr("R050", "facility not operational", RuleStatus.FAIL, Severity.CRITICAL),
    ]
    high = [
        _rr("R001", "low pass", RuleStatus.PASS, Severity.LOW),
        _rr("R002", "high failure", RuleStatus.FAIL, Severity.HIGH),
    ]
    # With CRITICAL > HIGH a blocking failure leaves the lower consistency.
    assert _consistency(crit, severity_critical=4) < _consistency(high)


def test_default_critical_weight_preserves_existing_scores_exactly():
    results = [
        _rr("R001", "low pass", RuleStatus.PASS, Severity.LOW),
        _rr("R002", "high fail", RuleStatus.FAIL, Severity.HIGH),
        _rr("R050", "facility not operational", RuleStatus.FAIL, Severity.CRITICAL),
    ]
    legacy_cfg = {"severity_high": 3, "severity_medium": 2, "severity_low": 1}
    legacy = calculate_quality_score(results, {}, [], set(), legacy_cfg)
    seeded = calculate_quality_score(
        results, {}, [], set(), dict(legacy_cfg, severity_critical=1))
    assert seeded == legacy, (
        "seeding severity_critical=1 must not move any component or the score"
    )


def test_severity_critical_setting_is_seeded_at_the_preserving_default():
    from app.main import APP_CONFIG_DEFAULTS

    row = next(r for r in APP_CONFIG_DEFAULTS if r[0] == "severity_critical")
    assert row[1] == 1.0, (
        "the default must equal the weight CRITICAL silently used before, or "
        "enabling the setting would change stored scores"
    )
    assert row[2] == "quality"


def test_every_consistency_weight_source_knows_critical():
    """The weight map exists twice (engine + the rules re-seed script) and is
    surfaced in Settings; all three must know CRITICAL."""
    from pathlib import Path

    from app.engine.quality import SEVERITY_WEIGHT_DEFAULTS, severity_weights

    assert set(SEVERITY_WEIGHT_DEFAULTS) == {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    assert severity_weights({"severity_critical": 5})["CRITICAL"] == 5.0
    assert severity_weights({})["CRITICAL"] == 1.0

    root = Path(__file__).resolve().parent.parent
    seed = (root / "scripts" / "seed_rules.py").read_text(encoding="utf-8")
    assert '"CRITICAL": float(quality_config.get("severity_critical", 1))' in seed

    html = (root / "static" / "tabs" / "settings.html").read_text(encoding="utf-8")
    assert 'id="cfg_severity_critical"' in html
    js = (root / "static" / "js" / "rules-manager.js").read_text(encoding="utf-8")
    assert "'severity_critical'" in js, "the Settings save list must include it"
