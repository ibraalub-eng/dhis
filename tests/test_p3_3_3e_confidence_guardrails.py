"""P3.3.3e — Confidence engine guardrails: policy-only, no live configuration.

The engine is a pure function of its arguments: an immutable
``ConfidencePolicy`` plus caller-supplied data. These tests pin that boundary
structurally (AST over the *calculation call graph*, not source substrings) and
behaviourally (policy isolation, no module state, safe provenance), so a future
edit that reintroduces a session, a model query, a config read or a
module-global weight table fails here instead of silently changing production
numbers.
"""
from __future__ import annotations

import ast
import copy
import inspect
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.engine import confidence as engine
from app.engine import pipeline
from app.engine.confidence import calculate_confidence
from app.engine.confidence_policy import (
    DEFAULT_HIGH,
    DEFAULT_LOW,
    DEFAULT_MEDIUM,
    DEFAULT_WEIGHTS,
    DEFAULT_ZSCORE_THRESHOLD,
    WEIGHT_KEYS,
    ConfidencePolicy,
)
from app.engine.config_resolver import resolve_policy
from app.models import Hospital, Indicator, IndicatorValue

MONTH = "2026-06"
APP_ROOT = Path(engine.__file__).resolve().parents[1]
MODULE = ast.parse(Path(engine.__file__).read_text(encoding="utf-8"))

#: Names that must never appear in the calculation call graph. The DB helper
#: ``build_indicator_rule_map(session)`` is deliberately outside that graph and
#: asserted unreachable below.
FORBIDDEN_NAMES = frozenset({
    "session", "db", "SIGNAL_WEIGHTS", "ConfidenceWeights", "SystemSetting",
    "get_config_dict", "load_policy_snapshot", "load_display_policy",
    "confidence_policy_from_snapshot", "DEFAULT_WEIGHTS",
})
FORBIDDEN_ATTRIBUTES = frozenset({
    "query", "first", "filter", "filter_by", "commit", "rollback", "scalar",
})


# ── static guardrails ───────────────────────────────────────────────────────

def _functions(tree):
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)}


def _called_names(node):
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _calculation_closure():
    """Every module function reachable from ``calculate_confidence``."""
    functions = _functions(MODULE)
    seen = {"calculate_confidence"}
    frontier = ["calculate_confidence"]
    while frontier:
        node = functions[frontier.pop()]
        for name in _called_names(node):
            if name in functions and name not in seen:
                seen.add(name)
                frontier.append(name)
    return functions, seen


def test_calculation_graph_is_closed_and_excludes_the_database_helper():
    functions, closure = _calculation_closure()

    # The traversal really covers the analytical helpers, not just the entry point.
    assert {
        "_signal_rule_compliance", "_signal_historical", "_signal_cross_hospital",
        "_signal_trend", "_signal_completeness", "_compute_level",
        "_build_recommendations", "_build_summary",
    } <= closure
    # The module's only DB helper is not part of the calculation.
    assert "build_indicator_rule_map" in functions
    assert "build_indicator_rule_map" not in closure


def test_calculation_graph_never_touches_a_session_model_or_live_config():
    functions, closure = _calculation_closure()

    referenced_names = set()
    referenced_attributes = set()
    for name in closure:
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Name):
                referenced_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced_attributes.add(node.attr)

    assert not (FORBIDDEN_NAMES & referenced_names)
    assert not (FORBIDDEN_ATTRIBUTES & referenced_attributes)


def test_calculation_graph_has_no_live_fallback_and_uses_only_the_policy():
    functions, closure = _calculation_closure()

    for name in closure:
        node = functions[name]
        assert not any(isinstance(sub, ast.Global)
                       for sub in ast.walk(node)), name
        # No default policy is constructed or substituted inside the calculation.
        constructed = [
            sub for sub in ast.walk(node)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
            and sub.func.id in {"ConfidencePolicy", "defaults"}
        ]
        assert constructed == [], name

    attributes = {
        sub.attr for name in closure
        for sub in ast.walk(functions[name]) if isinstance(sub, ast.Attribute)
    }
    # The five weights and four scalars come from the supplied object.
    assert {"weight_for", "high", "medium", "low", "zscore_threshold"} <= attributes


def test_engine_module_imports_no_database_or_live_configuration_plane():
    imported = []
    for node in MODULE.body:
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    forbidden = ("app.models", "app.database", "app.config_utils",
                 "app.engine.config_resolver", "app.engine.policy_view",
                 "sqlalchemy")
    for module_name in imported:
        assert not module_name.startswith(forbidden), module_name


def test_calculate_confidence_accepts_no_session_and_requires_the_policy():
    parameters = inspect.signature(calculate_confidence).parameters

    assert "session" not in parameters
    assert "db" not in parameters
    assert parameters["confidence_policy"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["confidence_policy"].default is inspect.Parameter.empty
    assert parameters["auto_disable_null"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["auto_disable_null"].default is inspect.Parameter.empty


def test_module_carries_no_mutable_signal_weight_table():
    assert "SIGNAL_WEIGHTS" not in vars(engine)

    module_dicts = {}
    for node in MODULE.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_dicts[target.id] = node.value

    weight_keyed = [
        name for name, value in module_dicts.items()
        if {key.value for key in value.keys
            if isinstance(key, ast.Constant)} & set(WEIGHT_KEYS)
    ]
    assert weight_keyed == []


# ── consumer and global inventory ──────────────────────────────────────────

def _app_modules():
    return sorted(APP_ROOT.rglob("*.py"))


def _parse(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.relative_to(APP_ROOT).as_posix()


def test_no_production_module_references_the_removed_global():
    offenders = [
        _relative(path) for path in _app_modules()
        if any(isinstance(node, ast.Name) and node.id == "SIGNAL_WEIGHTS"
               for node in ast.walk(_parse(path)))
    ]
    assert offenders == []


def test_confidence_weight_rows_are_confined_to_the_resolver_and_weights_api():
    allowed = {"engine/config_resolver.py", "api/confidence.py", "models.py"}

    offenders = [
        _relative(path) for path in _app_modules()
        if _relative(path) not in allowed
        and any(isinstance(node, ast.Name) and node.id == "ConfidenceWeights"
                for node in ast.walk(_parse(path)))
    ]
    assert offenders == []


def test_every_production_caller_passes_the_policy_and_no_session():
    calls = []
    for path in _app_modules():
        for node in ast.walk(_parse(path)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "calculate_confidence"):
                calls.append((_relative(path), node))

    assert calls, "no production calculate_confidence call was found"
    for relative, call in calls:
        keywords = [keyword.arg for keyword in call.keywords]
        assert "confidence_policy" in keywords, relative
        assert not {"session", "db"} & set(keywords), relative
        assert None not in keywords, f"{relative} forwards **kwargs"


# ── immutability and isolation ─────────────────────────────────────────────

HISTORY = {f"2025-{month:02d}": {"2": 100.0} for month in range(1, 10)}
PEERS = {"H": {"2": 500.0}, **{f"Peer {i}": {"2": 100.0} for i in range(1, 6)}}


def _policy(weights=None, **cutoffs):
    values = dict(DEFAULT_WEIGHTS)
    values.update(weights or {})
    scalars = dict(high=DEFAULT_HIGH, medium=DEFAULT_MEDIUM, low=DEFAULT_LOW,
                   zscore_threshold=DEFAULT_ZSCORE_THRESHOLD)
    scalars.update(cutoffs)
    return ConfidencePolicy(**values, **scalars)


def _call(policy, **overrides):
    kwargs = dict(
        hospital_name="H",
        month="2026-04",
        values={"2": 500.0},
        rule_results=[],
        historical_data=HISTORY,
        all_hospital_data=PEERS,
        indicator_map={"2": "Deliveries"},
        indicator_children={},
        indicator_rule_map={},
        key_indicator_codes=["2"],
        auto_disable_null=False,
    )
    kwargs.update(overrides)
    return calculate_confidence(confidence_policy=policy, **kwargs)


def test_the_supplied_policy_object_drives_the_calculation():
    default = _call(ConfidencePolicy.defaults())
    equal = _call(_policy({key: 0.2 for key in WEIGHT_KEYS}))

    assert default.overall_confidence != pytest.approx(equal.overall_confidence)


def test_the_calculation_does_not_mutate_the_policy():
    policy = _policy({"rule_compliance": 11.0, "historical": 2.0,
                      "cross_hospital": 2.0, "trend": 2.0,
                      "completeness": 3.0})
    before = (dict(policy.submitted_weights), dict(policy.effective_weights),
              dict(policy.effective_decimals))

    _call(policy)

    assert (dict(policy.submitted_weights), dict(policy.effective_weights),
            dict(policy.effective_decimals)) == before
    with pytest.raises(FrozenInstanceError):
        policy.rule_compliance = 0.1


def test_policies_stay_isolated_across_interleaved_calls():
    default = _policy({})
    equal = _policy({key: 0.2 for key in WEIGHT_KEYS})

    first_default = _call(default).to_dict()
    first_equal = _call(equal).to_dict()
    assert first_default != first_equal
    assert _call(default).to_dict() == first_default
    assert _call(equal).to_dict() == first_equal


def test_calls_do_not_mutate_any_module_global():
    before_ids = {name: id(value) for name, value in vars(engine).items()
                  if not name.startswith("__")}
    before_state = {
        name: copy.deepcopy(value) for name, value in vars(engine).items()
        if not name.startswith("__") and isinstance(value, (dict, list, set))
    }

    _call(ConfidencePolicy.defaults())
    _call(_policy({key: 0.2 for key in WEIGHT_KEYS}))

    after_ids = {name: id(value) for name, value in vars(engine).items()
                 if not name.startswith("__")}
    assert after_ids == before_ids
    assert {name: vars(engine)[name] for name in before_state} == before_state


def test_normalized_policy_is_mathematically_equivalent_to_defaults():
    doubled = _policy({key: value * 2.0 for key, value in DEFAULT_WEIGHTS.items()})

    assert doubled.normalization_applied is True
    assert dict(doubled.submitted_weights) != dict(DEFAULT_WEIGHTS)
    assert dict(doubled.effective_weights) == dict(DEFAULT_WEIGHTS)
    assert _call(doubled).to_dict() == _call(ConfidencePolicy.defaults()).to_dict()


def test_cutoff_policy_change_affects_only_level_classification():
    base = _call(ConfidencePolicy.defaults())
    strict = _call(_policy({}, high=99.0, medium=99.0))

    base_indicator = base.indicators[0]
    strict_indicator = strict.indicators[0]

    assert base.overall_confidence == pytest.approx(strict.overall_confidence)
    assert base_indicator.confidence == pytest.approx(
        strict_indicator.confidence)
    assert [signal.score for signal in base_indicator.signals] == \
        [signal.score for signal in strict_indicator.signals]
    assert base_indicator.level != strict_indicator.level


# ── provenance guardrails ─────────────────────────────────────────────────

def _seed_month(db, sample_values):
    hospital = db.query(Hospital).first()
    for code, value in sample_values.items():
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if indicator is not None:
            db.add(IndicatorValue(hospital_id=hospital.id,
                                  indicator_id=indicator.id,
                                  month=MONTH, value=value))
    db.commit()
    return hospital


def test_provenance_names_the_exact_policy_the_engine_received(
        db_session, monkeypatch, sample_values):
    hospital = _seed_month(db_session, sample_values)
    snapshot = resolve_policy({}, {}, confidence_weights={
        "rule_compliance": 11.0,
        "historical": 2.0,
        "cross_hospital": 2.0,
        "trend": 2.0,
        "completeness": 3.0,
    })
    assert snapshot.confidence_policy is not None

    seen = []
    real = pipeline.calculate_confidence

    def spy(**kwargs):
        seen.append(kwargs["confidence_policy"])
        return real(**kwargs)

    monkeypatch.setattr(pipeline, "calculate_confidence", spy)

    result = pipeline.run_full_analysis(
        db_session, hospital.id, MONTH, force=True, policy=snapshot)

    assert result["analysis_status"] == pipeline.ANALYSIS_STATUS_OK
    assert seen, "the pipeline did not calculate confidence"
    assert all(policy is snapshot.confidence_policy for policy in seen)

    provenance = result["policy_provenance"]
    assert provenance["digest"] == snapshot.digest
    assert provenance["confidence_policy_version"] == \
        snapshot.component_versions["confidence"]


def test_submitted_and_effective_weights_stay_distinct_and_unpublished():
    snapshot = resolve_policy({}, {}, confidence_weights={
        "rule_compliance": 11.0,
        "historical": 2.5,
        "cross_hospital": 2.5,
        "trend": 2.5,
        "completeness": 3.5,
    })
    policy = snapshot.confidence_policy
    assert policy is not None

    assert policy.submitted_weights["rule_compliance"] == 11.0
    assert policy.effective_weights["rule_compliance"] == pytest.approx(0.5)
    assert dict(policy.submitted_weights) != dict(policy.effective_weights)

    serialized = json.dumps(pipeline._policy_provenance(snapshot), sort_keys=True)
    assert "11.0" not in serialized
    assert "3.5" not in serialized
    assert "row_ids" not in serialized


def test_policy_provenance_drops_the_raw_read_error():
    snapshot = resolve_policy(
        {}, {}, strict=False,
        read_error="postgresql://user:secret@db.internal/health")

    provenance = pipeline._policy_provenance(snapshot)

    assert "read_error" not in provenance
    assert "db.internal" not in json.dumps(provenance)
    assert "secret" not in json.dumps(provenance)
    assert provenance["validation_status"] == "unavailable"


def test_unavailable_and_invalid_states_remain_distinguishable():
    unavailable = resolve_policy(
        {}, {}, strict=False, read_error="configuration store unavailable")
    invalid = resolve_policy({"confidence_high": -5.0}, {})

    assert unavailable.confidence_policy is None
    assert invalid.confidence_policy is None
    assert pipeline._policy_validation_status(unavailable) == "unavailable"
    assert pipeline._policy_validation_status(invalid) == "invalid"
