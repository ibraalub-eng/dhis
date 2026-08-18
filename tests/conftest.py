"""Shared test fixtures for HEALTH-ai backend tests."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Hospital
from scripts.seed_indicators import seed_indicators
from scripts.seed_rules import seed_rules


@pytest.fixture(autouse=True)
def _redirect_xgb_model_dir(tmp_path_factory, monkeypatch):
    """منع كتابة نماذج XGBoost في مجلد data/models الحقيقي أثناء الاختبارات.

    كل اختبار يستدعي run_xgboost_predictions قد يحفظ النموذج؛ نُعيد توجيه
    MODEL_DIR إلى مجلد مؤقت لتبقى الاختبارات معزولة ولا تُلوّث المستودع.
    """
    from app.engine.smart import xgboost_predictor
    model_dir = tmp_path_factory.mktemp("xgb_models")
    monkeypatch.setattr(xgboost_predictor, "MODEL_DIR", str(model_dir))


@pytest.fixture
def db_session():
    """In-memory SQLite session with schema seeded. Thread-safe for TestClient."""
    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        seed_indicators(session)
        _seed_hospitals(session)
        seed_rules(session)
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_hospitals(session):
    hospitals = [
        Hospital(name="General Hospital", region="Region A"),
        Hospital(name="Central Medical", region="Region B"),
        Hospital(name="Community Clinic", region="Region A"),
    ]
    for h in hospitals:
        session.add(h)
    session.flush()


@pytest.fixture
def sample_values():
    """Realistic indicator values for a hospital with good data quality."""
    return {
        "2": 300, "2.a": 120, "2.b": 180, "3": 200, "4": 20, "4.a": 18, "4.b": 2,
        "5": 80, "5.a": 20, "5.b": 60, "5.b.1": 45, "5.b.2": 15,
        "6": 280, "6.a": 140, "6.b": 135, "6.c": 5,
        "7": 10, "7.a": 7, "7.b": 3,
        "8": 2, "8.a": 1, "8.b": 1,
        "9": 1,
        "10": 15, "10.a": 8, "10.b": 4, "10.c": 2, "10.d": 1,
        "11": 1, "12": 3, "13": 2, "14": 1,
        "16": 12, "16.a": 8, "16.b": 2, "16.c": 2,
        "17": 5, "17.a": 3, "17.b": 2,
        "18": 1, "18.a": 1,
    }


@pytest.fixture
def sample_values_minimal():
    """Minimal values with only key indicators."""
    return {
        "2": 100, "3": 70, "4": 10, "5": 20, "6": 95,
        "7": 3, "10": 5, "11": 0, "16": 4, "17": 2,
    }


@pytest.fixture
def sample_values_empty():
    """Empty values dict, simulating no data uploaded."""
    return {}


@pytest.fixture
def all_hospital_data(sample_values, sample_values_minimal):
    """Multi-hospital data for cross-hospital comparison."""
    return {
        "General Hospital": sample_values,
        "Central Medical": sample_values_minimal,
        "Community Clinic": {
            "2": 250, "3": 160, "4": 15, "5": 75, "6": 235,
            "7": 8, "10": 12, "11": 1, "16": 8, "17": 4,
        },
    }


@pytest.fixture
def historical_data(sample_values, sample_values_minimal):
    """Monthly historical data for trend analysis (3 months)."""
    return {
        "2026-01": {
            "2": 280, "3": 190, "4": 18, "5": 72, "6": 260,
            "7": 8, "10": 10, "11": 0, "16": 8, "17": 4,
        },
        "2026-02": {
            "2": 290, "3": 195, "4": 19, "5": 76, "6": 270,
            "7": 9, "10": 12, "11": 1, "16": 10, "17": 5,
        },
        "2026-03": sample_values_minimal,
    }