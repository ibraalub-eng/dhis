"""Regression: constant (zero-variance) failure-rate series produced NaN in
calculate_trend (scipy linregress returns r_value=nan when all y equal), which
then leaked into /root-cause/{id} JSON and 500'd (NaN not JSON-compliant).

The fix must clamp to finite values (r_squared=0, significant=False) and the
API must still return 200.
"""
import math
import pytest
import json


@pytest.mark.parametrize("constant", [0.0, 5.0, 30.0])
def test_calculate_trend_constant_series_is_finite(constant):
    from app.engine.root_cause import calculate_trend, MonthDataPoint

    history = [MonthDataPoint(month=f"2026-0{i}", value=constant,
                              quality_score=0.8, confidence=0.8, rule_failure_rate=constant)
               for i in range(1, 6)]
    trend = calculate_trend(history)

    for key in ("slope", "r_squared", "volatility"):
        assert key in trend
        assert isinstance(trend[key], (int, float)), key
        assert not math.isnan(trend[key]), f"{key} is NaN for constant series"
        assert not math.isinf(trend[key]), f"{key} is inf for constant series"
    assert trend["r_squared"] == 0
    assert trend["significant_change"] is False


def test_root_cause_api_returns_200_with_constant_failure_rate(db_session):
    """A rule failing at the same rate every month must not 500 the endpoint."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.models import Hospital, ValidationResult, Indicator, IndicatorValue, Rule, HospitalType

    htype = HospitalType(name="ConstGov")
    db_session.add(htype)
    db_session.flush()
    htype_id = htype.id

    target = Hospital(name="ConstRateHosp", hospital_type_id=htype_id, is_active=True)
    peers = [Hospital(name=f"ConstHP{i}", hospital_type_id=htype_id, is_active=True) for i in range(3)]
    db_session.add_all([target] + peers)
    db_session.flush()

    code_to_id = {i.code: i.id for i in db_session.query(Indicator).all()}
    for h in [target] + peers:
        for code, v in {"2": 200, "5": 40, "6": 190, "10": 2}.items():
            for m in ["2026-04", "2026-05", "2026-06"]:
                db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=code_to_id[code], month=m, value=v))

    # Ensure the rule set exists in DB so history is keyed by rule code
    rule = Rule(code="R9NAN", name="C-section rate exceeds threshold", description="bench",
                expression_type="benchmark_rate", params=json.dumps(
                    {"num_code": "5", "den_code": "2", "threshold": 25.0}),
                rule_type="BENCHMARK", severity="HIGH", category="BASIC_LOGIC")
    db_session.add(rule)

    # SAME failure_rate every month (constant series, zero variance)
    for m in ["2026-04", "2026-05", "2026-06"]:
        db_session.add(ValidationResult(
            hospital_id=target.id, month=m, rule_code="R9NAN",
            rule_description="C-section rate exceeds threshold", status="FAIL", severity="HIGH",
        ))
        db_session.add(ValidationResult(
            hospital_id=target.id, month=m, rule_code="R9NAN",
            rule_description="C-section rate exceeds threshold", status="PASS", severity="HIGH",
        ))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get(
            f"/root-cause/{target.id}?month=2026-06&include_history=true&compare_peers=true&months_back=3"
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for factor, trend in (data.get("historical_trends") or {}).items():
        for key in ("slope", "r_squared", "volatility"):
            val = trend.get(key)
            if val is not None:
                assert math.isfinite(val), f"{factor}.{key} is non-finite: {val}"