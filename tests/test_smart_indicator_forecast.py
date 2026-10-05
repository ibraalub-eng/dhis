# -*- coding: utf-8 -*-
"""تنبؤ مؤشر واحد عبر عدة مستشفيات يختارها المستخدم خلال أفق زمني صريح.

المرحلة 4 (طلب المستخدم): «تنبؤ بسلوك مؤشر معيّن خلال الفترة الزمنية على
المستشفيات حيث يمكنني اختيار عدة مستشفيات خلال الفترة الزمنية».

- محرك نقي: تعريفات مؤشرات مشتقة (معدل القيصارية، الولادات الميتة، الولادات
  المبكرة، نقص الوزن، الخطر العالي، المراهقات، إجمالي المواليد) بصيغ مطابقة
  لما يحسبه xgboost_predictor، ومسار شهري لكل مستشفى بنفس منهجية
  trajectory.py (خطي إذا R²≥0.6 وإلا متوسط متحرك) مع نطاق يتسع مع الأفق
  ومزيج 30/30/40 للقيمة النهائية وإخلاء مسؤولية إحصائي.
- endpoint: GET /smart/indicator-forecast/{month}?indicator=..&hospital_ids=..&horizon=..
  لعدة مستشفيات يختارها المستخدم بلا أي تغيير في مخطط قاعدة البيانات.
"""
import pytest
from fastapi.testclient import TestClient

from app.engine.smart.indicator_forecast import (
    INDICATOR_DEFS,
    MAX_INDICATOR_FORECAST_HOSPITALS,
    available_indicators,
    forecast_indicator_trajectory,
    indicator_rate_from_values,
    run_indicator_forecast,
)


# ── 1) تعريفات المؤشرات وصيغها ────────────────────────────────────────

class TestIndicatorDefs:
    def test_core_indicator_keys_exist(self):
        for key in ("cs_rate", "stillbirth_rate", "preterm_rate", "lbw_rate",
                    "high_risk_rate", "adolescent_rate", "total_births"):
            assert key in INDICATOR_DEFS, key

    def test_defs_carry_bilingual_labels_and_unit(self):
        for key, d in INDICATOR_DEFS.items():
            assert d.get("label_ar"), key
            assert d.get("label_en"), key
            assert "unit" in d, key

    def test_cs_rate_label_respects_terminology_guard(self):
        # المصطلح المعتمد: «معدل العمليات القيصارية» (لا «معدل القيصارية»)
        assert INDICATOR_DEFS["cs_rate"]["label_ar"] == "معدل العمليات القيصارية"

    def test_available_indicators_shape(self):
        items = available_indicators()
        keys = [i["key"] for i in items]
        assert keys == list(INDICATOR_DEFS.keys())
        assert all(set(i.keys()) == {"key", "label_ar", "label_en", "unit"} for i in items)


class TestRateFormulas:
    """الصيغ مطابقة لـ _load_multi_month_data/_compute_derived_features."""

    def test_cs_rate(self):
        vals = {"5": 50, "2": 200}
        assert indicator_rate_from_values("cs_rate", vals) == pytest.approx(25.0)

    def test_stillbirth_rate_per_1000_live_births(self):
        # المقام المواليد الأحياء (6) — التعريف المعتمد في النظام
        vals = {"7": 5, "6": 400}
        assert indicator_rate_from_values("stillbirth_rate", vals) == pytest.approx(12.5)

    def test_preterm_lbw_highrisk_adolescent_rates(self):
        base = {"6": 400}
        assert indicator_rate_from_values("preterm_rate", {**base, "6.f": 30}) == pytest.approx(7.5)
        assert indicator_rate_from_values("lbw_rate", {**base, "6.g": 40}) == pytest.approx(10.0)
        # مطابقة للمحرك: مقام الخطر العالي/المراهقات هو المواليد الأحياء (6)
        # كما في xgboost_predictor._compute_derived_features
        assert indicator_rate_from_values("high_risk_rate", {**base, "2.n": 80}) == pytest.approx(20.0)
        assert indicator_rate_from_values(
            "adolescent_rate", {**base, "2.c": 10, "2.d": 5}) == pytest.approx(3.75)

    def test_total_births_is_raw_count(self):
        assert indicator_rate_from_values("total_births", {"6": 400}) == pytest.approx(400.0)

    def test_missing_or_zero_denominator_returns_none(self):
        assert indicator_rate_from_values("cs_rate", {"5": 50}) is None
        assert indicator_rate_from_values("cs_rate", {"5": 50, "2": 0}) is None

    def test_missing_numerator_returns_none(self):
        assert indicator_rate_from_values("cs_rate", {"2": 200}) is None
        # مراهقات: غياب أحد المكوّنين يفشل المجموع — بلا صفر صامت
        assert indicator_rate_from_values("adolescent_rate", {"6": 400, "2.c": 10}) is None

    def test_unknown_indicator_raises(self):
        with pytest.raises(ValueError):
            indicator_rate_from_values("nope", {"2": 1})


# ── 2) المسار الشهري النقي لكل مستشفى ─────────────────────────────────

_MONTHS = [f"2026-{m:02d}" for m in range(1, 9)]


def _hist(values):
    return list(zip(_MONTHS[:len(values)], values))


class TestForecastIndicatorTrajectory:
    def test_invalid_horizon_raises(self):
        with pytest.raises(ValueError):
            forecast_indicator_trajectory(_hist([20, 21, 22, 23]), 4)

    def test_rising_series_uses_linear_model(self):
        out = forecast_indicator_trajectory(_hist([20, 21, 22, 23, 24, 25, 26, 27]), 3)
        assert out["available"] is True
        assert out["model"] == "linear"
        values = [p["value"] for p in out["points"]]
        assert len(values) == 3
        assert values == sorted(values)
        assert values[-1] == pytest.approx(30.0, abs=0.05)  # امتداد ميل +1
        assert out["current"] == pytest.approx(27.0)

    def test_flat_series_uses_moving_average_and_symmetric_band(self):
        out = forecast_indicator_trajectory(_hist([25.0] * 6), 3)
        assert out["available"] is True
        assert out["model"] == "moving_average"
        p1 = out["points"][0]
        assert p1["value"] == pytest.approx(25.0, abs=0.01)
        assert p1["value"] - p1["lower"] == pytest.approx(p1["upper"] - p1["value"])

    def test_band_widens_with_horizon(self):
        out = forecast_indicator_trajectory(_hist([20, 22, 19, 23, 21, 24, 20, 25]), 3)
        w1 = out["points"][0]["upper"] - out["points"][0]["lower"]
        w3 = out["points"][2]["upper"] - out["points"][2]["lower"]
        assert w3 > w1

    def test_single_point_unavailable(self):
        out = forecast_indicator_trajectory(_hist([25.0]), 3)
        assert out["available"] is False
        assert "تاريخ كافٍ" in out["note"]
        assert out["points"] == []
        assert out["current"] == pytest.approx(25.0)

    def test_two_points_path_available_but_blend_not(self):
        out = forecast_indicator_trajectory(_hist([25.0, 26.0]), 3)
        assert out["available"] is True          # مسار بالمتوسط المتحرك
        assert out["blended"]["available"] is False  # المزيج يتطلب ≥3 أشهر

    def test_confidence_decreases_with_horizon(self):
        h = _hist([20, 21, 22, 23, 24, 25, 26, 27])
        c1 = forecast_indicator_trajectory(h, 1)["confidence"]
        c6 = forecast_indicator_trajectory(h, 6)["confidence"]
        assert c6 < c1

    def test_months_are_next_after_base(self):
        out = forecast_indicator_trajectory(
            [("2026-03", 20.0), ("2026-04", 21.0), ("2026-05", 22.0)], 3)
        # الأساس آخر شهر في السلسلة => الأشهر المتوقعة 2026-06 و2026-07 و2026-08
        assert [p["month"] for p in out["points"]] == ["2026-06", "2026-07", "2026-08"]

    def test_blended_final_uses_30_30_40(self):
        out = forecast_indicator_trajectory(
            _hist([20, 21, 22, 23, 24, 25]), 1, peer_mean=30.0)
        b = out["blended"]
        assert b["available"] is True
        final = out["points"][-1]["value"]
        expected = 0.3 * final + 0.3 * 30.0 + 0.4 * (sum(range(20, 26)) / 6)
        assert b["forecast"] == pytest.approx(expected, abs=0.01)
        assert b["lower"] <= b["forecast"] <= b["upper"]

    def test_note_carries_statistical_disclaimer(self):
        out = forecast_indicator_trajectory(_hist([20, 21, 22, 23]), 3)
        assert "تقدير إحصائي" in out["note"]

    def test_direction_rising_falling_stable(self):
        up = forecast_indicator_trajectory(_hist([20, 21, 22, 23, 24, 25]), 1)
        down = forecast_indicator_trajectory(_hist([25, 24, 23, 22, 21, 20]), 1)
        flat = forecast_indicator_trajectory(_hist([25.0] * 6), 1)
        assert up["direction"] == "rising"
        assert down["direction"] == "falling"
        assert flat["direction"] == "stable"


# ── 3) endpoint عدة مستشفيات ──────────────────────────────────────────

@pytest.fixture
def client(db_session):
    from app.main import app
    from app.database import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_series(db, hid, months_values):
    """زرع قيم مؤشرات: {month: {code: value}} للمستشفى hid."""
    from app.models import Indicator, IndicatorValue

    def _iid(code):
        ind = db.query(Indicator).filter(Indicator.code == code).first()
        if not ind:
            ind = Indicator(code=code, name=code)
            db.add(ind)
            db.flush()
        return ind.id

    for month, vals in months_values.items():
        for code, v in vals.items():
            db.add(IndicatorValue(
                hospital_id=hid, month=month, indicator_id=_iid(code), value=float(v)))
    db.commit()


def _cs_months(base_vals, cs_vals):
    """{month: {2:..., 5:...}} لستة أشهر 2026-01..2026-06."""
    out = {}
    for i, m in enumerate([f"2026-{k:02d}" for k in range(1, 7)]):
        out[m] = {"2": base_vals[i] if base_vals else 200, "5": cs_vals[i]}
    return out


def test_endpoint_returns_per_hospital_paths(client, db_session):
    _seed_series(db_session, 1, _cs_months(None, [40, 50, 60, 64, 70, 76]))
    _seed_series(db_session, 2, _cs_months(None, [30, 30, 30, 30, 30, 30]))
    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=1,2&horizon=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_month"] == "2026-06"
    assert data["indicator"] == "cs_rate"
    assert data["indicator_ar"] == "معدل العمليات القيصارية"
    assert data["horizon"] == 3
    assert "تقدير إحصائي" in data["note"]
    assert len(data["hospitals"]) == 2
    up = next(h for h in data["hospitals"] if h["hospital_id"] == 1)
    assert up["model"] == "linear"
    assert len(up["points"]) == 3
    assert [p["month"] for p in up["points"]] == ["2026-07", "2026-08", "2026-09"]
    assert up["points"][-1]["value"] > up["current"]
    assert up["series"][-1]["month"] == "2026-06"
    flat = next(h for h in data["hospitals"] if h["hospital_id"] == 2)
    # 30 قيصرية من 200 ولادة ثابتة => 15% طوال الأشهر => متوسط متحرك
    assert flat["points"][-1]["value"] == pytest.approx(15.0, abs=0.1)
    assert up["blended"]["available"] is True


def test_endpoint_indicator_catalog(client):
    resp = client.get("/smart/indicator-catalog")
    assert resp.status_code == 200
    items = resp.json()
    keys = [i["key"] for i in items]
    assert "cs_rate" in keys and "stillbirth_rate" in keys
    assert all("label_ar" in i and "label_en" in i for i in items)


def test_endpoint_unknown_hospital_goes_to_unavailable(client, db_session):
    _seed_series(db_session, 1, _cs_months(None, [40, 50, 60, 64, 70, 76]))
    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=1,999&horizon=1")
    assert resp.status_code == 200
    data = resp.json()
    assert [h["hospital_id"] for h in data["hospitals"]] == [1]
    un = data["unavailable"]
    assert len(un) == 1 and un[0]["hospital_id"] == 999


def test_endpoint_insufficient_history_stays_unavailable(client, db_session):
    """شهر واحد لا يكفي لمسار — يبقى ضمن hospitals بعلامة available=False (وليس صفراً صامتاً)."""
    _seed_series(db_session, 1, {"2026-06": {"2": 200, "5": 50}})
    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=1&horizon=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["unavailable"] == []
    assert len(data["hospitals"]) == 1
    h = data["hospitals"][0]
    assert h["available"] is False
    assert h["points"] == []
    assert h["current"] == pytest.approx(25.0)
    assert h["series"][0]["month"] == "2026-06"


def test_endpoint_missing_denominator_month_dropped(client, db_session):
    # 2026-03 بلا مقام (2) => يُسقط من السلسلة (بيانات ناقصة لا صفر صامت)
    months = _cs_months(None, [40, 50, 60, 64, 70, 76])
    months["2026-03"] = {"5": 60}
    _seed_series(db_session, 1, months)
    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=1&horizon=1")
    assert resp.status_code == 200
    series_months = [s["month"] for s in resp.json()["hospitals"][0]["series"]]
    assert "2026-03" not in series_months
    assert len(series_months) == 5


def test_endpoint_month_falls_back_to_latest(client, db_session):
    _seed_series(db_session, 1, _cs_months(None, [40, 50, 60, 64, 70, 76]))
    resp = client.get("/smart/indicator-forecast/2030-01?indicator=cs_rate&hospital_ids=1&horizon=1")
    assert resp.status_code == 200
    assert resp.json()["base_month"] == "2026-06"


def test_endpoint_invalid_indicator_422(client):
    resp = client.get("/smart/indicator-forecast/2026-06?indicator=foo&hospital_ids=1&horizon=1")
    assert resp.status_code == 422


def test_endpoint_invalid_horizon_422(client):
    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=1&horizon=5")
    assert resp.status_code == 422


def test_endpoint_missing_hospital_ids_422(client):
    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=&horizon=1")
    assert resp.status_code == 422


def test_endpoint_caps_selected_hospitals_422(client):
    ids = ",".join(str(i) for i in range(1, MAX_INDICATOR_FORECAST_HOSPITALS + 2))
    resp = client.get(f"/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids={ids}&horizon=1")
    assert resp.status_code == 422


def test_stillbirth_rate_endpoint_second_formula(client, db_session):
    # 6=400 ثابت، 7=2..7 => سلسلة خطية تماماً: 5، 7.5، 10، 12.5، 15، 17.5 لكل 1000
    months = {}
    for i, m in enumerate([f"2026-{k:02d}" for k in range(1, 7)]):
        months[m] = {"6": 400, "7": 2 + i}
    _seed_series(db_session, 1, months)
    resp = client.get("/smart/indicator-forecast/2026-06?indicator=stillbirth_rate&hospital_ids=1&horizon=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["indicator_ar"] == "معدل الولادات الميتة"
    h = data["hospitals"][0]
    assert h["current"] == pytest.approx(17.5)
    assert h["model"] == "linear"
    assert [p["value"] for p in h["points"]] == pytest.approx([20.0, 22.5, 25.0])
    assert [p["month"] for p in h["points"]] == ["2026-07", "2026-08", "2026-09"]


# ── 4) مقارنة النظراء: الملكية وشريحة الحجم مع مئين الموقع ────────────

_M6 = [f"2026-{k:02d}" for k in range(1, 7)]


def _seed_ownership_and_sizes(db):
    """ملكيّتان (حكومي/خاص) + مستشفى رابع خاص؛ الشرائح تُشتق من قيم «6» لاحقاً."""
    from app.models import FacilityOwnership, Hospital

    pub = FacilityOwnership(name="حكومي")
    prv = FacilityOwnership(name="خاص")
    db.add_all([pub, prv])
    db.flush()
    db.query(Hospital).filter(Hospital.id.in_([1, 2])).update(
        {"facility_ownership_id": pub.id}, synchronize_session=False)
    db.add(Hospital(name="Private Clinic", region="Region C", facility_ownership_id=prv.id))
    db.commit()
    return pub, prv


def _seed_births(db, hid, v):
    """قيم مؤشر «6» (المواليد الأحياء) على كامل المدة لاشتقاق شريحة الحجم."""
    _seed_series(db, hid, {m: {"6": v} for m in _M6})


class TestIndicatorPeerPercentilePure:
    """التجميع النقي: ترتيب تنازلي بالقيمة، مئين صاعد، كسر تعادل بالاسم."""

    def test_ranks_and_percentiles_within_groups(self):
        from app.engine.smart.indicator_forecast import peer_percentiles_for_indicator
        groups = peer_percentiles_for_indicator(
            {"a": 23.0, "b": 15.0, "c": 15.0, "d": 5.0},
            {"a": "حكومي", "b": "حكومي", "c": "خاص", "d": "خاص"})
        assert groups["a"]["ownership"]["available"] is True
        assert (groups["a"]["ownership"]["rank"], groups["a"]["ownership"]["total"]) == (1, 2)
        assert groups["a"]["ownership"]["percentile"] == pytest.approx(100.0)
        # التعادل 15/15 يُكسر بالاسم حتمياً: c قبل d
        assert (groups["c"]["ownership"]["rank"], groups["d"]["ownership"]["rank"]) == (1, 2)
        assert groups["c"]["ownership"]["percentile"] == pytest.approx(100.0)
        assert groups["d"]["ownership"]["percentile"] == pytest.approx(50.0)
        # بلا شريحة حجم => غير متاح بالسبب (لا صفر صامت)
        assert groups["a"]["size"]["available"] is False and groups["a"]["size"]["reason"]

    def test_missing_ownership_and_singleton_tier_unavailable(self):
        from app.engine.smart.indicator_forecast import peer_percentiles_for_indicator
        pp = peer_percentiles_for_indicator({"a": 10.0}, {"a": None})
        assert pp["a"]["ownership"]["available"] is False and pp["a"]["ownership"]["reason"]
        assert pp["a"]["size"]["available"] is False and pp["a"]["size"]["reason"]


def test_endpoint_returns_ownership_and_size_percentiles(client, db_session):
    _seed_ownership_and_sizes(db_session)
    months = _cs_months(None, [40, 50, 60, 64, 70, 76])
    _seed_series(db_session, 1, months)
    _seed_series(db_session, 2, _cs_months(None, [30, 30, 30, 30, 30, 30]))
    _seed_series(db_session, 3, _cs_months(None, [20, 20, 20, 20, 20, 20]))
    _seed_series(db_session, 4, _cs_months(None, [20, 20, 20, 20, 20, 20]))  # 10% — دون 1 ضمن شريحته
    # شرائح الحجم عبر متوسط «6»: 1 و4 كبيرتان، 2 متوسطة، 3 صغيرة
    for hid, v in ((1, 500), (2, 200), (3, 50), (4, 500)):
        _seed_births(db_session, hid, v)

    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=1,2&horizon=1")
    assert resp.status_code == 200
    by_id = {h["hospital_id"]: h for h in resp.json()["hospitals"]}
    # الملكية: 1 و2 حكومي (23% مقابل 15%) — الأعلى رتبة 1 ومئين 100
    own1 = by_id[1]["peer_percentiles"]["ownership"]
    own2 = by_id[2]["peer_percentiles"]["ownership"]
    assert (own1["rank"], own1["total"], own1["percentile"]) == (1, 2, 100.0)
    assert (own2["rank"], own2["total"], own2["percentile"]) == (2, 2, 50.0)
    # الحجم: 1 و4 (500) كبيرتان — الأعلى قيصرياً رتبة 1 من 2
    sz1 = by_id[1]["peer_percentiles"]["size"]
    assert (sz1["rank"], sz1["total"], sz1["percentile"]) == (1, 2, 100.0)
    # 2 وحدها في شريحتها (200) => شريحة الحجم غير متاحة لها بالسبب
    sz2 = by_id[2]["peer_percentiles"]["size"]
    assert sz2["available"] is False and sz2["reason"]
    # ملكية كل مستشفى موثقة في صفه
    assert by_id[1]["ownership_ar"] == "حكومي"
    assert by_id[2]["ownership_ar"] == "حكومي"


def test_ownership_peer_group_of_three_ranks_and_size_labels(client, db_session):
    pub, _prv = _seed_ownership_and_sizes(db_session)
    from app.models import Hospital
    db_session.add(Hospital(name="General Two", region="Region D",
                            facility_ownership_id=pub.id))
    db_session.commit()
    _seed_series(db_session, 1, _cs_months(None, [40, 50, 60, 64, 70, 76]))   # 23%
    _seed_series(db_session, 2, _cs_months(None, [30, 30, 30, 30, 30, 30]))   # 15%
    _seed_series(db_session, 3, _cs_months(None, [20, 20, 20, 20, 20, 20]))   # 10%
    _seed_series(db_session, 5, _cs_months(None, [10, 10, 10, 10, 10, 10]))   # 5%
    for hid, v in ((1, 500), (2, 200), (3, 50), (5, 500)):
        _seed_births(db_session, hid, v)

    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=1,2,3,5&horizon=1")
    assert resp.status_code == 200
    by_id = {h["hospital_id"]: h for h in resp.json()["hospitals"]}
    # الملكية: 1 و2 و5 حكومي (23/15/5) — رتبة تنازلية ومئين صاعد بمعدل 33.3
    pp = {h: by_id[h]["peer_percentiles"]["ownership"] for h in (1, 2, 5)}
    assert (pp[1]["rank"], pp[1]["total"], pp[1]["percentile"]) == (1, 3, 100.0)
    assert (pp[2]["rank"], pp[2]["total"], pp[2]["percentile"]) == (2, 3, 66.7)
    assert (pp[5]["rank"], pp[5]["total"], pp[5]["percentile"]) == (3, 3, 33.3)
    # الشرائح: ثالثات كمية على متوسط «6» => كبير/متوسط/صغير
    assert by_id[1]["peer_percentiles"]["size"]["peer_label_ar"] == "كبير"
    assert by_id[2]["peer_percentiles"]["size"]["peer_label_ar"] == "متوسط"
    assert by_id[3]["peer_percentiles"]["size"]["peer_label_ar"] == "صغير"
    # 3 بلا ملكية => مجموعة الملكية غير متاحة لها بالسبب
    assert by_id[3]["peer_percentiles"]["ownership"]["available"] is False


def test_percentiles_computed_over_all_active_hospitals_not_only_selected(client, db_session):
    pub, _prv = _seed_ownership_and_sizes(db_session)
    from app.models import Hospital
    # 3 يدخل مجموعة حكومي (ليصبح المجتمع 1 و2 و3) و4 يبقى خاصاً
    db_session.query(Hospital).filter(Hospital.id == 3).update(
        {"facility_ownership_id": pub.id}, synchronize_session=False)
    db_session.commit()
    _seed_series(db_session, 1, _cs_months(None, [40, 50, 60, 64, 70, 76]))
    _seed_series(db_session, 2, _cs_months(None, [30, 30, 30, 30, 30, 30]))
    # 3 و4 غير مختارين لكن بياناتهما تشارك في مجموعات النظراء
    _seed_series(db_session, 3, _cs_months(None, [10, 10, 10, 10, 10, 10]))
    _seed_series(db_session, 4, _cs_months(None, [60, 60, 60, 60, 60, 60]))
    for hid in (1, 2, 3, 4):
        _seed_births(db_session, hid, 300)

    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=1&horizon=1")
    h = resp.json()["hospitals"][0]
    own = h["peer_percentiles"]["ownership"]
    sz = h["peer_percentiles"]["size"]
    assert own["total"] == 3   # حكومي فقط (1 و2 و3) — 4 خاص مستبعد
    assert own["rank"] == 1 and own["percentile"] == pytest.approx(100.0)
    assert sz["total"] == 4 and sz["rank"] == 1  # قيم «6» متساوية => شريحة واحدة للجميع


def test_peer_group_skips_hospitals_without_base_month_value(client, db_session):
    pub, _prv = _seed_ownership_and_sizes(db_session)
    from app.models import Hospital
    # 3 يدخل مجموعة حكومي أيضاً ليبقى بعد استبعاد 2 نظيران اثنان
    db_session.query(Hospital).filter(Hospital.id == 3).update(
        {"facility_ownership_id": pub.id}, synchronize_session=False)
    db_session.commit()
    _seed_series(db_session, 1, _cs_months(None, [40, 50, 60, 64, 70, 76]))
    # 2 له تاريخ حتى 2026-04 فقط — بلا قيمة عند الأساس 2026-06 فيستبعد من النظراء
    _seed_series(db_session, 2, {m: {"2": 200, "5": 30} for m in _M6[:4]})
    _seed_series(db_session, 3, _cs_months(None, [20, 20, 20, 20, 20, 20]))
    resp = client.get("/smart/indicator-forecast/2026-06?indicator=cs_rate&hospital_ids=1&horizon=1")
    own = resp.json()["hospitals"][0]["peer_percentiles"]["ownership"]
    assert (own["rank"], own["total"]) == (1, 2)
