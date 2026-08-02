"""Tests for the full data export feature."""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# --- Engine helpers ---

def test_sanitize_converts_numpy_scalars(db_session):
    import numpy as np
    from app.engine.export import _sanitize
    out = _sanitize({"score": np.float64(0.45), "count": np.int64(7), "nan": float("nan"), "inf": float("inf")})
    assert out["score"] == 0.45
    assert isinstance(out["score"], float)
    assert out["count"] == 7
    assert isinstance(out["count"], int)
    assert out["nan"] == 0.0
    assert out["inf"] == 0.0


def test_sanitize_converts_numpy_array(db_session):
    import numpy as np
    from app.engine.export import _sanitize
    out = _sanitize({"arr": np.array([1.0, 2.5, 3.0])})
    assert out["arr"] == [1.0, 2.5, 3.0]
    assert isinstance(out["arr"], list)
    assert all(isinstance(v, float) for v in out["arr"])


def test_get_available_months_empty(db_session):
    from app.engine.export import _get_available_months
    assert _get_available_months(db_session) == []


def test_get_available_months_distinct_sorted(db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    from app.engine.export import _get_available_months
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add_all([
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=100),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=120),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=90),
    ])
    db_session.commit()
    assert _get_available_months(db_session) == ["2026-05", "2026-06"]


def test_get_master_data_returns_all_sections(db_session):
    from app.engine.export import _get_master_data
    md = _get_master_data(db_session)
    assert "governorates" in md
    assert "hospitals" in md
    assert "indicators" in md
    assert "hospital_indicator_configs" in md
    assert len(md["hospitals"]) == 3
    assert len(md["indicators"]) > 0
    h = md["hospitals"][0]
    for key in ("id", "name", "region", "address", "governorate_name",
                "hospital_type_name", "facility_ownership_name", "facility_type_name", "is_active"):
        assert key in h


def test_get_indicator_values_grouped_by_month(db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    from app.engine.export import _get_indicator_values
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add(IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=300, source_file="x.xlsx"))
    db_session.commit()
    result = _get_indicator_values(db_session, ["2026-06"])
    assert "2026-06" in result
    row = result["2026-06"][0]
    assert row["hospital_id"] == hosp.id
    assert row["hospital_name"] == hosp.name
    assert row["indicator_code"] == "2"
    assert row["indicator_name"] == ind.name
    assert row["value"] == 300
    assert row["source_file"] == "x.xlsx"


# --- build_full_export ---

def test_build_full_export_structure(db_session):
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    assert pkg["meta"]["scope"] == "2026-06"
    assert pkg["meta"]["lang"] == "ar"
    assert pkg["meta"]["schema_version"] == 1
    assert "master_data" in pkg
    assert "indicator_values" in pkg
    assert "analysis" in pkg
    assert "2026-06" in pkg["analysis"]
    assert isinstance(json.loads(json.dumps(pkg, ensure_ascii=False)), dict)


def test_build_full_export_smart_sections(db_session):
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    smart = pkg["analysis"]["2026-06"]["smart"]
    for key in ("kpi", "anomalies", "clustering", "correlations", "residuals",
                "stratified", "explanations", "geo"):
        assert key in smart


@patch("app.engine.export.run_smart_analytics")
def test_build_full_export_month_error_embedded(mock_analytics, db_session):
    mock_analytics.side_effect = RuntimeError("boom")
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    assert "error" in pkg["analysis"]["2026-06"]
    assert "boom" in pkg["analysis"]["2026-06"]["error"]


def test_build_full_export_all_months(db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    from app.engine.export import build_full_export
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add_all([
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=100),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=120),
    ])
    db_session.commit()
    pkg = build_full_export(db_session, "all", "ar")
    assert pkg["meta"]["scope"] == "all"
    assert set(pkg["indicator_values"].keys()) == {"2026-05", "2026-06"}
    assert set(pkg["analysis"].keys()) == {"2026-05", "2026-06"}


def test_build_full_export_comprehensive_report_null_when_uncached(db_session):
    from app.engine.export import build_full_export
    pkg = build_full_export(db_session, "2026-06", "ar")
    assert pkg["analysis"]["2026-06"]["comprehensive_report"] is None


@patch("app.engine.comparative.report_generator._call_api")
def test_export_never_calls_ai(mock_api, db_session):
    from app.engine.export import build_full_export
    build_full_export(db_session, "all", "ar")
    assert mock_api.call_count == 0


def test_build_full_export_report_from_cache(db_session):
    from app.engine.comparative.report_cache import store_report
    from app.engine.export import build_full_export
    store_report(db_session, "2026-06", "ar", {"report": "نص مخزن", "report_source": "ai", "month": "2026-06"})
    pkg = build_full_export(db_session, "2026-06", "ar")
    rep = pkg["analysis"]["2026-06"]["comprehensive_report"]
    assert rep == {"report": "نص مخزن", "report_source": "ai"}


def test_build_full_export_no_data_raises(db_session):
    from app.models import Hospital
    from app.engine.export import build_full_export, NoDataError
    db_session.query(Hospital).delete()
    db_session.commit()
    try:
        build_full_export(db_session, "all", "ar")
        assert False, "expected NoDataError"
    except NoDataError:
        pass


# --- API endpoint ---

def test_export_endpoint_returns_json_download(client):
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "ar"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "attachment" in resp.headers["content-disposition"]
    data = resp.json()
    assert data["meta"]["scope"] == "2026-06"


def test_export_endpoint_all_months(client, db_session):
    from app.models import Hospital, Indicator, IndicatorValue
    hosp = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    db_session.add_all([
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-05", value=100),
        IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month="2026-06", value=120),
    ])
    db_session.commit()
    resp = client.get("/export/full-data", params={"month": "all", "lang": "en"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["scope"] == "all"
    assert data["meta"]["lang"] == "en"
    assert set(data["indicator_values"].keys()) == {"2026-05", "2026-06"}


def test_export_endpoint_invalid_lang_422(client):
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "xx"})
    assert resp.status_code == 422


def test_export_endpoint_no_data_404(client, db_session):
    from app.models import Hospital
    db_session.query(Hospital).delete()
    db_session.commit()
    resp = client.get("/export/full-data", params={"month": "all", "lang": "ar"})
    assert resp.status_code == 404
    assert "لا توجد بيانات" in resp.json()["detail"]


def test_export_endpoint_serializes_without_error(client):
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "ar"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


@patch("app.api.export.build_full_export")
def test_export_endpoint_500_on_engine_failure(mock_build, client):
    mock_build.side_effect = RuntimeError("boom")
    resp = client.get("/export/full-data", params={"month": "2026-06", "lang": "ar"})
    assert resp.status_code == 500


# --- Frontend structure ---

def test_smart_page_has_export_button():
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "smart-analytics.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="smart-export-btn") is not None
    assert soup.find(id="smart-export-scope") is not None


def test_comparative_page_has_export_button():
    import os
    from bs4 import BeautifulSoup
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "comparative.html")
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    assert soup.find(id="comparative-export-btn") is not None
    assert soup.find(id="comparative-export-scope") is not None


def test_smart_js_has_export_handler():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "smart-analytics.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function smartExportData" in content
    assert "/export/full-data?month=" in content
    assert "lang=ar" in content


def test_comparative_js_has_export_handler():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "comparative.js")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "function comparativeExportData" in content
    assert "/export/full-data?month=" in content
    assert "lang=${reportLang}" in content
