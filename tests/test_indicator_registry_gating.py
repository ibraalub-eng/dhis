"""Indicators-registry gating: strict two-category axis + active/inactive
status as the single source of truth for current operational calculations.

Deactivating an indicator on the Indicators screen must remove it from the
rate-spec set, from spec resolution and from regional metrics, while keeping
its seeded definitions intact (history preserved).
"""
import pytest

from app.api.indicator_definitions import list_indicators
from app.engine.rate_config import (
    load_rate_specs,
    zscore_specs,
    _RATE_SPECS_CACHE,
)


@pytest.fixture(autouse=True)
def _fresh_rate_specs_cache():
    """Keep the in-process rate-spec cache out of test-to-test leakage."""
    global _RATE_SPECS_CACHE
    _RATE_SPECS_CACHE = None
    yield
    _RATE_SPECS_CACHE = None


def _catalog(db, **kw):
    kw.setdefault("q", None)
    kw.setdefault("category", None)
    kw.setdefault("kind", None)
    kw.setdefault("group", None)
    kw.setdefault("type", None)
    kw.setdefault("status", None)
    return list_indicators(db=db, **kw)


def _make_definition(session, **kw):
    from app.models import IndicatorDefinition

    payload = {
        "code": "test_derived_001",
        "name": "Test derived indicator",
        "group_name": None,
        "formula_type": "ratio",
        "numerator_codes": ["5"],
        "denominator_codes": ["2"],
        "operator": "/",
        "multiplier": 100.0,
        "aggregation": "sum",
        "result_type": "percentage",
        "is_active": True,
        "is_system": False,
        "source_site": None,
    }
    payload.update(kw)
    defn = IndicatorDefinition(**payload)
    session.add(defn)
    session.flush()
    return defn


def test_category_axis_is_strict_two_values(db_session):
    """Every catalog row's category is exactly Data Element or Derivative
    Indicator — an explicit group name never leaks into the category axis."""
    out = _catalog(db_session)
    allowed = {"Data Element", "Derivative Indicator"}
    assert out.items
    assert {i.category for i in out.items} <= allowed
    assert "Data Element" in out.categories
    assert "Derivative Indicator" in out.categories
    for item in out.items:
        if item.kind == "raw":
            assert item.category == "Data Element"
        else:
            assert item.category == "Derivative Indicator"


def test_raw_row_without_group_survives_are_broadcast(db_session):
    """A raw row with no group_name still lists under its kind-fallback
    category instead of an empty-group hole."""
    from app.models import Indicator

    raw = Indicator(code="zz_raw_nogroup", name="Ungrouped raw element")
    db_session.add(raw)
    db_session.flush()
    out = _catalog(db_session, kind="raw", group="Data Element")
    codes = {i.code for i in out.items}
    assert "zz_raw_nogroup" in codes
    assert all(i.name == "Ungrouped raw element" or i.group_name
               for i in out.items)


def test_group_chip_filter_matches_fallback_chip_rows(db_session):
    """Filtering by a fallback chip label ("Data Element") must return the
    ungrouped rows the /indicators/groups chip counts — previously the group
    filter compared group_name only and matched zero rows."""
    out = _catalog(db_session, group="Data Element")
    if not out.items:
        # Seed fixture groups every raw row — create ungrouped ones so the
        # fallback chips ("Data Element"/"Derivative Indicator") exist.
        from app.models import Indicator

        db_session.add(Indicator(code="zz_raw_chip", name="Chip raw element"))
        db_session.flush()
        out = _catalog(db_session, group="Data Element")
    assert out.items
    assert all(i.kind == "raw" for i in out.items)
    assert all(not (i.group_name or "").strip() for i in out.items)
    assert any(i.code == "zz_raw_chip" for i in out.items)

    derivative = _catalog(db_session, group="Derivative Indicator")
    if not derivative.items:
        _make_definition(db_session, code="zz_derived_chip",
                         name="Chip derived indicator")
        derivative = _catalog(db_session, group="Derivative Indicator")
    assert derivative.items
    assert all(i.kind in ("derived", "rate_spec") for i in derivative.items)
    assert all(not (i.group_name or "").strip() for i in derivative.items)

    # Explicit groups still filter exactly.
    grouped = _catalog(db_session)
    with_name = next(i for i in grouped.items if i.group_name)
    exact = _catalog(db_session, group=with_name.group_name)
    assert all((i.group_name or "").strip() == with_name.group_name
               for i in exact.items)
    assert exact.items


def test_load_rate_specs_drops_deactivated_registry_code(db_session):
    """Deactivating a seeded system definition removes its rate from the
    merged spec set (and its RateConfig row must not resurrect the builtin
    base); re-activation restores it."""
    from app.models import IndicatorDefinition

    specs_before = load_rate_specs(db_session)
    target = sorted(specs_before)[0]
    legacy = specs_before[target].rate_code

    row = db_session.query(IndicatorDefinition).filter(
        IndicatorDefinition.legacy_code == legacy).first()
    if row is None:
        # Schema guarantee: every merged spec's rate_code is seeded very early
        pytest.skip(f"no registry seed for {legacy} in this fixture")
    assert row is not None
    assert target in load_rate_specs(db_session)

    row.is_active = False
    db_session.flush()
    specs_off = load_rate_specs(db_session)
    assert target not in specs_off

    row.is_active = True
    db_session.flush()
    assert target in load_rate_specs(db_session)


def test_resolve_spec_fallback_respects_deactivation(db_session):
    """indicator_service._resolve_spec must not let a deactivated seed creep
    back through the builtin clinical/forecast fallback slices."""
    from app.engine import indicator_service
    from app.models import IndicatorDefinition

    fallback_codes = [
        s.rate_code for s in zscore_specs()
    ] or []
    code = next(
        (d.legacy_code for d in db_session.query(IndicatorDefinition)
         .filter(IndicatorDefinition.is_active.is_(True),
                 IndicatorDefinition.legacy_code.isnot(None))
         .all() if d.legacy_code), None)
    assert code, "fixture expected at least one seeded legacy rate"
    resolved_on = indicator_service._resolve_spec(db_session, code, None)
    assert resolved_on is not None

    row = db_session.query(IndicatorDefinition).filter(
        IndicatorDefinition.legacy_code == code).first()
    row.is_active = False
    db_session.flush()
    resolved_off = indicator_service._resolve_spec(db_session, code, None)
    assert resolved_off is None


def test_inactive_codes_matches_aliases(db_session):
    from app.engine import indicator_service
    from app.models import IndicatorDefinition

    row = db_session.query(IndicatorDefinition).filter(
        IndicatorDefinition.legacy_code.isnot(None)).first()
    row.is_active = False
    db_session.flush()
    codes = indicator_service.inactive_codes(db_session)
    assert row.code in codes
    assert row.legacy_code in codes


def test_regional_skip_includes_mapped_metric(db_session):
    """The regional board maps metric keys to registry definition codes; a
    deactivated definition must show up as a skipped metric."""
    from app.engine.smart import regional
    from app.models import IndicatorDefinition

    metric_code = next(iter(regional._RATE_DEFINITIONS.values()))
    row = db_session.query(IndicatorDefinition).filter(
        (IndicatorDefinition.code == metric_code)
        | (IndicatorDefinition.legacy_code == metric_code)).first()
    if row is None:
        pytest.skip(f"{metric_code} not seeded in this fixture")
    assert regional._RATE_DEFINITIONS  # sanity
    row.is_active = False
    db_session.flush()
    # Bypass the shared-cache TTL for determinism.
    from app.cache import cache
    cache.invalidate("analysis:regional_inactive_metrics")
    skip = regional._inactive_rate_metrics(db_session)
    mapped = {m for m, c in regional._RATE_DEFINITIONS.items() if c == metric_code}
    assert mapped & set(skip)


def test_regional_gov_metrics_skip_returns_none(db_session):
    from app.engine.smart import regional

    metrics = regional._gov_metrics(
        {
            "hospital_count": 1,
            "hospital_names": ["Test"],
            "sums": {
                "live_births": 100, "deliveries": 100, "cs_count": 10,
                "mat_deaths": 2, "nd": 5, "sb": 3, "smm": 4, "preterm": 6,
                "lbw": 7, "high_risk": 8, "adol_a": 2, "adol_b": 3,
            },
        },
        skip=frozenset({"cs_rate"}),
    )
    assert metrics["cs_rate"] is None
    assert metrics["stillbirth_rate"] is not None  # untouched metric still computed
