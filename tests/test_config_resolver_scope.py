"""D16-A3.1 — resolver coverage of the remaining analysis categories.

A1 proved parity for the six original planes. A3.1 adds the categories the
analysis path still read directly — ``rules``, ``ml``, the alert auto-scan flag
and the five ``trends`` gates the trend engine consumes as raw config — plus a
content digest of the ``rules`` table as immutable metadata.

These tests hold two lines: (a) every added value equals the default the
existing consumer actually uses, and (b) no category without an analysis
consumer is invented into the snapshot.
"""
from datetime import datetime, timedelta

import pytest

from app.engine import config_resolver as cr
from app.engine.anomaly import trends
from app.engine.config_resolver import load_policy_snapshot, resolve_policy
from app.engine.pipeline import _build_ml_config
from app.engine.quality import definitions as quality_definitions
from app.engine.quality.definitions import RULE_DEFAULTS
from app.models import AppConfig, Rule

TREND_GATES = ("trend_r_squared", "trend_finding_slope", "trend_finding_deviation",
               "trend_finding_cv", "trend_finding_r_squared")


def _app(db, key, value, category):
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if row is None:
        db.add(AppConfig(key=key, value=float(value), category=category,
                         label=key))
    else:
        row.value = float(value)
    db.commit()


def _nested_ml(snapshot):
    """snapshot ml plane reshaped exactly like ``_build_ml_config``."""
    v = snapshot.values
    return {
        "enabled": v["ml.enabled"],
        "clustering": {"enabled": v["ml.clustering_enabled"],
                       "min_k": v["ml.clustering_min_k"],
                       "max_k": v["ml.clustering_max_k"]},
        "anomaly": {"enabled": v["ml.anomaly_enabled"],
                    "contamination": v["ml.anomaly_contamination"]},
        "pca": {"enabled": v["ml.pca_enabled"],
                "variance_threshold": v["ml.pca_variance_threshold"]},
    }


# ── rules ──────────────────────────────────────────────────────────────────
def test_rules_plane_defaults_match_the_compiled_rule_table(db_session):
    sync = load_policy_snapshot(db_session)
    for key, default in RULE_DEFAULTS.items():
        assert sync.values[f"rules.{key}"] == pytest.approx(default), key
        assert sync.entries[f"rules.{key}"].source == "default", key


def test_rules_plane_reads_stored_values(db_session):
    _app(db_session, "eq_tolerance", 0.02, "rules")
    _app(db_session, "maternal_over_factor", 3.5, "rules")
    sync = load_policy_snapshot(db_session)

    assert sync.values["rules.eq_tolerance"] == pytest.approx(0.02)
    assert sync.values["rules.maternal_over_factor"] == pytest.approx(3.5)
    assert sync.entries["rules.eq_tolerance"].source == "database"
    # Untouched siblings still report their documented default.
    assert sync.values["rules.neonatal_over_factor"] == pytest.approx(4.0)


def test_rules_plane_reports_an_unusable_value(db_session):
    sync = resolve_policy({"eq_tolerance": "not-a-number"}, {})
    entry = sync.entries["rules.eq_tolerance"]
    assert entry.source == "invalid"
    assert entry.value == pytest.approx(RULE_DEFAULTS["eq_tolerance"])
    assert "rules.eq_tolerance" in sync.invalid_keys


# ── ml ─────────────────────────────────────────────────────────────────────
def test_ml_plane_defaults_match_the_pipeline_config(db_session):
    sync = load_policy_snapshot(db_session)
    assert _nested_ml(sync) == _build_ml_config({})


def test_ml_plane_matches_the_pipeline_config_with_stored_values(db_session):
    stored = {"ml_enabled": 1, "ml_clustering_min_k": 3, "ml_clustering_max_k": 5,
              "ml_anomaly_contamination": 0.07, "ml_pca_variance_threshold": 0.9}
    for key, value in stored.items():
        _app(db_session, key, value, "ml")
    sync = load_policy_snapshot(db_session)

    assert _nested_ml(sync) == _build_ml_config(stored)
    # bool(...) truthiness, exactly as the pipeline does it: 2 is truthy.
    assert sync.values["ml.enabled"] is True
    assert sync.entries["ml.anomaly_contamination"].source == "database"


def test_ml_plane_reports_an_unusable_value(db_session):
    sync = resolve_policy({"ml_anomaly_contamination": "abc"}, {})
    entry = sync.entries["ml.anomaly_contamination"]
    assert entry.source == "invalid"
    assert entry.value == pytest.approx(0.05)


# ── trend engine gates ─────────────────────────────────────────────────────
def test_trend_gates_default_to_the_engine_table(db_session):
    sync = load_policy_snapshot(db_session)
    for key in TREND_GATES:
        assert sync.values[key] == pytest.approx(trends.TREND_ENGINE_DEFAULTS[key]), key
        assert sync.entries[key].source == "default", key


def test_trend_gates_read_stored_values_and_stay_apart_from_the_specs(db_session):
    _app(db_session, "trend_finding_cv", 12.5, "trends")
    sync = load_policy_snapshot(db_session)

    assert sync.values["trend_finding_cv"] == pytest.approx(12.5)
    assert sync.entries["trend_finding_cv"].source == "database"
    # The documented defaults table is immutable: resolving must not mutate it.
    assert trends.TREND_ENGINE_DEFAULTS["trend_finding_cv"] == pytest.approx(30.0)
    # A spec-owned setting is resolved once, by the trend plane, not twice here.
    assert sync.entries["trend_analysis_window"].component == "trend"


# ── alert auto-scan flag ───────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    (0, False), (1, True), (2, True), ("0", False), ("0.0", False),
    ("false", False), ("False", False), ("off", False), ("1", True),
])
def test_alert_auto_scan_flag_is_parsed_like_the_pipeline(raw, expected):
    sync = resolve_policy({"alerts_auto_scan": raw}, {})
    assert sync.values["alerts.auto_scan"] is expected
    assert sync.entries["alerts.auto_scan"].source == "database"


def test_alert_auto_scan_defaults_to_on(db_session):
    sync = load_policy_snapshot(db_session)
    assert sync.values["alerts.auto_scan"] is True
    assert sync.entries["alerts.auto_scan"].source == "default"


# ── rules table digest as metadata ─────────────────────────────────────────
def test_rules_table_digest_is_metadata_not_a_setting(db_session):
    sync = load_policy_snapshot(db_session)
    assert "rules.hash" in sync.metadata
    assert "rules.hash" not in sync.values
    assert len(sync.metadata["rules.hash"]) == 64
    assert sync.metadata["rules.count"] > 0


def test_rules_digest_changes_when_a_rule_changes(db_session):
    before = load_policy_snapshot(db_session)
    rule = db_session.query(Rule).order_by(Rule.code).first()
    rule.severity = "CRITICAL" if rule.severity != "CRITICAL" else "HIGH"
    db_session.commit()

    after = load_policy_snapshot(db_session)
    assert after.metadata["rules.hash"] != before.metadata["rules.hash"]
    assert after.digest != before.digest


# ── digest covers the new planes, and the old ones still resolve ───────────
def test_digest_covers_the_new_planes(db_session):
    before = load_policy_snapshot(db_session)
    _app(db_session, "ml_anomaly_contamination", 0.11, "ml")
    after = load_policy_snapshot(db_session)
    assert after.digest != before.digest


def test_a2_views_still_resolve_from_the_extended_snapshot(db_session):
    from app.engine.policy_view import (
        alerts_config_from_snapshot,
        analysis_config_from_snapshot,
        comparison_policy_from_snapshot,
    )

    sync = load_policy_snapshot(db_session)
    assert analysis_config_from_snapshot(sync).zscore_threshold == 2.5
    assert alerts_config_from_snapshot(sync)["history_window"] == 12
    assert comparison_policy_from_snapshot(sync).history.window == 12


# ── scope line: no category without an analysis consumer is invented ──────
def test_categories_without_an_analysis_consumer_are_not_invented(db_session):
    sync = load_policy_snapshot(db_session)
    for prefix in ("clinical.", "risk.", "rates.", "smart."):
        assert not [key for key in sync.values if key.startswith(prefix)], prefix


def test_resolver_version_reflects_the_extended_coverage():
    assert cr.RESOLVER_VERSION == "1.4.0"


def test_rules_config_module_is_the_single_source_of_the_defaults():
    """Guard the one import the resolver relies on (no duplicated defaults)."""
    assert quality_definitions.RULE_DEFAULTS is RULE_DEFAULTS
    # The frozen baseline is a separate object from the mutable runtime table,
    # so a runtime ``set_rules_config`` cannot rebind it.
    assert quality_definitions.RULE_DEFAULTS is not quality_definitions._RULES_CONFIG
    assert dict(RULE_DEFAULTS) == quality_definitions._RULES_CONFIG


# ── A3.1b — rules defaults are frozen and provenance is honest ─────────────
def test_rules_defaults_are_an_immutable_baseline():
    with pytest.raises(TypeError):
        RULE_DEFAULTS["eq_tolerance"] = 1.0
    assert RULE_DEFAULTS["eq_tolerance"] == pytest.approx(0.01)


def test_runtime_rules_config_setter_is_inert(db_session):
    """A3.5: the compatibility shim moves no state and no baseline."""
    from app.engine.quality.rules import set_rules_config

    baseline = dict(RULE_DEFAULTS)
    set_rules_config({"eq_tolerance": 0.5, "month_over_factor": 9.0})
    assert dict(quality_definitions._RULES_CONFIG) == baseline

    clean = load_policy_snapshot(db_session)
    assert clean.values["rules.eq_tolerance"] == pytest.approx(0.01)
    assert clean.entries["rules.eq_tolerance"].source == "default"

    _app(db_session, "eq_tolerance", 0.02, "rules")
    stored = load_policy_snapshot(db_session)
    assert stored.values["rules.eq_tolerance"] == pytest.approx(0.02)
    assert stored.entries["rules.eq_tolerance"].source == "database"
    assert stored.values["rules.month_over_factor"] == pytest.approx(2.0)


def test_resolution_is_identical_after_a_legacy_setter_call(db_session):
    """The snapshot must not depend on process history."""
    from app.engine.quality.rules import set_rules_config

    before = load_policy_snapshot(db_session)
    set_rules_config({"eq_tolerance": 0.5})
    after = load_policy_snapshot(db_session)

    assert after.values == before.values
    assert after.sources == before.sources
    assert after.digest == before.digest


def test_source_database_is_reported_only_for_stored_keys(db_session):
    _app(db_session, "eq_tolerance", 0.02, "rules")
    _app(db_session, "ml_anomaly_contamination", 0.07, "ml")
    sync = load_policy_snapshot(db_session)

    stored_rules = {name for name, entry in sync.entries.items()
                    if entry.component == "rules" and entry.source == "database"}
    stored_ml = {name for name, entry in sync.entries.items()
                 if entry.component == "ml" and entry.source == "database"}
    assert stored_rules == {"rules.eq_tolerance"}
    assert stored_ml == {"ml.anomaly_contamination"}
    assert [name for name, source in sync.sources.items()
            if source not in ("database", "default", "invalid")] == []


# ── A3.1b — ``rules.hash`` contract ───────────────────────────────────────
def _new_rule(db, code, *, rule_id, params='{"parent": "2", "children": ["3"]}'):
    rule = Rule(id=rule_id, code=code, name=f"Contract probe {code}",
                rule_type="LOGIC", severity="LOW", category="LOGIC",
                expression_type="ge", params=params, description="",
                enabled=True, sort_order=99)
    db.add(rule)
    db.commit()
    return rule


def test_rules_hash_field_set_is_explicit(db_session):
    fields = cr.rules_hash_fields()
    assert "id" not in fields  # surrogate key, not analytical identity
    assert [name for name in fields if name.endswith("_at")] == []
    for required in ("code", "name", "rule_type", "severity", "category",
                     "expression_type", "params", "description", "enabled",
                     "sort_order"):
        assert required in fields
    metadata = load_policy_snapshot(db_session).metadata
    assert metadata["rules.hash_fields"] == list(fields)
    assert metadata["rules.fields"] == len(fields)


def test_rules_hash_is_stable_across_repeated_resolutions(db_session):
    first = load_policy_snapshot(db_session)
    for _ in range(3):
        again = load_policy_snapshot(db_session)
        assert again.metadata["rules.hash"] == first.metadata["rules.hash"]
        assert again.metadata["rules.count"] == first.metadata["rules.count"]
        assert again.digest == first.digest
        assert again.canonical_json() == first.canonical_json()


def test_rules_hash_ignores_a_timestamp_only_touch(db_session):
    before = load_policy_snapshot(db_session)
    rule = db_session.query(Rule).order_by(Rule.code).first()
    rule.updated_at = (rule.updated_at or datetime.utcnow()) + timedelta(days=2)
    db_session.commit()

    after = load_policy_snapshot(db_session)
    assert after.metadata["rules.hash"] == before.metadata["rules.hash"]
    assert after.metadata["rules.updated_at"] != before.metadata["rules.updated_at"]
    # Provenance moved; policy identity did not.
    assert after.digest == before.digest
    assert after.canonical_json() == before.canonical_json()
    assert (after.canonical_json(include_provenance=True)
            != before.canonical_json(include_provenance=True))
    assert after.metadata["rules.updated_at"] in after.canonical_json(
        include_provenance=True)


def test_rules_hash_ignores_the_storage_primary_key(db_session):
    baseline = load_policy_snapshot(db_session).metadata["rules.hash"]

    rule = _new_rule(db_session, "R996", rule_id=9001)
    with_first_pk = load_policy_snapshot(db_session).metadata["rules.hash"]
    assert with_first_pk != baseline

    db_session.delete(rule)
    db_session.commit()
    _new_rule(db_session, "R996", rule_id=9002)
    with_second_pk = load_policy_snapshot(db_session).metadata["rules.hash"]
    assert with_second_pk == with_first_pk


def test_rules_hash_ignores_params_json_formatting(db_session):
    rule = _new_rule(db_session, "R995", rule_id=9100)
    rule.params = '{"parent":"2","children":["3","4"]}'
    db_session.commit()
    compact = load_policy_snapshot(db_session).metadata["rules.hash"]

    rule.params = '{\n  "children": ["3", "4"],\n  "parent": "2"\n}'
    db_session.commit()
    pretty = load_policy_snapshot(db_session).metadata["rules.hash"]
    assert pretty == compact


def test_rules_hash_separates_malformed_params_text(db_session):
    rule = _new_rule(db_session, "R994", rule_id=9200, params="not-json")
    as_text = load_policy_snapshot(db_session).metadata["rules.hash"]

    rule.params = '"not-json"'  # same characters, but valid JSON text
    db_session.commit()
    as_json = load_policy_snapshot(db_session).metadata["rules.hash"]
    assert as_json != as_text


@pytest.mark.parametrize("field,value", [
    ("severity", "CRITICAL"),
    ("enabled", False),
    ("sort_order", 3),
    ("name", "Renamed probe"),
    ("params", '{"parent":"2","children":["4"]}'),
])
def test_analytical_rule_changes_move_hash_and_digest(db_session, field, value):
    rule = _new_rule(db_session, "R993", rule_id=9300)
    before = load_policy_snapshot(db_session)

    setattr(rule, field, value)
    db_session.commit()
    after = load_policy_snapshot(db_session)

    assert after.metadata["rules.hash"] != before.metadata["rules.hash"]
    assert after.digest != before.digest


# ── A3.1b — ``PolicySnapshot.digest`` contract ────────────────────────────
def test_digest_is_identical_for_repeated_pure_resolutions():
    first = resolve_policy({}, {})
    for _ in range(3):
        assert resolve_policy({}, {}).digest == first.digest


def test_digest_ignores_metadata_key_order():
    metadata = {"rules.hash": "a" * 64, "rules.count": 72,
                "rules.updated_at": "2026-01-01T00:00:00"}
    forward = resolve_policy({}, {}, metadata=metadata)
    reverse = resolve_policy({}, {}, metadata=dict(reversed(list(metadata.items()))))
    assert forward.digest == reverse.digest
    assert forward.canonical_json() == reverse.canonical_json()


def test_provenance_metadata_stays_visible_and_out_of_the_digest():
    without = resolve_policy({}, {}, metadata={"rules.count": 3})
    with_stamp = resolve_policy({}, {}, metadata={
        "rules.count": 3, "rules.updated_at": "2026-02-01T10:00:00"})

    assert with_stamp.metadata["rules.updated_at"] == "2026-02-01T10:00:00"
    assert "rules.updated_at" not in with_stamp.identity_metadata
    assert with_stamp.digest == without.digest
    assert with_stamp.as_dict()["metadata"]["rules.updated_at"] == "2026-02-01T10:00:00"
    assert "2026-02-01T10:00:00" in with_stamp.canonical_json(include_provenance=True)
    assert "2026-02-01T10:00:00" not in with_stamp.canonical_json()


def test_analytical_metadata_changes_do_move_the_digest():
    base = resolve_policy({}, {}, metadata={"rules.count": 3})
    changed = resolve_policy({}, {}, metadata={"rules.count": 4})
    assert base.digest != changed.digest


# ── A3.1b — ML parity edge cases (documented, not silently assumed) ───────
def test_ml_parity_for_zero_and_false_values():
    stored = {"ml_enabled": 0, "ml_clustering_enabled": False,
              "ml_clustering_min_k": 0, "ml_clustering_max_k": 0,
              "ml_anomaly_enabled": 0, "ml_anomaly_contamination": 0.0,
              "ml_pca_enabled": False, "ml_pca_variance_threshold": 0.0}
    sync = resolve_policy(stored, {})
    assert _nested_ml(sync) == _build_ml_config(stored)
    assert sync.entries["ml.clustering_min_k"].source == "database"


def test_ml_explicit_none_diverges_from_the_pipeline_and_is_documented():
    raw = {"ml_clustering_enabled": None, "ml_pca_enabled": None}
    sync = resolve_policy(raw, {})
    # Resolver: an explicit None is "not stored" -> documented default.
    assert sync.values["ml.clustering_enabled"] is True
    assert sync.values["ml.pca_enabled"] is True
    assert sync.entries["ml.clustering_enabled"].source == "default"
    # Pipeline: the key is present, so bool(None) is False.
    assert _build_ml_config(raw)["clustering"]["enabled"] is False
    assert _build_ml_config(raw)["pca"]["enabled"] is False
    # Unreachable through storage: app_config.value is NOT NULL, so no stored
    # row can produce this divergence; it is pinned so it stays deliberate.


def test_ml_non_finite_values_pass_through_and_stay_deterministic():
    raw = {"ml_anomaly_contamination": float("inf"),
           "ml_pca_variance_threshold": float("nan")}
    first = resolve_policy(raw, {})
    second = resolve_policy(raw, {})
    # No clamping or validation is claimed for opening the ML plane.
    assert first.values["ml.anomaly_contamination"] == float("inf")
    assert first.entries["ml.pca_variance_threshold"].source == "database"
    assert first.digest == second.digest


def test_ml_pca_threshold_type_diverges_from_the_pipeline():
    raw = {"ml_pca_variance_threshold": "0.9"}
    sync = resolve_policy(raw, {})
    assert sync.values["ml.pca_variance_threshold"] == pytest.approx(0.9)
    assert isinstance(sync.values["ml.pca_variance_threshold"], float)
    # The pipeline does not coerce this key; only the Float column makes the
    # two agree on stored data.
    assert _build_ml_config(raw)["pca"]["variance_threshold"] == "0.9"


def test_ml_k_bounds_are_validated_by_neither_side():
    raw = {"ml_clustering_min_k": -3, "ml_clustering_max_k": 1}
    sync = resolve_policy(raw, {})
    assert _nested_ml(sync) == _build_ml_config(raw)
    assert sync.values["ml.clustering_min_k"] == -3


# ── A3.1b — trend gate edge cases ────────────────────────────────────────
@pytest.mark.parametrize("raw,expected,source", [
    (0, 0.0, "database"),
    (False, 0.0, "database"),
    ("0", 0.0, "database"),
    (None, 20.0, "default"),
])
def test_trend_gate_zero_false_string_and_missing(raw, expected, source):
    payload = {} if raw is None else {"trend_finding_deviation": raw}
    sync = resolve_policy(payload, {})
    assert sync.values["trend_finding_deviation"] == pytest.approx(expected)
    assert sync.entries["trend_finding_deviation"].source == source


def test_trend_gate_invalid_value_falls_back_to_the_engine_default():
    sync = resolve_policy({"trend_finding_deviation": "abc"}, {})
    entry = sync.entries["trend_finding_deviation"]
    assert entry.source == "invalid"
    assert entry.value == pytest.approx(
        trends.TREND_ENGINE_DEFAULTS["trend_finding_deviation"])
    assert "trend_finding_deviation" in sync.invalid_keys
