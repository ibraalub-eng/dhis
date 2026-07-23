import pytest
import numpy as np
from app.engine.smart.xgboost_predictor import (
    run_xgboost_predictions,
    _normalize_scores,
)
from app.engine.smart.schemas import (
    XGBoostPredictionResult,
    XGBoostPrediction,
    XGBoostDriver,
    XGBoostGlobalExplanation,
)


class TestNormalizeScores:
    def test_basic_normalization(self):
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _normalize_scores(scores)
        assert result[0] == pytest.approx(0.0)
        assert result[-1] == pytest.approx(1.0)

    def test_constant_scores(self):
        scores = np.array([3.0, 3.0, 3.0])
        result = _normalize_scores(scores)
        assert all(r == pytest.approx(0.0) for r in result)

    def test_single_value(self):
        scores = np.array([5.0])
        result = _normalize_scores(scores)
        assert result[0] == pytest.approx(0.0)


class TestXGBoostSchemas:
    def test_prediction_dataclass(self):
        p = XGBoostPrediction(
            hospital_name="Test Hospital",
            hospital_id=1,
            current_score=0.4,
            predicted_next_score=0.5,
            predicted_severity="warning",
            risk_change="increasing",
            confidence=0.85,
            top_drivers=[],
        )
        assert p.hospital_name == "Test Hospital"
        assert p.predicted_severity == "warning"
        assert p.confidence == 0.85

    def test_driver_dataclass(self):
        d = XGBoostDriver(
            feature="cs_rate",
            arabic_label="معدل القيصارية",
            shap_value=0.15,
            direction="increases_risk",
            magnitude="medium",
        )
        assert d.feature == "cs_rate"
        assert d.shap_value == 0.15

    def test_global_explanation_dataclass(self):
        g = XGBoostGlobalExplanation(
            feature="cs_rate",
            arabic_label="معدل القيصارية",
            mean_abs_shap=0.234,
            rank=1,
        )
        assert g.rank == 1
        assert g.mean_abs_shap == 0.234


class TestXGBoostPredictionResult:
    def test_empty_result_insufficient_data(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        result = run_xgboost_predictions(session, "2026-06", {"xgboost_enabled": True})
        assert isinstance(result, XGBoostPredictionResult)
        assert result.hospitals_trained == 0
        assert len(result.predictions) == 0
        assert "Not enough" in result.accuracy_note
        session.close()

    def test_result_with_db_has_months(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue, QualityScore
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="Gaza", id=1)
        ht = HospitalType(name="general", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 8):
            h = Hospital(id=i, name=f"Hospital {i}", governorate_id=1, hospital_type_id=1, is_active=True)
            session.add(h)
        session.flush()

        indicators = []
        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            ind = Indicator(id=idx, code=code, name=f"ind_{code}")
            indicators.append(ind)
        session.add_all(indicators)
        session.flush()

        months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
        for month in months:
            for hosp_id in range(1, 8):
                for ind in indicators:
                    val = IndicatorValue(
                        hospital_id=hosp_id,
                        indicator_id=ind.id,
                        month=month,
                        value=random.uniform(1, 50),
                    )
                    session.add(val)
        session.flush()

        result = run_xgboost_predictions(session, "2026-05", {
            "xgboost_enabled": True,
            "xgb_n_estimators": 50,
            "xgb_max_depth": 3,
        })
        assert isinstance(result, XGBoostPredictionResult)
        assert result.training_months == 5
        assert result.hospitals_trained == 7
        assert len(result.predictions) == 7
        assert len(result.global_feature_importance) > 0
        for pred in result.predictions:
            assert pred.predicted_severity in ("normal", "warning", "critical")
            assert pred.risk_change in ("increasing", "decreasing", "stable")
            assert 0.0 <= pred.predicted_next_score <= 1.0
            assert 0.0 <= pred.confidence <= 1.0
        session.close()

    def test_predictions_sorted_by_score_desc(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="Gaza", id=1)
        ht = HospitalType(name="general", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 8):
            h = Hospital(id=i, name=f"Hospital {i}", governorate_id=1, hospital_type_id=1, is_active=True)
            session.add(h)
        session.flush()

        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            session.add(Indicator(id=idx, code=code, name=f"ind_{code}"))
        session.flush()

        for month in ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]:
            for hosp_id in range(1, 8):
                for ind_id in range(1, 13):
                    session.add(IndicatorValue(hospital_id=hosp_id, indicator_id=ind_id, month=month, value=random.uniform(1, 50)))
        session.flush()

        result = run_xgboost_predictions(session, "2026-05", {"xgb_n_estimators": 30, "xgb_max_depth": 2})
        for i in range(len(result.predictions) - 1):
            assert result.predictions[i].predicted_next_score >= result.predictions[i + 1].predicted_next_score
        session.close()

    def test_driver_count_per_prediction(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="North Gaza", id=1)
        ht = HospitalType(name="specialist", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 8):
            session.add(Hospital(id=i, name=f"Hosp {i}", governorate_id=1, hospital_type_id=1, is_active=True))
        session.flush()

        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            session.add(Indicator(id=idx, code=code, name=f"ind_{code}"))
        session.flush()

        for month in ["2026-01", "2026-02", "2026-03"]:
            for hosp_id in range(1, 8):
                for ind_id in range(1, 13):
                    session.add(IndicatorValue(hospital_id=hosp_id, indicator_id=ind_id, month=month, value=random.uniform(1, 50)))
        session.flush()

        result = run_xgboost_predictions(session, "2026-03", {"xgb_n_estimators": 20})
        for pred in result.predictions:
            assert len(pred.top_drivers) <= 5
            for d in pred.top_drivers:
                assert d.direction in ("increases_risk", "decreases_risk")
                assert d.magnitude in ("high", "medium", "low")
        session.close()

    def test_global_feature_importance_ranked(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="Khan Younis", id=1)
        ht = HospitalType(name="general", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 8):
            session.add(Hospital(id=i, name=f"H {i}", governorate_id=1, hospital_type_id=1, is_active=True))
        session.flush()

        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            session.add(Indicator(id=idx, code=code, name=f"ind_{code}"))
        session.flush()

        for month in ["2026-01", "2026-02", "2026-03", "2026-04"]:
            for hosp_id in range(1, 8):
                for ind_id in range(1, 13):
                    session.add(IndicatorValue(hospital_id=hosp_id, indicator_id=ind_id, month=month, value=random.uniform(1, 50)))
        session.flush()

        result = run_xgboost_predictions(session, "2026-04", {"xgb_n_estimators": 25})
        assert len(result.global_feature_importance) <= 12
        ranks = [fi.rank for fi in result.global_feature_importance]
        assert ranks == sorted(ranks)
        for fi in result.global_feature_importance:
            assert fi.mean_abs_shap >= 0
        session.close()

    def test_model_metrics_are_numeric(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Base
        from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue
        import random

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        gov = Governorate(name="Rafah", id=1)
        ht = HospitalType(name="maternity", id=1)
        session.add_all([gov, ht])
        session.flush()

        for i in range(1, 6):
            session.add(Hospital(id=i, name=f"H{i}", governorate_id=1, hospital_type_id=1, is_active=True))
        session.flush()

        for idx, code in enumerate(["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"], start=1):
            session.add(Indicator(id=idx, code=code, name=f"i_{code}"))
        session.flush()

        for month in ["2026-01", "2026-02"]:
            for hosp_id in range(1, 6):
                for ind_id in range(1, 13):
                    session.add(IndicatorValue(hospital_id=hosp_id, indicator_id=ind_id, month=month, value=random.uniform(0.1, 100)))
        session.flush()

        result = run_xgboost_predictions(session, "2026-02", {"xgb_n_estimators": 15})
        assert isinstance(result.model_r2, float)
        assert isinstance(result.model_mae, float)
        assert result.model_mae >= 0
        session.close()
