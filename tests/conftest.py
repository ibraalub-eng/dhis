"""Shared test fixtures for HEALTH-ai backend tests."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.core.deps import get_current_user
from app.models import Hospital
from scripts.seed_indicators import seed_indicators
from scripts.seed_rules import seed_rules
from scripts.seed_menu import seed_menu  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_production_db(db_session, monkeypatch):
    """Keep pytest off the production database and uploads folder.

    Background workers (process-preview, upload-multiple-analyze) build their
    own session via ``SessionLocal`` in fresh threads — the get_db dependency
    override does NOT cover them. Without this fixture a single test run
    imports fixture rows ("Al-Shifa Hospital", formerly "Test Hospital")
    into the real Postgres and leaves poison files in data/uploads/ that
    resurrect the ghost hospital on the next run.

    Two defenses:
    1. Every module-level ``SessionLocal`` binding is redirected to a
       sessionmaker bound to the test engine (lazy ``from app.database
       import SessionLocal`` inside functions resolves through
       app.database, which is patched too).
    2. Files newly created in data/uploads/ during a test are removed on
       teardown (best-effort, never fails the test).
    """
    import os
    from app import database as _database

    test_sessionmaker = sessionmaker(bind=db_session.get_bind())

    import app.api.admin as _admin
    import app.api.analysis as _analysis
    import app.api.file_ops as _file_ops
    import app.api.reports as _reports
    import app.main as _main
    for mod in (_database, _admin, _analysis, _file_ops, _reports, _main):
        if hasattr(mod, "SessionLocal"):
            monkeypatch.setattr(mod, "SessionLocal", test_sessionmaker)

    uploads_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
    )
    # Known test-residue patterns: files the suite itself writes (or wrote
    # before isolation existed). Removed at setup so a leftover poison file
    # can never be re-processed against production again.
    import fnmatch
    residue_patterns = ("unit_*", "test_*", "*_test*", "preview_test*", "preview_qr*", "integration_*", "to_update.xlsx")
    if os.path.isdir(uploads_dir):
        for name in os.listdir(uploads_dir):
            if any(fnmatch.fnmatch(name, p) for p in residue_patterns):
                try:
                    os.remove(os.path.join(uploads_dir, name))
                except OSError:
                    pass
    before = set(os.listdir(uploads_dir)) if os.path.isdir(uploads_dir) else set()
    yield
    try:
        after = set(os.listdir(uploads_dir)) if os.path.isdir(uploads_dir) else set()
        import shutil
        import time
        for name in after - before:
            path = os.path.join(uploads_dir, name)
            for _ in range(10):  # Windows releases handles asynchronously
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    break
                except OSError:
                    time.sleep(0.2)
    except Exception:
        pass


class _FakeSuperAdmin:
    """Minimal superadmin stub for test auth bypass."""
    id = 99999
    username = "testadmin"
    email = "test@test.local"
    full_name = "Test Admin"
    is_active = True
    is_superuser = True
    roles = []


@pytest.fixture(autouse=True)
def _bypass_auth(app, db_session):
    """Override get_current_user so all existing tests pass without JWT tokens.

    Auth-specific tests in test_auth.py use their own client fixture
    that does NOT override get_current_user, so they test real auth.
    """
    def override_get_user():
        return _FakeSuperAdmin()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_current_user] = override_get_user
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def app():
    """Provide the FastAPI app instance for dependency override tests."""
    from app.main import app as _app
    return _app


@pytest.fixture(autouse=True)
def _redirect_xgb_model_dir(tmp_path_factory, monkeypatch):
    """منع كتابة نماذج XGBoost في مجلد data/models الحقيقي أثناء الاختبارات.

    كل اختبار يستدعي run_xgboost_predictions قد يحفظ النموذج؛ نُعيد توجيه
    MODEL_DIR إلى مجلد مؤقت لتبقى الاختبارات معزولة ولا تُلوّث المستودع.
    """
    from app.engine.smart import xgboost_predictor
    model_dir = tmp_path_factory.mktemp("xgb_models")
    monkeypatch.setattr(xgboost_predictor, "MODEL_DIR", str(model_dir))


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path_factory, monkeypatch):
    """Point the TTLCache's file layer at a temp dir for every test.

    The live app and pytest both persist to data/cache — without this
    isolation a test run leaked fixture months ("2027-01") and fixture
    hospitals into the LIVE cache files, which the running app then served:
    real months silently vanished from the Quality Score Trend and the
    month/year dropdowns for up to 24h after every pytest run.

    _CACHE_DIR is read at CALL time from the module global, so patching it
    redirects every cache instance (app modules bind the instance by
    reference via `from app.cache import cache` — replacing the attribute
    would not reach them). The in-memory dict of the shared instance is
    cleared so entries from a previous test cannot leak into this one.
    """
    import app.cache as cache_mod
    test_dir = str(tmp_path_factory.mktemp("test_cache"))
    monkeypatch.setattr(cache_mod, "_CACHE_DIR", test_dir)
    # Freeze the data epoch: the fingerprint queries the REAL database,
    # which tests must not touch (and each test's in-memory SQLite differs
    # anyway). Patching compute_data_epoch (not get_data_epoch) keeps the
    # real lazy-compute/interval-refresh logic live in every code path while
    # making the fingerprint a deterministic constant.
    monkeypatch.setattr(cache_mod, "compute_data_epoch", lambda: "test-epoch")
    monkeypatch.setattr(cache_mod, "_data_epoch", None)
    cache_mod.cache._cache.clear()
    yield
    cache_mod.cache._cache.clear()


@pytest.fixture
def db_session():
    """File-backed SQLite session with schema seeded.

    File-backed (not :memory:+StaticPool) because background workers run in
    separate threads with their OWN connections via the redirected
    SessionLocal — a single StaticPool connection shared across threads
    segfaults the interpreter (native sqlite3 access violation).
    """
    import tempfile
    _tmpdir = tempfile.mkdtemp(prefix="healthai_test_db_")
    engine = create_engine(
        f"sqlite:///{_tmpdir}/test.db",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        seed_indicators(session)
        _seed_hospitals(session)
        seed_rules(session)
        seed_menu(session)
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