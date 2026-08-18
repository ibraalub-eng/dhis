import pytest
from app.engine.smart.patterns import detect_composite_patterns, _apriori_itemsets


def _hospital(name, hid, values, gov="Gaza", htype="general"):
    return {"hospital_id": hid, "governorate": gov, "hospital_type": htype, "values": values}


@pytest.fixture
def pattern_data():
    """8 مستشفيات: نصفها بارتفاع متزامن في القيصرية + الولادات المبكرة + وفيات المولودين."""
    data = {}
    for i in range(4):
        data[f"H{i}"] = _hospital(
            f"H{i}", i,
            {"cs_rate": 40.0, "preterm": 20.0, "lbw": 15.0, "nd": 5.0, "smm_total": 5.0,
             "mat_deaths": 1.0, "sb": 2.0, "high_risk": 10.0, "adolescent": 3.0},
        )
    for i in range(4, 8):
        data[f"H{i}"] = _hospital(
            f"H{i}", i,
            {"cs_rate": 12.0, "preterm": 4.0, "lbw": 3.0, "nd": 0.0, "smm_total": 1.0,
             "mat_deaths": 0.0, "sb": 0.0, "high_risk": 5.0, "adolescent": 1.0},
        )
    return data


def test_detects_composite_pattern(pattern_data):
    patterns = detect_composite_patterns(pattern_data, {}, top_n=10)
    assert len(patterns) >= 1
    p = patterns[0]
    assert p.hospitals_count >= 2
    assert p.support > 0
    assert p.lift > 1.0
    # النمط يجب أن يشمل القيصرية المرتفعة مع مؤشر آخر على الأقل
    assert "cs_rate" in p.indicators
    assert len(p.indicators) >= 2


def test_pattern_has_arabic_summary_and_names(pattern_data):
    patterns = detect_composite_patterns(pattern_data, {}, top_n=5)
    assert patterns
    p = patterns[0]
    assert p.summary_ar
    assert len(p.arabic_names) == len(p.indicators)
    assert all(name for name in p.arabic_names)
    assert all(status in ("elevated", "lowered") for status in p.statuses)


def test_patterns_sorted_by_lift(pattern_data):
    patterns = detect_composite_patterns(pattern_data, {}, top_n=10)
    lifts = [p.lift for p in patterns]
    assert lifts == sorted(lifts, reverse=True)


def test_no_patterns_with_few_hospitals():
    data = {
        "H1": _hospital("H1", 1, {"cs_rate": 40.0, "preterm": 20.0, "nd": 5.0}),
        "H2": _hospital("H2", 2, {"cs_rate": 12.0, "preterm": 4.0, "nd": 0.0}),
    }
    assert detect_composite_patterns(data, {}) == []


def test_disabled_returns_empty(pattern_data):
    assert detect_composite_patterns(pattern_data, {}, enabled=False) == []


def test_empty_data():
    assert detect_composite_patterns({}, {}) == []


def test_apriori_itemsets_basic():
    tx = {
        "A": ["cs_rate", "preterm"],
        "B": ["cs_rate", "preterm"],
        "C": ["cs_rate"],
        "D": ["lbw"],
    }
    itemsets = _apriori_itemsets(tx, min_support=0.3)
    assert len(itemsets) >= 1
    found = {(sorted(fs)[0], sorted(fs)[1] if len(fs) > 1 else None): s for fs, s in itemsets}
    assert any(fs == frozenset({"cs_rate", "preterm"}) for fs, _ in itemsets)


def test_patterns_serialized_as_plain_dicts(pattern_data):
    """التسلسل للواجهة يحوّل الأنماط لقواميس بمفاتيح قابلة للقراءة من JS."""
    from app.api.smart_analytics import _sanitize
    patterns = detect_composite_patterns(pattern_data, {}, top_n=5)
    serialized = _sanitize([p.__dict__ for p in patterns])
    assert isinstance(serialized, list)
    for p in serialized:
        assert isinstance(p, dict)
        assert isinstance(p["indicators"], list)
        assert isinstance(p["support"], float)
        assert isinstance(p["lift"], float)
        assert p["summary_ar"]


def test_pipeline_includes_patterns(db_session):
    """run_smart_analytics يضع الأنماط المركبة داخل النتيجة النهائية."""
    from app.engine.smart import run_smart_analytics
    from app.models import Hospital, IndicatorValue, Indicator

    code_to_id = {ind.code: ind.id for ind in db_session.query(Indicator).all()}
    hospitals = []
    for i in range(8):
        h = Hospital(name=f"H{i}", is_active=True)
        db_session.add(h)
        hospitals.append(h)
    db_session.flush()

    for i, h in enumerate(hospitals):
        high = i < 4
        vals = {"2": 200, "5": 80 if high else 24, "6": 190,
                "10": 5 if high else 1, "11": 1 if high else 0,
                "17": 5 if high else 0, "7": 2 if high else 0,
                "6.f": 40 if high else 8, "6.g": 30 if high else 6,
                "2.n": 10, "2.c": 3, "2.d": 2}
        for code, val in vals.items():
            db_session.add(IndicatorValue(
                hospital_id=h.id, indicator_id=code_to_id[code], month="2026-06", value=val
            ))
    db_session.commit()

    result = run_smart_analytics(db_session, "2026-06")
    assert result is not None
    assert isinstance(result.patterns, list)
    assert len(result.patterns) >= 1
    assert result.patterns[0].hospitals_count >= 2
