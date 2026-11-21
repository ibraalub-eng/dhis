"""Configured reference benchmarks participate in the alert scan.

``IndicatorDefinition.global_reference_value`` / ``local_reference_value`` are
FIXED benchmarks, unlike the computed peer/history baselines:

* each configured value is its own comparison perspective, so a definition
  that carries both yields two independent findings;
* a NULL (or 0, which has no percentage base) contributes nothing at all and
  is never read as a zero baseline;
* the deviation is banded with the same percentages the trend policy exposes,
  and a single value can never claim the top band because it has no spread.
"""
import inspect
from types import SimpleNamespace

from app.engine import quality_alerts as engine
from app.engine import severity as severity_policy
from app.engine.anomaly import layered

BANDS = {"stable": 2.0, "low": 5.0, "moderate": 15.0, "high": 30.0}


def _resolved(**definition):
    return SimpleNamespace(code="X", name="Indicator", unit="%",
                           definition=SimpleNamespace(**definition))


def test_reference_deviation_needs_a_usable_base():
    assert engine.reference_deviation_pct(110, 100) == 10.0
    assert engine.reference_deviation_pct(90, 100) == -10.0
    # NULL is absent and 0 has no percentage base — neither is a comparison.
    assert engine.reference_deviation_pct(5, None) is None
    assert engine.reference_deviation_pct(5, 0) is None


def test_reference_score_reuses_the_trend_band_percentages():
    assert engine.reference_score(1.9, BANDS) is None
    low = engine.reference_score(3.0, BANDS)
    moderate = engine.reference_score(10.0, BANDS)
    high = engine.reference_score(20.0, BANDS)
    assert 0.25 <= low < 0.50
    assert 0.50 <= moderate < 0.75
    assert 0.75 <= high < 0.90
    # Magnitude decides the band, not the sign.
    assert engine.reference_score(-20.0, BANDS) == high


def test_reference_score_never_reaches_the_top_band():
    assert engine.reference_score(1000.0, BANDS) == engine.REFERENCE_MAX_SCORE
    assert (layered.level_for_score(engine.REFERENCE_MAX_SCORE)
            == layered.LEVEL_HIGH)


def test_both_references_are_independent_perspectives():
    resolved = _resolved(global_reference_value=80.0,
                         local_reference_value=95.0)
    findings = engine.reference_findings(resolved, 70.0, BANDS)
    assert [f["perspective"] for f in findings] == [
        engine.PERSPECTIVE_GLOBAL_REFERENCE,
        engine.PERSPECTIVE_LOCAL_REFERENCE,
    ]
    # 70 vs 80 = -12.5% (moderate band); 70 vs 95 = -26.3% (high band).
    assert 0.50 <= findings[0]["score"] < 0.75
    assert 0.75 <= findings[1]["score"] < 0.90
    assert findings[0]["baseline"] == 80.0
    assert findings[1]["baseline"] == 95.0
    # A configured value is one point: no z, no peer count, no spread.
    assert findings[0]["z"] is None
    assert findings[0]["peer_count"] is None
    assert findings[0]["stats"]["std"] is None
    assert findings[0]["method"] == engine.METHOD_REFERENCE_DEVIATION
    assert findings[0]["reference"]["value"] == 80.0
    assert findings[0]["reference"]["deviation_pct"] == -12.5


def test_range_deviation_is_measured_from_the_nearest_bound():
    assert engine.reference_range_deviation_pct(50, 40, 60) == 0.0
    assert engine.reference_range_deviation_pct(30, 40, 60) == -25.0
    assert engine.reference_range_deviation_pct(75, 40, 60) == 25.0
    # A bound of 0 has no percentage base — no invented deviation.
    assert engine.reference_range_deviation_pct(-5, 0, 10) is None


def test_a_family_target_range_replaces_its_single_value():
    resolved = _resolved(global_reference_value=80.0,
                         global_target_min=40.0, global_target_max=60.0)
    # Inside the range there is nothing to review, even though 50 differs
    # from the single reference value of 80.
    assert engine.reference_findings(resolved, 50.0, BANDS) == []

    findings = engine.reference_findings(resolved, 70.0, BANDS)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["perspective"] == engine.PERSPECTIVE_GLOBAL_REFERENCE
    assert finding["reference"]["basis"] == "target_range"
    assert finding["reference"]["range"] == {"min": 40.0, "max": 60.0}
    assert finding["reference"]["edge"] == "max"
    assert finding["baseline"] == 60.0
    # 70 vs the nearest bound 60 = +16.67% (between moderate and high).
    assert 0.75 <= finding["score"] < 0.90


def test_a_family_range_needs_both_bounds():
    half = _resolved(global_reference_value=80.0,
                     global_target_min=40.0, global_target_max=None)
    findings = engine.reference_findings(half, 70.0, BANDS)
    assert [f["reference"]["basis"] for f in findings] == ["value"]
    assert findings[0]["baseline"] == 80.0


def test_each_family_target_range_is_independent():
    resolved = _resolved(global_target_min=0.0, global_target_max=10.0,
                         local_target_min=60.0, local_target_max=90.0)
    findings = engine.reference_findings(resolved, 80.0, BANDS)
    # Global: 80 is 700% above its max. Local: 80 is inside 60-90.
    assert [f["perspective"] for f in findings] == [
        engine.PERSPECTIVE_GLOBAL_REFERENCE]
    assert findings[0]["reference"]["deviation_pct"] == 700.0


def test_each_family_has_its_own_direction():
    definition = SimpleNamespace(global_direction="lower_is_better",
                                 local_direction="higher_is_better")
    # The local family's direction interprets its own row; everything else
    # keeps the resolved (global) direction.
    assert engine.interpretation_direction(
        definition, engine.PERSPECTIVE_LOCAL_REFERENCE,
        "lower_is_better") == "higher_is_better"
    assert engine.interpretation_direction(
        definition, engine.PERSPECTIVE_GLOBAL_REFERENCE,
        "lower_is_better") == "lower_is_better"


def test_a_family_without_its_own_direction_falls_back():
    definition = SimpleNamespace(global_direction="lower_is_better")
    assert engine.interpretation_direction(
        definition, engine.PERSPECTIVE_LOCAL_REFERENCE, "none") == "none"
    assert engine.interpretation_direction(
        None, engine.PERSPECTIVE_LOCAL_REFERENCE, "higher_is_better") == "higher_is_better"


def test_resolve_direction_prefers_the_global_family_direction():
    resolved = SimpleNamespace(code="X", definition=SimpleNamespace(
        global_direction="higher_is_better", direction="lower_is_better",
        target_min=None, target_max=None))
    assert engine.resolve_direction(None, resolved)[0] == "higher_is_better"

    legacy_only = SimpleNamespace(code="X", definition=SimpleNamespace(
        global_direction=None, direction="lower_is_better",
        target_min=None, target_max=None))
    assert engine.resolve_direction(None, legacy_only)[0] == "lower_is_better"


def test_interpretation_uses_the_finding_family_range():
    definition = SimpleNamespace(local_target_min=60.0, local_target_max=90.0)
    assert engine.interpretation_targets(
        definition, engine.PERSPECTIVE_LOCAL_REFERENCE, 0.0, 10.0) == (60.0, 90.0)
    # A family without a range keeps the resolved definition targets.
    assert engine.interpretation_targets(
        definition, engine.PERSPECTIVE_GLOBAL_REFERENCE, 0.0, 10.0) == (0.0, 10.0)


def test_a_null_reference_contributes_nothing():
    none_set = _resolved(global_reference_value=None,
                         local_reference_value=None)
    assert engine.reference_findings(none_set, 70.0, BANDS) == []

    local_only = _resolved(global_reference_value=None,
                           local_reference_value=50.0)
    keys = [f["perspective"]
            for f in engine.reference_findings(local_only, 70.0, BANDS)]
    assert keys == [engine.PERSPECTIVE_LOCAL_REFERENCE]


def test_a_zero_reference_is_skipped_not_treated_as_a_base():
    resolved = _resolved(global_reference_value=0.0)
    assert engine.reference_findings(resolved, 70.0, BANDS) == []


def test_a_definition_without_a_row_has_no_reference():
    resolved = SimpleNamespace(code="X", name="Indicator", unit="",
                               definition=None)
    assert engine.reference_findings(resolved, 70.0, BANDS) == []


def test_reference_rows_are_not_statistical_outliers():
    assert (engine._severity_source(engine.PERSPECTIVE_GLOBAL_REFERENCE)
            == severity_policy.SOURCE_REFERENCE_BENCHMARK)
    assert severity_policy.SOURCE_REFERENCE_BENCHMARK in severity_policy.SOURCES


def test_interpretation_compares_against_the_reference_value():
    # The reference replaces the baseline in interpret_deviation, so the label
    # states whether being ABOVE the configured value is good or concerning.
    assert (engine.interpret_deviation("lower_is_better", 120, 100)
            == engine.INTERP_HIGH_CONCERN)
    assert (engine.interpret_deviation("higher_is_better", 120, 100)
            == engine.INTERP_HIGH_FAVORABLE)
    assert (engine.interpret_deviation("none", 120, 100)
            == engine.INTERP_STATISTICAL_ONLY)


def test_reason_names_the_target_range_and_its_nearest_bound():
    text = engine._reason_text(
        _resolved(), engine.PERSPECTIVE_LOCAL_REFERENCE, "HIGH",
        70.0, 60.0, None, None, engine.INTERP_OUTSIDE_TARGET,
        reference={"range": {"min": 40.0, "max": 60.0},
                   "basis": "target_range"})
    assert "configured local reference range 40–60" in text
    assert "nearest bound 60" in text


def test_reason_names_the_configured_reference():
    text = engine._reason_text(
        _resolved(), engine.PERSPECTIVE_GLOBAL_REFERENCE, "HIGH",
        70.0, 80.0, None, None, engine.INTERP_HIGH_CONCERN)
    assert "configured global reference 80" in text
    assert "baseline" not in text


def test_family_settings_merge_prefers_the_representative_then_fills_nulls():
    """Settings are formula-level: the representative wins, blanks are absent.

    A NULL (or blank) on the analysed copy is not a decision — it is "not
    recorded" — so the value of another registration fills it. A value the
    representative DOES record always wins over a stale duplicate.
    """
    from app.engine import indicator_service

    representative = SimpleNamespace(code="REP", definition=SimpleNamespace(
        code="REP", global_direction=None, direction="",
        local_direction="lower_is_better", global_reference_value=None))
    clinical = SimpleNamespace(code="CLIN", definition=SimpleNamespace(
        code="CLIN", global_direction="higher_is_better",
        direction="lower_is_better", global_reference_value=42.0))

    settings = indicator_service.merge_family_settings([representative, clinical])
    assert settings.global_direction == "higher_is_better"   # NULL on the rep
    assert settings.direction == "lower_is_better"           # "" is not a value
    assert settings.local_direction == "lower_is_better"     # the rep's own value
    assert settings.global_reference_value == 42.0
    # Unrecorded settings stay absent, never invented as 0.
    assert getattr(settings, "local_reference_value", None) is None
    # The merged view is readable exactly like a definition row.
    assert engine.reference_bounds(settings, "global_target_min",
                                   "global_target_max") is None


def test_a_raw_element_has_no_family_settings():
    """Data elements have no registry definition, so the view stays absent
    (they keep their existing stored-value / threshold-table behaviour)."""
    from app.engine import indicator_service

    raw = SimpleNamespace(code="6.f", definition=None)
    assert indicator_service.family_settings_view(raw) is None


def test_a_raw_element_reads_its_own_direction():
    """Elements have no definition row: the direction lives on the element."""
    element = SimpleNamespace(code="17", global_direction="lower_is_better")
    assert engine.resolve_direction(None, element) == (
        "lower_is_better", None, None)

    # Unset (NULL) or explicitly "none" keeps the threshold fallback, so an
    # element nobody configured behaves exactly as before the column existed.
    for value in (None, "none"):
        unset = SimpleNamespace(code="QA_NO_THRESHOLD", global_direction=value)
        assert engine.resolve_direction(None, unset)[0] == "none"

    # An element has no range columns: a stored target_range (or any unknown
    # value) must never be read as an unbounded range labelled "within target".
    for value in ("target_range", "worse", " ", " LOWER_IS_BETTER "):
        invalid = SimpleNamespace(code="QA_NO_THRESHOLD", global_direction=value)
        assert engine.resolve_direction(None, invalid)[0] == "none"


def test_the_scan_evaluates_references_without_a_peer_group():
    """References must not sit behind the peer-comparability safeguard."""
    source = inspect.getsource(engine.scan)
    assert "reference_findings(" in source
    assert "if (peers_allowed and peers_comparable)" in source
    assert "if history_allowed and peers_comparable" in source
    # The reference findings are built inside the hospital loop, before any
    # peer group is required.
    assert source.index("reference_findings(") < source.index(
        "PEER_PERSPECTIVES if (peers_allowed")
