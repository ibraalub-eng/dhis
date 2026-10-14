"""US-05: the Quality Score must have a single source of truth.

Every surface (engine, dashboard KPI recalc, indicator-config recalc, audit
tools, score repair) must combine the four components with the *same* weights
and the *same* formula, and produce the *same* result.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.engine.quality import (
    QUALITY_WEIGHT_DEFAULTS,
    QUALITY_WEIGHT_KEYS,
    RuleResult,
    RuleStatus,
    RuleType,
    Severity,
    calculate_quality_score,
    combine_quality_score,
    quality_weights,
)
from app.main import app
from app.models import QualityScore

# ── the canonical helpers ────────────────────────────────────────────────────

def test_quality_weights_defaults():
    assert quality_weights(None) == QUALITY_WEIGHT_DEFAULTS
    assert quality_weights({}) == QUALITY_WEIGHT_DEFAULTS
    assert QUALITY_WEIGHT_DEFAULTS == {
        "rule_compliance": 0.35,
        "completeness": 0.25,
        "consistency": 0.25,
        "outlier_penalty": 0.15,
    }


def test_quality_weights_from_config_keys():
    cfg = {
        "quality_rule_compliance": "0.40",
        "quality_completeness": "0.30",
        "quality_consistency": "0.20",
        "quality_outlier_penalty": "0.10",
    }
    w = quality_weights(cfg)
    assert w == {"rule_compliance": 0.40, "completeness": 0.30,
                 "consistency": 0.20, "outlier_penalty": 0.10}
    # every weight name maps to an AppConfig key
    assert set(QUALITY_WEIGHT_KEYS) == set(QUALITY_WEIGHT_DEFAULTS)


def test_combine_is_the_documented_formula():
    manual = round(
        90 * 0.35 + 50 * 0.25 + 80 * 0.25 + (100 - 10) * 0.15,
        1,
    )
    assert combine_quality_score(90, 50, 80, 10) == manual


def test_combine_clamps_and_handles_none():
    assert combine_quality_score(100, 100, 100, 0) == 100.0
    # missing components are treated as 0; a missing penalty means no penalty
    assert combine_quality_score(None, None, None, None) == 15.0
    assert 0.0 <= combine_quality_score(0, 0, 0, 100) <= 100.0


def test_combine_honours_config_override():
    cfg = {"quality_outlier_penalty": "0.5", "quality_rule_compliance": "0.5",
           "quality_completeness": "0.0", "quality_consistency": "0.0"}
    assert combine_quality_score(100, 0, 0, 100, cfg) == 50.0
    assert combine_quality_score(100, 0, 0, 100, cfg) != combine_quality_score(100, 0, 0, 100)


def test_calculate_quality_score_delegates_to_combine():
    results = [RuleResult("R1", "ok", RuleStatus.PASS, Severity.HIGH, RuleType.LOGIC, "")]
    values = {str(i): float(i) for i in range(60)}
    out = calculate_quality_score(results, values, [], set(values))
    expected = combine_quality_score(
        out["rule_compliance"], out["completeness"],
        out["consistency"], out["outlier_penalty"],
    )
    # stored components are rounded to 0.1, so allow one final-rounding step
    assert abs(out["score"] - expected) <= 0.1


# ── every recalculation surface must agree ───────────────────────────────────

@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _expected_from_engine(db, hospital_id, month, rc, co, op):
    from app.config_utils import get_config_dict
    from app.engine.pipeline import compute_hospital_completeness
    cp = round(compute_hospital_completeness(db, hospital_id, month), 1)
    cfg = get_config_dict(db, "quality")
    return cp, combine_quality_score(rc, cp, co, op, cfg)


def test_dashboard_recalc_uses_engine_formula(client, db_session):
    qs = QualityScore(hospital_id=1, month="2027-03", score=1.0,
                      rule_compliance=90.0, completeness=50.0,
                      consistency=80.0, outlier_penalty=10.0)
    db_session.add(qs)
    db_session.commit()

    resp = client.post("/dashboard/recalculate-completeness")
    assert resp.status_code == 200
    db_session.refresh(qs)

    cp, expected = _expected_from_engine(db_session, 1, "2027-03", 90.0, 80.0, 10.0)
    assert qs.completeness == cp
    assert qs.score == expected


def test_indicator_config_recalc_uses_engine_formula(db_session):
    from app.api.indicator_config import _recalc_hospital_scores

    qs = QualityScore(hospital_id=1, month="2027-04", score=1.0,
                      rule_compliance=75.0, completeness=60.0,
                      consistency=65.0, outlier_penalty=20.0)
    db_session.add(qs)
    db_session.commit()

    _recalc_hospital_scores(db_session, 1)
    db_session.refresh(qs)

    cp, expected = _expected_from_engine(db_session, 1, "2027-04", 75.0, 65.0, 20.0)
    assert qs.completeness == cp
    assert qs.score == expected


def test_admin_expected_score_matches_combine(db_session):
    from app.api.admin import _expected_score, _quality_weights
    from app.engine.quality import combine_quality_score

    w = _quality_weights(db_session)
    expected = combine_quality_score(88.0, 71.0, 63.0, 12.0,
                                     {"quality_rule_compliance": w["rule_compliance"],
                                      "quality_completeness": w["completeness"],
                                      "quality_consistency": w["consistency"],
                                      "quality_outlier_penalty": w["outlier_inverted"]})
    assert _expected_score(w, 88.0, 71.0, 63.0, 12.0) == expected


def test_audit_breakdown_weights_match_engine(db_session):
    from app.engine.audit import calculation_steps, data_auditor  # noqa: F401
    from app.engine.audit.explain import _quality_config
    from app.engine.quality import quality_weights

    w = quality_weights(None)
    qc = _quality_config(db_session)["weights"]
    assert qc["rule_compliance"] == w["rule_compliance"]
    assert qc["completeness"] == w["completeness"]
    assert qc["consistency"] == w["consistency"]
    assert qc["outlier_score"] == w["outlier_penalty"]


def test_config_change_propagates_to_recalc(client, db_session):
    from app.models import AppConfig
    row = db_session.query(AppConfig).filter(AppConfig.key == "quality_outlier_penalty").first()
    if row is None:
        row = AppConfig(key="quality_outlier_penalty", value=0.5, category="quality")
        db_session.add(row)
    else:
        row.value = 0.5
    db_session.commit()

    qs = QualityScore(hospital_id=1, month="2027-05", score=1.0,
                      rule_compliance=100.0, completeness=50.0,
                      consistency=100.0, outlier_penalty=0.0)
    db_session.add(qs)
    db_session.commit()

    client.post("/dashboard/recalculate-completeness")
    db_session.refresh(qs)

    cp, expected = _expected_from_engine(db_session, 1, "2027-05", 100.0, 100.0, 0.0)
    assert qs.score == expected
    # 0.5 outlier weight on a zero penalty *lowers* nothing but the other
    # weights are diluted; the point is the endpoint used the new config.
    assert cp == round(cp, 1)
