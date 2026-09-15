"""Tests for the pipeline orchestrator (engine.pipeline)."""
import pytest
from sqlalchemy import text
from app.engine.pipeline import (
    run_full_analysis,
    get_values_for_hospital_month,
    get_enabled_values_for_hospital_month,
    get_disabled_indicator_ids,
    get_all_hospital_data_for_month,
    get_historical_months,
    check_analysis_exists,
)
from app.models import Hospital, Indicator, IndicatorValue, HospitalIndicatorConfig, QualityScore, SystemSetting


class TestGetValuesForHospitalMonth:
    def test_returns_values_for_existing_data(self, db_session):
        hospital = db_session.query(Hospital).first()
        ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
        iv = IndicatorValue(hospital_id=hospital.id, indicator_id=ind.id, month="2026-04", value=300)
        db_session.add(iv)
        db_session.commit()

        values = get_values_for_hospital_month(db_session, hospital.id, "2026-04")
        assert "2" in values
        assert values["2"] == 300

    def test_returns_empty_for_no_data(self, db_session):
        hospital = db_session.query(Hospital).first()
        values = get_values_for_hospital_month(db_session, hospital.id, "2099-01")
        assert values == {}

    def test_excludes_null_values(self, db_session):
        hospital = db_session.query(Hospital).first()
        ind2 = db_session.query(Indicator).filter(Indicator.code == "2").first()
        ind3 = db_session.query(Indicator).filter(Indicator.code == "3").first()
        db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind2.id, month="2026-04", value=300))
        db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind3.id, month="2026-04", value=None))
        db_session.commit()

        values = get_values_for_hospital_month(db_session, hospital.id, "2026-04")
        assert "2" in values
        assert "3" not in values


class TestGetEnabledValuesForHospitalMonth:
    def test_excludes_manually_disabled(self, db_session):
        hospital = db_session.query(Hospital).first()
        ind2 = db_session.query(Indicator).filter(Indicator.code == "2").first()
        ind3 = db_session.query(Indicator).filter(Indicator.code == "3").first()
        db_session.add_all([
            IndicatorValue(hospital_id=hospital.id, indicator_id=ind2.id, month="2026-04", value=300),
            IndicatorValue(hospital_id=hospital.id, indicator_id=ind3.id, month="2026-04", value=200),
        ])
        db_session.add(HospitalIndicatorConfig(hospital_id=hospital.id, indicator_id=ind3.id, is_enabled=False))
        db_session.commit()

        values = get_enabled_values_for_hospital_month(db_session, hospital.id, "2026-04")
        assert "2" in values
        assert "3" not in values

    def test_returns_all_when_all_enabled(self, db_session):
        hospital = db_session.query(Hospital).first()
        ind2 = db_session.query(Indicator).filter(Indicator.code == "2").first()
        ind3 = db_session.query(Indicator).filter(Indicator.code == "3").first()
        db_session.add_all([
            IndicatorValue(hospital_id=hospital.id, indicator_id=ind2.id, month="2026-04", value=300),
            IndicatorValue(hospital_id=hospital.id, indicator_id=ind3.id, month="2026-04", value=200),
        ])
        db_session.commit()

        values = get_enabled_values_for_hospital_month(db_session, hospital.id, "2026-04")
        assert values["2"] == 300
        assert values["3"] == 200


class TestGetDisabledIndicatorIds:
    def test_returns_manually_disabled(self, db_session):
        hospital = db_session.query(Hospital).first()
        ind3 = db_session.query(Indicator).filter(Indicator.code == "3").first()
        db_session.add(HospitalIndicatorConfig(hospital_id=hospital.id, indicator_id=ind3.id, is_enabled=False))
        db_session.commit()

        disabled = get_disabled_indicator_ids(db_session, hospital.id, "2026-04")
        assert ind3.id in disabled

    def test_returns_empty_when_nothing_disabled(self, db_session):
        hospital = db_session.query(Hospital).first()
        disabled = get_disabled_indicator_ids(db_session, hospital.id, "2026-04")
        assert disabled == []

    def test_auto_disable_null_when_enabled(self, db_session):
        hospital = db_session.query(Hospital).first()
        ind2 = db_session.query(Indicator).filter(Indicator.code == "2").first()
        ind3 = db_session.query(Indicator).filter(Indicator.code == "3").first()
        # Only indicator 2 has a value; indicator 3 has no row
        db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind2.id, month="2026-04", value=300))
        db_session.add(SystemSetting(key="auto_disable_null_indicators", value="true"))
        db_session.commit()

        disabled = get_disabled_indicator_ids(db_session, hospital.id, "2026-04")
        assert ind3.id in disabled


class TestGetAllHospitalDataForMonth:
    def test_aggregates_all_hospitals(self, db_session):
        hospitals = db_session.query(Hospital).all()
        ind2 = db_session.query(Indicator).filter(Indicator.code == "2").first()
        for h in hospitals:
            db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=ind2.id, month="2026-04", value=100))
        db_session.commit()

        data = get_all_hospital_data_for_month(db_session, "2026-04")
        assert len(data) >= 3
        for h in hospitals:
            assert h.name in data
            assert data[h.name]["2"] == 100

    def test_excludes_hospitals_with_no_data(self, db_session):
        data = get_all_hospital_data_for_month(db_session, "2099-01")
        assert data == {}


class TestGetHistoricalMonths:
    def test_returns_other_months(self, db_session):
        hospital = db_session.query(Hospital).first()
        ind2 = db_session.query(Indicator).filter(Indicator.code == "2").first()
        for m in ["2026-01", "2026-02", "2026-03"]:
            db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind2.id, month=m, value=100))
        db_session.commit()

        historical = get_historical_months(db_session, hospital.id, "2026-04")
        assert "2026-01" in historical
        assert "2026-02" in historical
        assert "2026-03" in historical

    def test_excludes_current_month(self, db_session):
        hospital = db_session.query(Hospital).first()
        ind2 = db_session.query(Indicator).filter(Indicator.code == "2").first()
        db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind2.id, month="2026-04", value=100))
        db_session.commit()

        historical = get_historical_months(db_session, hospital.id, "2026-04")
        assert "2026-04" not in historical


class TestCheckAnalysisExists:
    def test_returns_false_when_no_analysis(self, db_session):
        hospital = db_session.query(Hospital).first()
        assert check_analysis_exists(db_session, hospital.id, "2026-04") is False

    def test_returns_true_when_analysis_exists(self, db_session, sample_values):
        from app.engine.pipeline import run_full_analysis
        hospital = db_session.query(Hospital).first()
        ind2 = db_session.query(Indicator).filter(Indicator.code == "2").first()
        db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind2.id, month="2026-04", value=300))
        db_session.commit()

        run_full_analysis(db_session, hospital.id, "2026-04")
        assert check_analysis_exists(db_session, hospital.id, "2026-04") is True


class TestRunFullAnalysis:
    def test_hospital_not_found_raises(self, db_session):
        with pytest.raises(ValueError, match="not found"):
            run_full_analysis(db_session, 99999, "2026-04")

    def test_no_data_returns_zero_score(self, db_session):
        hospital = db_session.query(Hospital).first()
        result = run_full_analysis(db_session, hospital.id, "2025-01")
        assert result["data_quality_score"] == 0
        assert "No data found" in str(result.get("issues", []))

    def test_with_data_returns_score_and_outliers(self, db_session, sample_values):
        hospital = db_session.query(Hospital).first()
        from app.models import Indicator

        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if ind:
                db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind.id, month="2026-04", value=value))
        db_session.commit()

        result = run_full_analysis(db_session, hospital.id, "2026-04")
        assert "data_quality_score" in result
        assert "outliers" in result
        assert isinstance(result["outliers"], list)
        assert "confidence" in result
        assert result["cached"] is False

    def test_cached_result_returns_early(self, db_session, sample_values):
        hospital = db_session.query(Hospital).first()
        from app.models import Indicator

        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if ind:
                db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind.id, month="2026-07", value=value))
        db_session.commit()

        run_full_analysis(db_session, hospital.id, "2026-07")
        cached = run_full_analysis(db_session, hospital.id, "2026-07")
        assert cached["cached"] is True

    def test_force_bypasses_cache(self, db_session, sample_values):
        hospital = db_session.query(Hospital).first()
        from app.models import Indicator

        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if ind:
                db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind.id, month="2026-08", value=value))
        db_session.commit()

        run_full_analysis(db_session, hospital.id, "2026-08")
        forced = run_full_analysis(db_session, hospital.id, "2026-08", force=True)
        assert forced["cached"] is False

    def test_result_contains_confidence_section(self, db_session, sample_values):
        hospital = db_session.query(Hospital).first()
        from app.models import Indicator

        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if ind:
                db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind.id, month="2026-09", value=value))
        db_session.commit()

        result = run_full_analysis(db_session, hospital.id, "2026-09")
        conf = result["confidence"]
        assert "overall_confidence" in conf
        assert "level" in conf
        assert "by_level" in conf
        assert "by_group" in conf
        assert "priority_verify" in conf
        assert "summary" in conf

    def test_result_contains_quality_components(self, db_session, sample_values):
        hospital = db_session.query(Hospital).first()
        from app.models import Indicator

        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if ind:
                db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind.id, month="2026-10", value=value))
        db_session.commit()

        result = run_full_analysis(db_session, hospital.id, "2026-10")
        assert "rule_compliance" in result
        assert "completeness" in result
        assert "consistency" in result
        assert "outlier_penalty" in result
        assert "issues" in result


class TestAnalysisFailureRecovery:
    """Regression tests for the settings-screen re-analysis 500:
    'This Session's transaction has been rolled back due to a previous
    exception' (psycopg2 UndefinedColumn on anomaly_results.peer_*)."""

    def test_failed_save_rolls_back_and_still_persists_fallback(self, db_session, monkeypatch, sample_values):
        """A failing save step (e.g. UndefinedColumn) must not poison the
        session: run_full_analysis rolls back before the fallback save, so a
        0-score QualityReport row is still persisted and the session stays
        usable for the next hospital/month."""
        from app.engine import pipeline

        hospital = db_session.query(Hospital).first()
        for code, value in sample_values.items():
            ind = db_session.query(Indicator).filter(Indicator.code == code).first()
            if ind:
                db_session.add(IndicatorValue(hospital_id=hospital.id, indicator_id=ind.id, month="2026-04", value=value))
        db_session.commit()

        def poisoned_save(session, hospital_id, month, results):
            # Simulate PostgreSQL aborting the transaction: once a statement
            # fails there, every later statement raises until ROLLBACK.
            # SQLAlchemy reproduces the exact user-facing error
            # (PendingRollbackError) for any subsequent use of the session.
            try:
                session.execute(text("SELECT * FROM no_such_table_xyz"))
            except Exception:
                pass
            raise RuntimeError("simulated UndefinedColumn: column \"peer_count\" does not exist")

        monkeypatch.setattr(pipeline, "_save_anomaly_results", poisoned_save)

        result = run_full_analysis(db_session, hospital.id, "2026-04")

        assert result["data_quality_score"] == 0
        # Fallback report persisted (impossible while the session is poisoned)
        qs = db_session.query(QualityScore).filter_by(hospital_id=hospital.id, month="2026-04").first()
        assert qs is not None and qs.score == 0
        # Session remains usable
        assert db_session.query(Hospital).count() >= 1

    def test_reanalyze_loop_recovers_and_surfaces_errors(self, db_session, monkeypatch):
        """The bulk re-analysis loop must roll back after a failed month and
        still analyze the remaining months, then raise a summary so the task
        is reported as failed instead of silently 'done'."""
        import app.api.analysis as analysis_api

        hospital = db_session.query(Hospital).first()
        monkeypatch.setattr(analysis_api, "get_enabled_months", lambda db, hospital_id=None: ["2026-01", "2026-02"])
        monkeypatch.setattr(analysis_api, "SessionLocal", lambda: db_session)

        class _FakeCache:
            def invalidate(self, *a, **k):
                pass

        monkeypatch.setattr(analysis_api, "cache", _FakeCache())

        state = {"attempted": [], "session_ok_second_month": False}

        def fake_analysis(session, hospital_id, month, force=False):
            state["attempted"].append(month)
            if month == "2026-01":
                try:
                    session.execute(text("SELECT * FROM no_such_table_xyz"))
                except Exception:
                    pass
                raise RuntimeError("simulated UndefinedColumn: peer_count")
            # Second month: proves the loop rolled the session back — a
            # poisoned session raises PendingRollbackError here.
            session.execute(text("SELECT 1")).all()
            state["session_ok_second_month"] = True
            return {"ok": True}

        monkeypatch.setattr(analysis_api, "run_full_analysis", fake_analysis)

        with pytest.raises(RuntimeError, match="1 of 2 analyses failed"):
            analysis_api._run_reanalyze_all([hospital], True)

        assert state["attempted"] == ["2026-01", "2026-02"]  # loop continued
        assert state["session_ok_second_month"] is True
        db_session.rollback()
        assert db_session.query(Hospital).count() >= 1  # session reusable
