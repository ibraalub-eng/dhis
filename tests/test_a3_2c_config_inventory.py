"""A3.2c pins: the settings inventory must stay true.

Read-only. Nothing is imported from ``app.main`` (importing it runs startup,
alembic and DB side effects); ``APP_CONFIG_DEFAULTS`` is parsed with ``ast``.
Each assertion corresponds to a measured claim in
``qa-d16/A3.2c-SETTINGS-INVENTORY.md``; if the architecture changes, the
inventory must be updated with it rather than the assertion loosened.
"""
from __future__ import annotations

import ast
import collections
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
SCRIPTS = ROOT / "scripts"

#: Documented seed counts (A3.2c §4). 115 literal tuples + 1 appended adapter.
EXPECTED_CATEGORIES = {
    "clinical": 45,
    "smart_analytics": 15,
    "risk": 14,
    "quality": 9,
    "trends": 9,
    "alerts": 7,
    "rates": 7,
    "rules": 5,
    "thresholds": 4,
}
EXPECTED_LITERAL_ROWS = 115

#: Consumed with defaults in code but never seeded and not exposed (D2).
UNMANAGED_ML_KEYS = (
    "ml_enabled",
    "ml_clustering_enabled",
    "ml_clustering_min_k",
    "ml_clustering_max_k",
    "ml_anomaly_enabled",
    "ml_anomaly_contamination",
    "ml_pca_enabled",
    "ml_pca_variance_threshold",
)

CATEGORY_SWEEP = "get_config_dict("


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _sources(*roots: Path) -> dict:
    out = {}
    for root in roots:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            out[path.relative_to(ROOT).as_posix()] = _read(path)
    return out


def _seed_rows():
    """``(rows, appended_expressions)`` parsed without importing the app."""
    tree = ast.parse(_read(APP / "main.py"))
    rows, appended = [], []
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "APP_CONFIG_DEFAULTS"
                and isinstance(node.value, ast.List)):
            for elt in node.value.elts:
                key = elt.elts[0].value if isinstance(elt.elts[0], ast.Constant) else None
                cat = elt.elts[2].value if isinstance(elt.elts[2], ast.Constant) else None
                rows.append((key, cat))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (ast.unparse(node.func) == "APP_CONFIG_DEFAULTS.append"
                    and node.args and isinstance(node.args[0], ast.Tuple)):
                appended.append(ast.unparse(node.args[0].elts[0]))
    return rows, appended


def test_seed_counts_per_category_and_no_duplicate_keys():
    rows, appended = _seed_rows()
    assert len(rows) == EXPECTED_LITERAL_ROWS
    assert dict(collections.Counter(cat for _key, cat in rows)) == EXPECTED_CATEGORIES
    keys = [key for key, _cat in rows]
    assert all(isinstance(key, str) and key for key in keys)
    assert len(keys) == len(set(keys)), "a seeded key is declared twice"
    assert appended == ["_TREND_PERSISTENCE.key"]
    main = _read(APP / "main.py")
    assert '_TREND_PERSISTENCE = TREND_SETTING_SPECS["trend_finding_consecutive"]' in main


def test_dead_keys_appear_only_in_the_seeder():
    """D1: 45 clinical_* + 14 risk_* + 7 rate_*_benchmark rows have no reader."""
    rows, _appended = _seed_rows()
    dead = [key for key, cat in rows if cat in ("clinical", "risk", "rates")]
    assert len(dead) == 66
    sources = {
        name: text for name, text in _sources(APP, SCRIPTS).items()
        if name != "app/main.py"
    }
    offenders = {
        key: sorted(name for name, text in sources.items() if key in text)
        for key in dead
    }
    offenders = {key: files for key, files in offenders.items() if files}
    assert offenders == {}, offenders
    # ...while the clinical engine classifies from Python constants instead.
    meta = _read(APP / "engine" / "clinical" / "thresholds.py")
    assert "_CLINICAL_META" in meta
    assert "higher_is_worse" in meta


def test_ml_keys_are_consumed_but_never_seeded():
    """D2: 8 ml_* keys resolve from code defaults only."""
    rows, _appended = _seed_rows()
    seeded = {key for key, _cat in rows}
    assert not (set(UNMANAGED_ML_KEYS) & seeded)

    pipeline = _read(APP / "engine" / "pipeline.py")
    resolver = _read(APP / "engine" / "config_resolver.py")
    for key in UNMANAGED_ML_KEYS:
        assert f'"{key}"' in pipeline, key
        assert f'"{key}"' in resolver, key
    # Nothing seeds the category, so the resolver reports "default" forever.
    assert 'category="ml"' not in _read(APP / "main.py")


def test_resolver_does_not_yet_cover_smart_flags_or_dashboard():
    """§3C: the resolver's coverage gap is a fact, not an aspiration."""
    resolver = _read(APP / "engine" / "config_resolver.py")
    assert "RESOLVER_VERSION" in resolver
    assert "smart_analytics" not in resolver
    # A3.3 migrated this one: it now lives in the resolver's flags plane.
    assert "auto_disable_null_indicators" in resolver
    assert "anomaly_drift_months" not in resolver
    # ...while it does carry the alert flag that policy_view then drops.
    assert '"alerts_auto_scan"' in resolver


def test_category_sweeps_remain_the_real_access_path():
    """D10: 24 textual occurrences in 15 files -> 21 executable call sites.

    A3.5 P1 replaced the pipeline's direct ``rules`` category reads with the
    resolved ``RulesPolicy``; P2 did the same for ``trends`` and ``rates``, and
    P3 (D5) moved confidence onto the snapshot, removing the last standalone
    ``thresholds`` sweep in ``engine/confidence.py``. The remaining sweeps are
    ml/quality (P3 still to migrate) and the display paths.
    """
    sources = _sources(APP, SCRIPTS)
    holders = {
        name: text.count(CATEGORY_SWEEP)
        for name, text in sources.items()
        if CATEGORY_SWEEP in text
    }
    assert len(holders) == 15, sorted(holders)
    assert sum(holders.values()) == 24, holders
    # 1 definition (config_utils) + 2 docstring mentions (scoring.py).
    assert holders["app/config_utils.py"] == 1
    assert holders["app/engine/quality/scoring.py"] == 2
    assert sum(holders.values()) - 1 - 2 == 21
    assert holders["app/engine/pipeline.py"] == 3


def test_direct_system_setting_queries_are_the_second_access_path():
    """A3.3 removed the dashboard, tree and confidence readers; the rest stay."""
    sources = _sources(APP)
    holders = sorted(
        name for name, text in sources.items()
        if "query(SystemSetting)" in text or "query(_SS)" in text
    )
    assert holders == [
        "app/api/analysis.py",
        "app/api/comparative.py",
        "app/api/config_api.py",
        "app/api/file_ops.py",
        "app/config_utils.py",
        "app/engine/config_resolver.py",
        "app/engine/severity.py",
        "app/main.py",
    ]
    assert not [h for h in holders if h in (
        "app/api/dashboard.py", "app/api/tree_config.py",
        "app/engine/confidence.py", "app/engine/pipeline.py")]


def test_single_value_helpers_that_are_dead_or_over_broad():
    """D8: get_config_value has no caller; get_ai_config loads every row."""
    sources = _sources(APP, SCRIPTS)
    callers = [
        name for name, text in sources.items()
        if "get_config_value(" in text and name != "app/config_utils.py"
    ]
    assert callers == []
    ai = _read(APP / "config_utils.py")
    assert "db.query(SystemSetting).all()" in ai


def test_process_global_policy_setters_still_exist():
    """D4: the deprecated shims remain, but nothing analytical calls them."""
    rules = _read(APP / "engine" / "quality" / "rules.py")
    trends = _read(APP / "engine" / "anomaly" / "trends.py")
    pipeline = _read(APP / "engine" / "pipeline.py")
    assert re.search(r"^def set_rules_config", rules, re.M)
    assert re.search(r"^def set_trends_config", trends, re.M)
    # A3.5 P1/P2: rules and trends arrive as explicit immutable policies; the
    # pipeline mutates neither global.
    assert "set_rules_config(" not in pipeline
    assert "set_trends_config(" not in pipeline
    assert 'get_config_dict(session, "trends")' not in pipeline
    assert 'get_config_dict(session, "rates")' not in pipeline


def test_month_eligibility_rule_is_implemented_twice():
    """D5: two parsers, two different notions of 'false'."""
    eligibility = _read(APP / "eligibility.py")
    analysis = _read(APP / "api" / "analysis.py")
    assert 'str(value).strip().lower() == "false"' in eligibility
    assert 'row.value == "false"' in analysis
