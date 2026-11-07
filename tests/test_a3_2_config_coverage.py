"""A3.2 - decision-affecting configuration coverage (pinned facts).

Investigation-phase tests. They pin the CURRENT semantics of the three
settings A3.2 examined, so a later integration phase cannot move them
silently:

  * ``auto_disable_null_indicators`` - one stored value, six readers, literal
    ``"true"`` parsing, and a writer that stores any string it is given;
  * ``smart_analytics`` - 15 seeded keys, 2 seeded but unconsumed, 2 consumed
    but unseeded, and no coercion in ``_load_config``;
  * ``anomaly_drift_months`` - default 3, clamped to 2..6, truncated on read.

Nothing here changes production behaviour. Every test reads a temporary
SQLite session, renders a stored artefact (seed registry, source text) or
calls a pure function with ``enabled=False``. No consumer is modified and no
production database is touched.

When a later phase moves any of these settings into the resolver, the
assertions in ``test_resolver_covers_none_of_the_three_settings`` must be
updated deliberately - that is the point of pinning the gap.
"""
from pathlib import Path

import pytest

from app.database import get_db
from app.engine import config_resolver as cr
from app.main import APP_CONFIG_DEFAULTS
from app.models import AppConfig, SystemSetting

ROOT = Path(__file__).resolve().parents[1]
SMART_DIR = ROOT / "app" / "engine" / "smart"

#: Exactly the ``smart_analytics`` rows ``APP_CONFIG_DEFAULTS`` seeds.
SEEDED_SMART_DEFAULTS = {
    "smart_enabled": 1.0,
    "smart_contamination": 0.05,
    "smart_lof_neighbors": 5.0,
    "smart_dbscan_eps": 1.5,
    "smart_dbscan_min_samples": 3.0,
    "smart_threshold_green": 0.3,
    "smart_threshold_yellow": 0.6,
    "smart_shap_enabled": 1.0,
    "smart_ensemble_if_weight": 0.35,
    "smart_ensemble_lof_weight": 0.3,
    "smart_ensemble_mahal_weight": 0.2,
    "smart_ensemble_residual_weight": 0.15,
    "smart_xgboost_enabled": 1.0,
    "smart_xgb_n_estimators": 100.0,
    "smart_xgb_max_depth": 4.0,
}

#: Keys a consumer reads, each with an inline default at its read site.
CONSUMED_WITH_INLINE_DEFAULT = (
    "enabled",
    "contamination",
    "lof_neighbors",
    "dbscan_eps",
    "dbscan_min_samples",
    "threshold_green",
    "threshold_yellow",
    "shap_enabled",
    "ensemble_if_weight",
    "ensemble_lof_weight",
    "ensemble_mahal_weight",
    "ensemble_residual_weight",
    "xgboost_enabled",
    "fdr_q",
    "pattern_min_support",
)


def _smart_sources():
    return {p.name: p.read_text(encoding="utf-8") for p in SMART_DIR.glob("*.py")}


def _app(db, key, value, category="smart_analytics"):
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if row is None:
        db.add(AppConfig(key=key, value=float(value), category=category,
                         label=key))
    else:
        row.value = float(value)
    db.commit()


def _setting(db, key, value):
    db.add(SystemSetting(key=key, value=value))
    db.commit()


@pytest.fixture
def client(db_session):
    """Minimal client bound to the temp SQLite session (same as test_api_config)."""
    from fastapi.testclient import TestClient
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---- smart_analytics: seed registry ---------------------------------------
def test_seeded_smart_registry_is_exactly_the_documented_fifteen():
    seeded = {
        key: value for key, value, category, _label in APP_CONFIG_DEFAULTS
        if category == "smart_analytics"
    }
    assert seeded == SEEDED_SMART_DEFAULTS


def test_consumed_but_unseeded_keys_have_no_seed_row():
    """``fdr_q`` and ``pattern_min_support`` are consumed with inline
    defaults; neither has a seed row, so neither can be edited in the UI."""
    seeded_keys = {key for key, *_rest in APP_CONFIG_DEFAULTS}
    assert "smart_fdr_q" not in seeded_keys
    assert "smart_pattern_min_support" not in seeded_keys


def test_seeded_but_unconsumed_keys_are_the_two_xgb_tuning_keys():
    """Seeding a value no engine reads is worse than not seeding it: the UI
    shows a knob that cannot change a result."""
    joined = "\n".join(_smart_sources().values())
    for key in ("xgb_n_estimators", "xgb_max_depth"):
        assert key not in joined, key

    from app.engine.smart.xgboost_predictor import ENSEMBLE_CONFIGS
    assert [(c["n_estimators"], c["max_depth"]) for c in ENSEMBLE_CONFIGS] == [
        (80, 3), (150, 5), (200, 7),
    ]


def test_every_consumed_key_is_read_with_an_inline_default():
    """No consumer reads a smart key without declaring its own fallback, so a
    missing row degrades to a known value rather than a crash."""
    joined = "\n".join(_smart_sources().values())
    for key in CONSUMED_WITH_INLINE_DEFAULT:
        assert f'config.get("{key}"' in joined, key


# ---- smart_analytics: storage and coercion -------------------------------
def test_load_config_strips_prefix_and_invents_no_defaults(db_session):
    from app.engine.smart import _load_config

    _app(db_session, "smart_contamination", 0.07)
    _app(db_session, "smart_lof_neighbors", 9)

    config = _load_config(db_session)
    assert config == {"contamination": 0.07, "lof_neighbors": 9.0}
    assert all(isinstance(v, float) for v in config.values())
    # Nothing is invented for keys with no row: the consumers' inline
    # defaults are the only source of a missing value.
    assert "enabled" not in config


def test_smart_enabled_gate_short_circuits_the_detectors():
    from app.engine.smart.anomaly import detect_smart_anomalies
    from app.engine.smart.clustering import run_clustering
    from app.engine.smart.patterns import detect_composite_patterns

    data = {"A": {"hospital_id": 1, "values": {"2": 10}}}
    assert detect_smart_anomalies(data, {}, enabled=False) == []
    assert run_clustering(data, {}, enabled=False) is None
    assert detect_composite_patterns(data, {}, enabled=False) == []


def test_smart_enabled_and_xgboost_enabled_are_independent_gates():
    """``smart_enabled`` suppresses the detectors only; the XGBoost path has
    its own switch and still runs when smart analytics is 'off'."""
    src = (SMART_DIR / "__init__.py").read_text(encoding="utf-8")
    assert 'config.get("enabled", 1.0) > 0.5' in src
    assert 'if config.get("xgboost_enabled", True):' in src


# ---- auto_disable_null_indicators: parsing -------------------------------
@pytest.mark.parametrize("stored,expected", [
    ("true", True),
    ("TRUE", False),
    ("True", False),
    ("1", False),
    ("yes", False),
    ("true ", False),
    (None, False),
])
def test_auto_disable_flag_reads_only_the_literal_true(db_session, stored, expected):
    from app.engine.config_resolver import load_policy_snapshot

    if stored is not None:
        _setting(db_session, "auto_disable_null_indicators", stored)
    # A3.3: the run snapshot is the only reader; the parser is unchanged.
    assert load_policy_snapshot(db_session).require_auto_disable_null() is expected


def test_auto_disable_writer_lowercases_but_does_not_validate(client):
    """The writer stores any string verbatim (lowercased); the reader only
    accepts the literal ``true``. ``"yes"`` therefore saves successfully and
    reads back as off."""
    def _read():
        return client.get("/config/control/settings").json()[
            "auto_disable_null_indicators"]

    assert client.put("/config/control/settings",
                      json={"auto_disable_null_indicators": True}).status_code == 200
    assert _read() is True

    client.put("/config/control/settings",
               json={"auto_disable_null_indicators": "TRUE"})
    assert _read() is True  # lowercased on write

    client.put("/config/control/settings",
               json={"auto_disable_null_indicators": "YES"})
    assert _read() is False  # stored as "yes", reader wants "true"


# ---- anomaly_drift_months ------------------------------------------------
@pytest.mark.parametrize("stored,expected", [
    (None, 3),   # documented default
    ("6", 6),    # upper bound
    ("9", 6),    # clamped
    ("1", 2),    # clamped
    ("3.6", 3),  # truncated, not rounded
    ("abc", 3),  # unparsable -> default
])
def test_drift_months_default_bounds_and_truncation(db_session, stored, expected):
    from app.api.config_api import get_anomaly_settings

    if stored is not None:
        _setting(db_session, "anomaly_drift_months", stored)

    settings = get_anomaly_settings(db_session)
    assert settings["anomaly_drift_months"] == expected
    assert isinstance(settings["anomaly_drift_months"], int)


def test_drift_has_exactly_one_runtime_consumer():
    """The Dashboard 'Needs attention' drift detector is the only reader;
    config_api owns storage/validation."""
    app_dir = ROOT / "app"
    hits = sorted(
        path.name for path in app_dir.rglob("*.py")
        if "anomaly_drift_months" in path.read_text(encoding="utf-8")
    )
    assert hits == ["config_api.py", "dashboard.py"]


# ---- resolver coverage gap ----------------------------------------------
def test_resolver_covers_the_auto_disable_flag_only(db_session):
    snapshot = cr.load_policy_snapshot(db_session)
    keys = set(snapshot.values) | set(snapshot.metadata)

    # A3.3 added the flags plane; the other two remain out of scope.
    assert "flags.auto_disable_null" in keys
    assert snapshot.auto_disable_null is False
    assert not [k for k in keys if k.startswith("smart.")]
    assert not [k for k in keys if "anomaly_drift" in k]

    src = (ROOT / "app" / "engine" / "config_resolver.py").read_text(encoding="utf-8")
    assert "auto_disable_null_indicators" in src
    for marker in ("smart_analytics", "anomaly_drift_months"):
        assert marker not in src, marker
