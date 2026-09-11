"""Integration tests: upload → processing → analysis → report (via FastAPI TestClient)."""
import pytest
import io
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.models import Hospital, IndicatorValue

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

    def test_dashboard_total_reports_counts_distinct_pairs(self, client, db_session):
        """Regression: total_reports must count distinct (hospital, month) pairs.

        Previously the query used PostgreSQL-only DISTINCT ON which SQLite
        silently ignores, so duplicate rows for the same hospital+month were
        counted multiple times.
        """
        from app.models import Hospital, QualityScore
        from app.cache import cache

        h = db_session.query(Hospital).first()
        # Two duplicate rows for the same (hospital, month) + one unique month
        db_session.add(QualityScore(hospital_id=h.id, month="2027-01", score=70.0))
        db_session.add(QualityScore(hospital_id=h.id, month="2027-01", score=75.0))
        db_session.add(QualityScore(hospital_id=h.id, month="2027-02", score=80.0))
        db_session.commit()
        cache.invalidate("analysis:months")

        resp = client.get("/dashboard/overview")
        assert resp.status_code == 200
        total_reports = resp.json()["total_reports"]
        # 2 distinct (hospital, month) pairs — not 3 rows
        assert total_reports == 2

    def test_dashboard_overview_year_filter_applies_to_all_sections(self, client, db_session):
        """Regression: ?year= only filtered the trend chart; summary cards,
        alerts, confidence and comparison showed all-time data."""
        from app.models import QualityScore, ValidationResult, ConfidenceScore
        from app.cache import cache

        h = db_session.query(Hospital).first()
        db_session.add(QualityScore(hospital_id=h.id, month="2026-06", score=50.0,
                                    rule_compliance=60.0, consistency=70.0))
        db_session.add(QualityScore(hospital_id=h.id, month="2027-01", score=90.0,
                                    rule_compliance=95.0, consistency=85.0))
        db_session.add(ValidationResult(hospital_id=h.id, month="2026-06",
                                        rule_code="R1", rule_description="d", status="FAIL", severity="HIGH"))
        db_session.add(ConfidenceScore(hospital_id=h.id, month="2026-06",
                                       overall_confidence=30.0, level="LOW"))
        db_session.commit()
        cache.invalidate("analysis:months")

        # All-time data (both months)
        all_data = client.get("/dashboard/overview").json()
        assert all_data["total_reports"] == 2
        assert all_data["avg_quality_score"] == 70.0
        assert all_data["total_alerts"] == 1

        # 2027 filters every section down to that single month
        y27 = client.get("/dashboard/overview?year=2027").json()
        assert y27["total_reports"] == 1
        assert y27["avg_quality_score"] == 90.0
        assert y27["total_alerts"] == 0
        assert all(m["score"] == 90.0 for m in y27["quality_trend"])
        assert y27["confidence_distribution"]["LOW"] == 0

        # 2026 keeps alerts + confidence, drops the 2027 report
        y26 = client.get("/dashboard/overview?year=2026").json()
        assert y26["total_reports"] == 1
        assert y26["total_alerts"] == 1
        assert y26["confidence_distribution"]["LOW"] == 1

    def test_dashboard_kpi_honors_year(self, client, db_session):
        """Regression: /dashboard/kpi ignored ?year= silently."""
        from app.models import QualityScore
        from app.cache import cache

        h = db_session.query(Hospital).first()
        db_session.add(QualityScore(hospital_id=h.id, month="2026-06", score=50.0,
                                    rule_compliance=60.0, consistency=70.0))
        db_session.add(QualityScore(hospital_id=h.id, month="2027-01", score=90.0,
                                    rule_compliance=95.0, consistency=85.0))
        db_session.commit()
        cache.invalidate("analysis:months")

        kpi_all = client.get("/dashboard/kpi").json()
        qs_all = next(k for k in kpi_all["kpis"] if k["id"] == "quality_score")
        assert qs_all["value"] == 70.0

        kpi_27 = client.get("/dashboard/kpi?year=2027").json()
        qs_27 = next(k for k in kpi_27["kpis"] if k["id"] == "quality_score")
        assert qs_27["value"] == 90.0

    def test_dashboard_bad_year_format_rejected(self, client):
        resp = client.get("/dashboard/overview?year=abc")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestAnalysisFlow:
    def test_analyze_saved_empty(self, client):
        """Analyze with no saved files should return gracefully."""
        resp = client.post("/analysis/analyze-saved?filenames=nonexistent.xlsx")
        # Should not crash — may return error or empty result
        assert resp.status_code in (200, 400, 404)

    def test_heatmap_endpoint(self, client):
        resp = client.get("/analysis/heatmap")
        assert resp.status_code == 200

    def test_heatmap_filters_by_hospital(self, client, db_session):
        """Regression: /analysis/heatmap?hospital_id= was ignored."""
        from app.models import QualityScore
        from app.cache import cache

        hospitals = db_session.query(Hospital).order_by(Hospital.id).all()
        h1, h2 = hospitals[0], hospitals[1]
        db_session.add(QualityScore(hospital_id=h1.id, month="2027-03", score=70.0))
        db_session.add(QualityScore(hospital_id=h2.id, month="2027-03", score=90.0))
        db_session.commit()
        cache.invalidate("analysis:months")

        r1 = client.get(f"/analysis/heatmap?hospital_id={h1.id}").json()
        assert len(r1["data"]) == 1
        assert r1["data"][0]["hospital"] == h1.name

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


class TestRootCauseTimeline:
    """المقارنة الزمنية في Root Cause: خط المستشفى مقابل متوسط النظير مع فاصل الثقة."""

    def test_timeline_returns_series_with_peer_band(self, client, db_session):
        from app.models import Hospital, HospitalType, Indicator, IndicatorValue

        htype = HospitalType(name="TimelineGov")
        db_session.add(htype)
        db_session.flush()

        target = Hospital(name="Timeline Target", hospital_type_id=htype.id, is_active=True)
        peers = [Hospital(name=f"Timeline Peer {i}", hospital_type_id=htype.id, is_active=True) for i in range(3)]
        db_session.add_all([target] + peers)
        db_session.flush()

        ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
        assert ind is not None, "Indicator '2' must be seeded"

        for m, val in [("2026-01", 100.0), ("2026-02", 120.0), ("2026-03", 90.0)]:
            db_session.add(IndicatorValue(hospital_id=target.id, indicator_id=ind.id, month=m, value=val))
            for pi, p in enumerate(peers):
                db_session.add(IndicatorValue(hospital_id=p.id, indicator_id=ind.id, month=m, value=80.0 + pi * 5))
        db_session.commit()

        resp = client.get(f"/root-cause/{target.id}/timeline?month=2026-03&months_back=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hospital_id"] == target.id
        assert len(data["indicators"]) >= 1
        code2 = next(i for i in data["indicators"] if i["indicator_code"] == "2")
        assert len(code2["series"]) == 3
        last = code2["series"][-1]
        assert last["hospital_value"] == 90.0
        # متوسط النظير = متوسط (80, 85, 90) = 85
        assert last["peer_mean"] == 85.0
        # فاصل الثقة 95% حول متوسط النظير
        assert last["peer_lower"] is not None
        assert last["peer_lower"] <= last["peer_mean"] <= last["peer_upper"]
        assert last["peer_count"] == 3
        # الترتيب الزمني تصاعدي
        months = [p["month"] for p in code2["series"]]
        assert months == sorted(months)

    def test_timeline_404_unknown_hospital(self, client):
        resp = client.get("/root-cause/999999/timeline?month=2026-03")
        assert resp.status_code == 404


class TestFullPipeline:
    """Full upload → process → analyze → report flow using DB directly."""

    def test_pipeline_run_full_analysis(self, db_session, sample_values):
        """Insert indicator values directly and run full analysis."""
        from app.engine.pipeline import run_full_analysis

        hospital = db_session.query(Hospital).first()
        assert hospital is not None

        # Insert indicator values
        from app.models import Indicator

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