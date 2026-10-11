"""API tests for the layered-outlier endpoints (design spec 2026-10-08 §8).

Rows are inserted directly: pipeline → table persistence is Task 13's
coverage; this module reads the API surface (filters, paging, summary,
the outliers join, cache lifecycle, permissions)."""
import pytest
from fastapi.testclient import TestClient

from app.cache import cache
from app.core.deps import get_current_user
from app.core.security import hash_password
from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    Permission,
    Role,
    User,
)


@pytest.fixture
def client(app):
    """TestClient over the conftest app — `_bypass_auth` already overrides
    get_current_user (superadmin) and get_db (db_session)."""
    return TestClient(app)


@pytest.fixture
def real_auth(app, _bypass_auth):
    """Strip the FakeSuperAdmin override so real JWT permission checks run."""
    app.dependency_overrides.pop(get_current_user, None)
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _login(client, username, password="test123"):
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _add_layered(db, hospital_id, month, *, analysis_code="rate_cs", **overrides):
    fields = dict(
        hospital_id=hospital_id,
        analysis_code=analysis_code,
        month=month,
        raw_value=25.0,
        previous_value=10.0,
        denominator=100.0,
        rate=25.0,
        raw_value_outlier_score=1.0,
        rate_outlier_score=1.0,
        historical_outlier_score=1.0,
        volume_anomaly_score=0.0,
        outlier_level="VERY_HIGH",
        outlier_type="CLINICAL_INVESTIGATION_REQUIRED",
        outlier_method="pct_change",
        interpretation="Rate and history both exceed their thresholds.",
        investigation_route="clinical",
    )
    fields.update(overrides)
    row = LayeredOutlierResult(**fields)
    db.add(row)
    db.commit()
    return row


def test_layered_endpoint_filters_by_month(db_session, client):
    """Scenario 14: only the requested month comes back."""
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-05")
    _add_layered(db_session, h.id, "2027-06")

    resp = client.get("/analysis/layered?month=2027-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert [row["month"] for row in body["data"]] == ["2027-06"]


def test_layered_endpoint_filters_by_hospital(db_session, client):
    """Scenario 15: only the requested hospital comes back."""
    h1, h2 = db_session.query(Hospital).order_by(Hospital.id).limit(2).all()
    _add_layered(db_session, h1.id, "2027-06")
    _add_layered(db_session, h2.id, "2027-06")

    resp = client.get(f"/analysis/layered?month=2027-06&hospital={h1.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert {row["hospital_id"] for row in body["data"]} == {h1.id}


def test_layered_endpoint_filters_classification_level_and_route(db_session, client):
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-06")
    _add_layered(db_session, h.id, "2027-06", analysis_code="5",
                 outlier_type="HISTORICAL_ANOMALY", outlier_level="HIGH",
                 investigation_route="contextual")
    _add_layered(db_session, h.id, "2027-06", analysis_code="2",
                 outlier_type="NORMAL", outlier_level="NONE",
                 investigation_route="none")

    resp = client.get("/analysis/layered?month=2027-06&classification=NORMAL")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["data"][0]["analysis_code"] == "2"

    resp = client.get("/analysis/layered?month=2027-06&level=VERY_HIGH")
    assert resp.json()["total"] == 1
    assert resp.json()["data"][0]["analysis_code"] == "rate_cs"

    resp = client.get("/analysis/layered?month=2027-06&investigation=contextual")
    assert resp.json()["total"] == 1
    assert resp.json()["data"][0]["analysis_code"] == "5"

    # Display metadata comes from build_analysis_specs — same source the
    # engine persisted with (registry name for rate rows, Indicator name
    # for count rows).
    by_code = {row["analysis_code"]: row
               for row in client.get("/analysis/layered?month=2027-06").json()["data"]}
    assert by_code["rate_cs"]["indicator_name"] == "C-section rate"
    assert by_code["rate_cs"]["indicator_type"] is not None
    ind2 = db_session.query(Indicator).filter_by(code="2").first()
    assert by_code["2"]["indicator_name"] == ind2.name


def test_layered_endpoint_paginates_and_sorts(db_session, client):
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-06", analysis_code="a", raw_value=10.0)
    _add_layered(db_session, h.id, "2027-06", analysis_code="b", raw_value=30.0)
    _add_layered(db_session, h.id, "2027-06", analysis_code="c", raw_value=20.0)

    page1 = client.get(
        "/analysis/layered?month=2027-06&sort=raw_value&order=asc&page=1&page_size=2"
    ).json()
    assert page1["total"] == 3
    assert page1["page_size"] == 2
    assert [row["analysis_code"] for row in page1["data"]] == ["a", "c"]

    page2 = client.get(
        "/analysis/layered?month=2027-06&sort=raw_value&order=asc&page=2&page_size=2"
    ).json()
    assert [row["analysis_code"] for row in page2["data"]] == ["b"]


def test_layered_summary_counts_classifications_and_hospitals(db_session, client):
    h1, h2 = db_session.query(Hospital).order_by(Hospital.id).limit(2).all()
    _add_layered(db_session, h1.id, "2027-06")
    _add_layered(db_session, h1.id, "2027-06", analysis_code="5",
                 outlier_type="HISTORICAL_ANOMALY", outlier_level="HIGH",
                 investigation_route="contextual")
    _add_layered(db_session, h2.id, "2027-06",
                 outlier_type="NORMAL", outlier_level="NONE",
                 investigation_route="none")
    _add_layered(db_session, h1.id, "2027-05")

    resp = client.get("/analysis/layered/summary?month=2027-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert {c["outlier_type"]: c["count"] for c in body["by_classification"]} == {
        "CLINICAL_INVESTIGATION_REQUIRED": 1,
        "HISTORICAL_ANOMALY": 1,
        "NORMAL": 1,
    }
    assert {row["hospital_id"]: row["count"] for row in body["by_hospital"]} == {
        h1.id: 2,
        h2.id: 1,
    }
    assert all(row["hospital"] for row in body["by_hospital"])

    all_months = client.get("/analysis/layered/summary").json()
    assert all_months["total"] == 4


def test_outliers_endpoint_includes_layered_classification(db_session, client):
    h = db_session.query(Hospital).first()
    # rate_name "C-section rate" → registry rate_code "rate_cs"; the layered
    # row must be keyed by that code for the join to find it.
    _add_layered(db_session, h.id, "2027-06", analysis_code="rate_cs",
                 outlier_type="CLINICAL_INVESTIGATION_REQUIRED",
                 outlier_level="VERY_HIGH",
                 interpretation="Rate and history both exceed their thresholds.")
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2027-06", indicator_code="5",
        rate_name="C-section rate", value=90.0, benchmark=40.0,
        z_score=3.1, is_outlier=True,
    ))
    db_session.add(AnomalyResult(  # no layered row for this month
        hospital_id=h.id, month="2027-05", indicator_code="5",
        rate_name="C-section rate", value=60.0, benchmark=40.0,
        z_score=2.8, is_outlier=True,
    ))
    db_session.commit()

    resp = client.get("/analysis/outliers")
    assert resp.status_code == 200
    rows = {row["month"]: row for row in resp.json()["data"]}

    joined = rows["2027-06"]
    assert joined["layered_type"] == "CLINICAL_INVESTIGATION_REQUIRED"
    assert joined["layered_level"] == "VERY_HIGH"
    assert "threshold" in joined["layered_interpretation"]

    # LEFT JOIN semantics: no layered row → nulls, never a fake classification.
    assert rows["2027-05"]["layered_type"] is None
    assert rows["2027-05"]["layered_level"] is None
    assert rows["2027-05"]["layered_interpretation"] is None


def test_layered_cache_lifecycle_within_a_request_cycle(db_session, client):
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-06", analysis_code="rate_cs")

    first = client.get("/analysis/layered?month=2027-06").json()
    assert first["total"] == 1

    _add_layered(db_session, h.id, "2027-06", analysis_code="5")
    cached = client.get("/analysis/layered?month=2027-06").json()
    assert cached["total"] == 1  # still cached — the new row is invisible

    # Prefix must include the "v2|" segment make_key() prepends (cache.py:193).
    cache.invalidate("v2|analysis:layered")
    fresh = client.get("/analysis/layered?month=2027-06").json()
    assert fresh["total"] == 2


def test_layered_endpoints_enforce_analysis_read(db_session, client, real_auth):
    perm = db_session.query(Permission).filter_by(codename="analysis.read").first()
    if perm is None:
        perm = Permission(codename="analysis.read")
        db_session.add(perm)
        db_session.flush()

    reader_role = Role(name="layered_reader")
    reader_role.permissions.append(perm)
    db_session.add(reader_role)
    db_session.add_all([
        User(username="layered_noperm", email="layered_np@test.local",
             full_name="No Perm", password_hash=hash_password("test123")),
        User(username="layered_reader", email="layered_r@test.local",
             full_name="Reader", password_hash=hash_password("test123"),
             roles=[reader_role]),
    ])
    db_session.commit()

    no_perm_token = _login(client, "layered_noperm")
    resp = client.get("/analysis/layered",
                      headers={"Authorization": f"Bearer {no_perm_token}"})
    assert resp.status_code == 403
    resp = client.get("/analysis/layered/summary",
                      headers={"Authorization": f"Bearer {no_perm_token}"})
    assert resp.status_code == 403

    ok_token = _login(client, "layered_reader")
    resp = client.get("/analysis/layered",
                      headers={"Authorization": f"Bearer {ok_token}"})
    assert resp.status_code == 200
    assert "data" in resp.json()


# ───────────────────────── explain (kind=layered_outlier) ─────────────────────

def _add_history_values(db, hospital_id, months, code="2", value=100.0):
    """Prior-month values so get_historical_months finds a real baseline."""
    ind = db.query(Indicator).filter(Indicator.code == str(code)).first()
    assert ind is not None, f"seeded indicator {code} missing"
    for m in months:
        db.add(IndicatorValue(
            hospital_id=hospital_id, indicator_id=ind.id, month=m, value=value,
        ))
    db.commit()


def test_explain_layered_outlier_contract(db_session, client):
    """Spec §9: full contract payload; stored scores + current history
    reproduce rule 4's clinical classification."""
    h = db_session.query(Hospital).first()
    _add_history_values(db_session, h.id, ["2027-03", "2027-04", "2027-05"])
    _add_layered(db_session, h.id, "2027-06")

    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={h.id}"
        "&month=2027-06&indicator_code=rate_cs"
    )
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["kind"] == "layered_outlier"
    assert p["data_epoch"]
    for key in ("what", "where", "why", "how", "reproduce", "chain", "classification"):
        assert key in p, f"contract key {key!r} missing"
    assert p["what"]
    assert p["classification"] == "CLINICAL_INVESTIGATION_REQUIRED"
    assert p["where"]["analysis_code"] == "rate_cs"
    assert p["where"]["indicator_name"] == "C-section rate"
    # Full-precision inputs behind every displayed number.
    inputs = p["how"]["inputs"]
    assert inputs["raw_value"] == 25.0
    assert inputs["raw_change_percent"] == 150.0
    assert inputs["denominator"] == 100.0
    assert inputs["scores"]["rate"] == 1.0
    assert inputs["scores"]["volume"] == 0.0
    assert p["how"]["thresholds"]["minimum_history_period"] == 3
    # 3 prior months >= minimum_history_period → history_ok; the re-run over
    # the stored scores reproduces rule 4 (rate HIGH + history HIGH + volume LOW).
    assert p["reproduce"]["history_ok"] is True
    assert p["reproduce"]["verified"] is True
    assert p["rule_number"] == 4
    # §9 dashboard block: one entry per layer, engine order.
    assert [lay["key"] for lay in p["layers"]] == ["raw", "rate", "historical", "volume", "peer"]
    assert p["layers"][2]["score"] == 1.0 and p["layers"][2]["level"] == "VERY_HIGH"
    # The stored interpretation is the conclusion paragraph.
    assert "Rate and history both exceed their thresholds." in p["why"]
    assert any("/analysis/layered" in (n.get("endpoint") or "") for n in p["chain"])


def test_explain_layered_outlier_missing_row_404s(db_session, client):
    h = db_session.query(Hospital).first()

    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={h.id}"
        "&month=2027-06&indicator_code=rate_cs"
    )
    assert resp.status_code == 404
    assert "layered outlier row" in resp.json()["detail"]

    # The analysis unit travels on the existing indicator_code parameter.
    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={h.id}&month=2027-06"
    )
    assert resp.status_code == 404
    assert "indicator_code" in resp.json()["detail"]


def test_explain_layered_outlier_flags_changed_history(db_session, client):
    """Row written under a different history → honest 'recalculate' note,
    stored classification still displayed, no invented rule number."""
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-06")     # no IndicatorValue history

    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={h.id}"
        "&month=2027-06&indicator_code=rate_cs"
    )
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["classification"] == "CLINICAL_INVESTIGATION_REQUIRED"
    assert p["reproduce"]["history_ok"] is False
    assert p["reproduce"]["verified"] is False
    assert p["rule_number"] is None
    assert "recalculate" in p["why"]


# ───────────────────────────────────────────── trend endpoint (Layer trend chart)

def test_layered_trend_one_series_per_hospital(db_session, client):
    """For a chosen indicator, the trend plots one series per hospital with its
    points across the sorted months — the same unit across the series."""
    h1, h2 = db_session.query(Hospital).order_by(Hospital.id).limit(2).all()
    _add_layered(db_session, h1.id, "2027-06", analysis_code="rate_cs", raw_value=20.0)
    _add_layered(db_session, h1.id, "2027-05", analysis_code="rate_cs", raw_value=10.0)
    _add_layered(db_session, h2.id, "2027-06", analysis_code="rate_cs", raw_value=99.0)

    resp = client.get("/analysis/layered/trend?indicator=rate_cs")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["months"] == ["2027-05", "2027-06"]
    series = {s["key"]: s for s in body["series"]}
    assert set(series) == {str(h1.id), str(h2.id)}
    assert series[str(h1.id)]["name"] == h1.name
    assert [p["month"] for p in series[str(h1.id)]["points"]] == ["2027-05", "2027-06"]
    assert [p["raw_value"] for p in series[str(h1.id)]["points"]] == [10.0, 20.0]
    assert [p["month"] for p in series[str(h2.id)]["points"]] == ["2027-06"]


def test_layered_trend_single_line_for_hospital_and_indicator(db_session, client):
    """Hospital + indicator selected → exactly one series across the months."""
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-05", analysis_code="rate_cs", raw_value=10.0)
    _add_layered(db_session, h.id, "2027-06", analysis_code="rate_cs", raw_value=20.0)

    body = client.get(
        f"/analysis/layered/trend?hospital={h.id}&indicator=rate_cs"
    ).json()
    assert len(body["series"]) == 1
    assert body["series"][0]["name"] == h.name
    assert [p["raw_value"] for p in body["series"][0]["points"]] == [10.0, 20.0]


def test_layered_trend_honors_every_filter(db_session, client):
    """The chart is a filter-driven view: classification/level/month narrow the
    points exactly like the table (design decision: honor all table filters)."""
    h = db_session.query(Hospital).first()
    _add_layered(db_session, h.id, "2027-05", analysis_code="rate_cs",
                 raw_value=10.0, outlier_type="NORMAL", outlier_level="NONE")
    _add_layered(db_session, h.id, "2027-06", analysis_code="rate_cs",
                 raw_value=20.0, outlier_type="CLINICAL_INVESTIGATION_REQUIRED",
                 outlier_level="VERY_HIGH")

    only_normal = client.get(
        f"/analysis/layered/trend?hospital={h.id}&indicator=rate_cs&classification=NORMAL"
    ).json()
    pts = only_normal["series"][0]["points"]
    assert [p["month"] for p in pts] == ["2027-05"]

    only_june = client.get(
        f"/analysis/layered/trend?hospital={h.id}&indicator=rate_cs&month=2027-06"
    ).json()
    assert only_june["months"] == ["2027-06"]

    # Every point carries the classification so the chart can color outliers.
    full = client.get(f"/analysis/layered/trend?hospital={h.id}&indicator=rate_cs").json()
    pt = full["series"][0]["points"][1]
    assert pt["outlier_type"] == "CLINICAL_INVESTIGATION_REQUIRED"
    assert pt["outlier_level"] == "VERY_HIGH"
    assert "rate" in pt


def test_layered_trend_empty(db_session, client):
    resp = client.get("/analysis/layered/trend?indicator=rate_cs")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["months"] == []
    assert body["series"] == []


def test_layered_trend_enforces_analysis_read(db_session, client, real_auth):
    perm = db_session.query(Permission).filter_by(codename="analysis.read").first()
    if perm is None:
        perm = Permission(codename="analysis.read")
        db_session.add(perm)
        db_session.flush()
    reader_role = Role(name="trend_reader")
    reader_role.permissions.append(perm)
    db_session.add(reader_role)
    db_session.add_all([
        User(username="trend_noperm", email="trend_np@test.local",
             full_name="No Perm", password_hash=hash_password("test123")),
        User(username="trend_reader", email="trend_r@test.local",
             full_name="Reader", password_hash=hash_password("test123"),
             roles=[reader_role]),
    ])
    db_session.commit()

    no_perm_token = _login(client, "trend_noperm")
    resp = client.get("/analysis/layered/trend",
                      headers={"Authorization": f"Bearer {no_perm_token}"})
    assert resp.status_code == 403

    ok_token = _login(client, "trend_reader")
    resp = client.get("/analysis/layered/trend",
                      headers={"Authorization": f"Bearer {ok_token}"})
    assert resp.status_code == 200
