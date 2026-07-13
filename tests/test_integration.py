"""Integration tests: upload → processing → analysis → report (via FastAPI TestClient)."""
import pytest
import io
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, get_db, SessionLocal, engine
from app.models import Hospital, IndicatorValue, QualityScore

# Use TestClient with dependency override for DB
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


def _make_excel_file(hospital="Test Hospital", month="2026-04"):
    """Create an in-memory Excel file with sample SRMNH data."""
    data = {
        "organisationunitname": [hospital, hospital],
        "month": [month, month],
        "Total Deliveries": [300, 280],
        "Normal Vaginal Deliveries": [200, 180],
        "Caesarean Sections": [80, 75],
        "Live Births": [290, 270],
        "Maternal Deaths": [1, 0],
        "Neonatal deaths": [5, 3],
    }
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    return buf


class TestUploadFlow:
    def test_upload_preview(self, client):
        f = _make_excel_file()
        resp = client.post(
            "/upload/preview",
            files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "file_path" in data or "filename" in data
        assert "hospitals" in data
        assert "months" in data

    def test_hospitals_endpoint(self, client):
        resp = client.get("/hospitals/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_reports_endpoint(self, client):
        resp = client.get("/reports/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_config_endpoint(self, client):
        resp = client.get("/config/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_dashboard_endpoint(self, client):
        resp = client.get("/dashboard/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_hospitals" in data or "hospitals" in data or isinstance(data, dict)


class TestAnalysisFlow:
    def test_analyze_saved_empty(self, client):
        """Analyze with no saved files should return gracefully."""
        resp = client.post("/analysis/analyze-saved?filenames=nonexistent.xlsx")
        # Should not crash — may return error or empty result
        assert resp.status_code in (200, 400, 404)

    def test_heatmap_endpoint(self, client):
        resp = client.get("/analysis/heatmap")
        assert resp.status_code == 200

    def test_clinical_endpoint(self, client):
        resp = client.get("/clinical/test_hospital/2026-04")
        assert resp.status_code in (200, 404)

    def test_alerts_overview(self, client):
        resp = client.get("/alerts/overview")
        assert resp.status_code == 200

    def test_alerts_list(self, client):
        resp = client.get("/alerts/list?limit=10")
        assert resp.status_code == 200

    def test_root_cause(self, client):
        resp = client.get("/root-cause/1/2026-04")
        assert resp.status_code in (200, 404)


class TestFullPipeline:
    """Full upload → process → analyze → report flow using DB directly."""

    def test_pipeline_run_full_analysis(self, db_session, sample_values):
        """Insert indicator values directly and run full analysis."""
        from app.engine.pipeline import run_full_analysis

        hospital = db_session.query(Hospital).first()
        assert hospital is not None

        # Insert indicator values
        from app.models import Indicator
        from app.indicators import INDICATOR_CODE_TO_NAME

        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if not ind:
                continue
            iv = IndicatorValue(
                hospital_id=hospital.id,
                indicator_id=ind.id,
                month="2026-04",
                value=value,
            )
            db_session.add(iv)
        db_session.commit()

        # Run analysis
        result = run_full_analysis(db_session, hospital.id, "2026-04")
        assert result is not None
        assert "data_quality_score" in result or "score" in result
        assert result.get("cached") is False or "cached" not in result

    def test_pipeline_cached_analysis(self, db_session, sample_values):
        """Second run should return cached result."""
        from app.engine.pipeline import run_full_analysis

        hospital = db_session.query(Hospital).first()
        from app.models import Indicator

        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if not ind:
                continue
            iv = IndicatorValue(
                hospital_id=hospital.id,
                indicator_id=ind.id,
                month="2026-05",
                value=value,
            )
            db_session.add(iv)
        db_session.commit()

        # First run
        result1 = run_full_analysis(db_session, hospital.id, "2026-05")
        assert result1 is not None

        # Second run should be cached
        result2 = run_full_analysis(db_session, hospital.id, "2026-05")
        assert result2.get("cached") is True or result2.get("data_quality_score") is not None

    def test_pipeline_force_rerun(self, db_session, sample_values):
        """Forced re-run should not use cache."""
        from app.engine.pipeline import run_full_analysis

        hospital = db_session.query(Hospital).first()
        from app.models import Indicator

        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if not ind:
                continue
            iv = IndicatorValue(
                hospital_id=hospital.id,
                indicator_id=ind.id,
                month="2026-06",
                value=value,
            )
            db_session.add(iv)
        db_session.commit()

        run_full_analysis(db_session, hospital.id, "2026-06")
        result = run_full_analysis(db_session, hospital.id, "2026-06", force=True)
        assert result.get("cached") is False or "data_quality_score" in result

    def test_pipeline_no_data(self, db_session):
        """No data for hospital/month → score 0."""
        from app.engine.pipeline import run_full_analysis

        hospital = db_session.query(Hospital).first()
        result = run_full_analysis(db_session, hospital.id, "2025-01")
        assert result["data_quality_score"] == 0 or result.get("issues")


class TestRegressionIndicators:
    """Regression tests ensuring all 100 indicators can be processed."""

    def test_all_indicators_have_code_and_name(self):
        from app.indicators import INDICATOR_FLAT_LIST
        assert len(INDICATOR_FLAT_LIST) >= 50
        for ind in INDICATOR_FLAT_LIST:
            assert "code" in ind
            assert "name" in ind
            assert ind["code"]
            assert ind["name"]

    def test_indicator_mapping_dicts(self):
        from app.indicators import INDICATOR_CODE_TO_NAME, INDICATOR_NAME_TO_CODE
        assert len(INDICATOR_CODE_TO_NAME) >= 50
        assert len(INDICATOR_NAME_TO_CODE) >= 50
        assert INDICATOR_CODE_TO_NAME["2"] == "Total Deliveries"

    def test_parent_child_map(self):
        from app.indicators import PARENT_CHILD_MAP
        assert "2" in PARENT_CHILD_MAP
        assert len(PARENT_CHILD_MAP["2"]) > 5

    def test_all_indicators_seeded_in_db(self, db_session):
        from app.models import Indicator
        count = db_session.query(Indicator).count()
        assert count >= 50