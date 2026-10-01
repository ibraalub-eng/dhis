"""اختبارات مسار التنبؤ بدرجة المخاطرة عبر آفاق صريحة (1/3/6 أشهر).

التغطية (المرحلة 1 — البندان 1.1 و1.2 من الخطة المعتمدة):
- اختيار النموذج تلقائياً (خطي / متوسط متحرك) بقاعدة R² صريحة.
- اتساع نطاق عدم اليقين مع الأفق (P10–P90 من أخطاء walk-forward).
- الثقة المتناقصة مع الأفق (m+1 كاملة، 3 أشهر ×0.85، 6 أشهر ×0.7).
- عبور عتبات الخطورة عبر _score_to_severity داخل الأفق فقط.
- backtest لكل أفق (يتطلب ≥ 6 أشهر وإلا «غير متاح بعد»).
- التثبيت على تنبؤ XGBoost المتحقَّق منه للشهر m+1.
- الحالات الفارغة (تاريخ فارغ/قصير/نقطة واحدة).
"""
import pytest

from app.engine.smart.trajectory import (
    compute_risk_trajectory,
    run_forecast_trajectory,
    _next_months,
    _choose_model,
    HORIZON_FACTORS,
    BACKTEST_MIN_MONTHS,
)


# ── أدوات ──────────────────────────────────────────────────────────────

def _hist(scores):
    return list(scores)


# ── 1) اختيار النموذج (قاعدة صريحة مُختبَرة) ──────────────────────────

class TestModelSelection:
    def test_linear_for_steady_trend(self):
        """سلسلة صاعدة بانتظام => R² عالٍ => اتجاه خطي."""
        assert _choose_model(_hist([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])) == "linear"

    def test_moving_average_for_volatile_series(self):
        """سلسلة متذبذبة بلا اتجاه => R² منخفض => متوسط متحرك."""
        assert _choose_model(_hist([0.2, 0.8, 0.2, 0.8, 0.2, 0.8])) == "moving_average"

    def test_moving_average_for_short_series(self):
        """أقل من 4 نقاط => متوسط متحرك (لا معنى لملاءمة خط)."""
        assert _choose_model(_hist([0.4, 0.6, 0.5])) == "moving_average"

    def test_moving_average_for_constant_series(self):
        """سلسلة ثابتة (تباين صفري) => متوسط متحرك لا خط وهمي."""
        assert _choose_model(_hist([0.5] * 8)) == "moving_average"


# ── 2) التثبيت على تنبؤ XGBoost للشهر m+1 ─────────────────────────────

class TestAnchoring:
    def test_anchor_replaces_first_point(self):
        traj = compute_risk_trajectory(
            "H", _hist([0.3, 0.35, 0.4, 0.45, 0.5, 0.55]), "2026-06", 3,
            xgb_anchor=0.65,
        )
        assert traj.anchor_applied is True
        assert traj.points[0].value == pytest.approx(0.65)
        assert traj.points[0].month == "2026-07"

    def test_no_anchor_falls_back_to_model_continuation(self):
        """بلا تثبيت XGBoost => الشهر الأول من استمرار النموذج (خطي: 0.55+0.05)."""
        traj = compute_risk_trajectory(
            "H", _hist([0.3, 0.35, 0.4, 0.45, 0.5, 0.55]), "2026-06", 3,
        )
        assert traj.anchor_applied is False
        assert traj.points[0].value == pytest.approx(0.60)

    def test_horizon_three_yields_three_points(self):
        traj = compute_risk_trajectory(
            "H", _hist([0.3, 0.35, 0.4, 0.45, 0.5, 0.55]), "2026-06", 3,
        )
        assert len(traj.points) == 3
        assert [p.horizon_month for p in traj.points] == [1, 2, 3]
        assert [p.month for p in traj.points] == ["2026-07", "2026-08", "2026-09"]


# ── 3) نطاق عدم اليقين يتسع مع الأفق ──────────────────────────────────

class TestIntervalWidensWithHorizon:
    ERRORS = [0.01, 0.02, 0.03, 0.04, 0.05]

    def _traj(self, horizon):
        return compute_risk_trajectory(
            "H", _hist([0.4, 0.42, 0.44, 0.46, 0.48, 0.5]), "2026-06", horizon,
            fold_errors=self.ERRORS,
        )

    def test_width_grows_linearly_with_horizon(self):
        w1 = self._traj(1).points[0].upper - self._traj(1).points[0].lower
        w6 = self._traj(6).points[-1].upper - self._traj(6).points[-1].lower
        assert w6 / w1 == pytest.approx(6, rel=0.01)

    def test_interval_contains_center(self):
        for p in self._traj(6).points:
            assert p.lower <= p.value <= p.upper

    def test_zero_interval_without_errors(self):
        """بلا أخطاء walk-forward موثقة => نطاق منكمش (الحدود = المركز)."""
        traj = compute_risk_trajectory(
            "H", _hist([0.4, 0.42, 0.44, 0.46, 0.48, 0.5]), "2026-06", 3,
        )
        for p in traj.points:
            assert p.lower == pytest.approx(p.value)
            assert p.upper == pytest.approx(p.value)


# ── 4) الثقة المتناقصة مع الأفق ────────────────────────────────────────

class TestConfidenceDecays:
    def test_factors_match_plan(self):
        assert HORIZON_FACTORS == {1: 1.0, 3: 0.85, 6: 0.7}

    def test_confidence_decays_with_horizon(self):
        for h in (1, 3, 6):
            traj = compute_risk_trajectory(
                "H", _hist([0.4, 0.42, 0.44, 0.46, 0.48, 0.5]), "2026-06", h,
                base_confidence=0.8,
            )
            assert traj.confidence == pytest.approx(0.8 * HORIZON_FACTORS[h])
        c1 = compute_risk_trajectory("H", _hist([0.4] * 6), "2026-06", 1).confidence
        c3 = compute_risk_trajectory("H", _hist([0.4] * 6), "2026-06", 3).confidence
        c6 = compute_risk_trajectory("H", _hist([0.4] * 6), "2026-06", 6).confidence
        assert c1 > c3 > c6


# ── 5) عبور العتبات (داخل الأفق فقط) ──────────────────────────────────

class TestThresholdCrossing:
    def test_crossing_detected_within_horizon(self):
        """0.55 أساس (تحذير) + ميل 0.05 => الحرج (0.6) عند الشهر التالي."""
        traj = compute_risk_trajectory(
            "H", _hist([0.30, 0.35, 0.40, 0.45, 0.50, 0.55]), "2026-06", 3,
        )
        c = traj.threshold_crossing
        assert c is not None
        assert c.severity == "critical"
        assert c.month == "2026-07"
        assert c.months_away == 1
        assert c.from_threshold == pytest.approx(0.6)

    def test_no_crossing_when_stable(self):
        traj = compute_risk_trajectory(
            "H", _hist([0.4, 0.4, 0.4, 0.4, 0.4, 0.4]), "2026-06", 3,
        )
        assert traj.threshold_crossing is None

    def test_no_crossing_beyond_horizon(self):
        """ميل خفيف لا يعبر 0.3 داخل 3 أشهر => لا عبور (يُتجاهل ما بعد الأفق)."""
        traj = compute_risk_trajectory(
            "H", _hist([0.26, 0.264, 0.268, 0.272, 0.276, 0.28]), "2026-06", 3,
        )
        assert traj.threshold_crossing is None


# ── 6) backtest لكل أفق (≥ 6 أشهر وإلا «غير متاح») ────────────────────

class TestBacktestPerHorizon:
    def test_backtest_available_with_enough_months(self):
        """سلسلة خطية مثالية => MAE ≈ 0 عبر 8 أشهر."""
        traj = compute_risk_trajectory(
            "H", _hist([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]), "2026-08", 1,
        )
        assert traj.backtest.available is True
        # 8 أشهر − الأفق − 3 نقاط ملاءمة دنيا = 4 تقييمات بنافذة موسّعة
        assert traj.backtest.n_evals == 4
        assert traj.backtest.mae < 0.01

    def test_backtest_unavailable_under_min_months(self):
        traj = compute_risk_trajectory(
            "H", _hist([0.3, 0.35, 0.4, 0.45, 0.5]), "2026-05", 3,
        )
        assert traj.backtest.available is False
        assert traj.backtest.n_evals == 0
        assert "غير متاح" in traj.backtest.note

    def test_min_months_constant_is_six(self):
        assert BACKTEST_MIN_MONTHS == 6


# ── 7) الحالات الفارغة ─────────────────────────────────────────────────

class TestEmptyStates:
    def test_empty_history_yields_empty_trajectory(self):
        traj = compute_risk_trajectory("H", [], "2026-06", 3)
        assert traj.points == []
        assert traj.threshold_crossing is None
        assert traj.backtest.available is False

    def test_single_point_flat_trajectory(self):
        traj = compute_risk_trajectory("H", _hist([0.5]), "2026-06", 3)
        assert len(traj.points) == 3
        assert all(p.value == pytest.approx(0.5) for p in traj.points)

    def test_invalid_horizon_raises(self):
        with pytest.raises(ValueError):
            compute_risk_trajectory("H", _hist([0.5] * 6), "2026-06", 4)


# ── 8) حساب الشهور القادمة (ليّنة عبر نهاية السنة) ─────────────────────

class TestNextMonths:
    def test_within_year(self):
        assert _next_months("2026-06", 3) == ["2026-07", "2026-08", "2026-09"]

    def test_year_rollover(self):
        assert _next_months("2026-11", 3) == ["2026-12", "2027-01", "2027-02"]


# ── 9) التكامل مع قاعدة البيانات ───────────────────────────────────────

def _build_traj_db(months, rising_levels, flat_level=50.0, skip_last_month_for=None):
    """قاعدة مؤقتة: مستشفى A بمستويات صاعدة محددة + مستشفى B ثابت.

    المستويات تُطبَّق على كل مفاتيح الميزات فيتحرك الوسيط معها حتمياً،
    فتصبح درجة المخاطرة (0.5 + (cur/prev − 1)×2) قابلة للحساب المسبق.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import Hospital, Governorate, HospitalType, Indicator, IndicatorValue

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    session.add_all([Governorate(name="Gaza", id=1), HospitalType(name="general", id=1)])
    session.flush()
    session.add(Hospital(id=1, name="Rising", governorate_id=1, hospital_type_id=1, is_active=True))
    session.add(Hospital(id=2, name="Stable", governorate_id=1, hospital_type_id=1, is_active=True))
    session.flush()

    codes = ["2", "5", "6", "10", "11", "7", "6.f", "6.g", "2.n", "2.c", "2.d", "17"]
    for idx, code in enumerate(codes, start=1):
        session.add(Indicator(id=idx, code=code, name=f"ind_{code}"))
    session.flush()

    for mi, month in enumerate(months):
        for hosp_id, levels in ((1, rising_levels), (2, [flat_level] * len(months))):
            if skip_last_month_for == hosp_id and mi == len(months) - 1:
                continue
            for ind_id in range(1, len(codes) + 1):
                session.add(IndicatorValue(
                    hospital_id=hosp_id, indicator_id=ind_id, month=month,
                    value=float(levels[mi]),
                ))
    session.commit()
    return session


class TestRunForecastTrajectory:
    MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04",
              "2026-05", "2026-06", "2026-07", "2026-08"]
    # مستويات تُنتج درجات خطية تماماً 0.1..0.7 (كل نسبة شهرية => 0.5+(r−1)×2)
    RISING = [100.0, 80.0, 68.0, 61.2, 58.14, 58.14, 61.05, 67.155]

    def test_returns_trajectory_per_active_hospital(self):
        session = _build_traj_db(self.MONTHS, self.RISING)
        try:
            result = run_forecast_trajectory(session, "2026-08", 3)
            assert result["base_month"] == "2026-08"
            assert result["horizon"] == 3
            by_name = {t.hospital_name: t for t in result["trajectories"]}
            assert set(by_name) == {"Rising", "Stable"}
            rising = by_name["Rising"]
            assert len(rising.points) == 3
            assert rising.model == "linear"
            # الصاعد يستمر صاعداً داخل الأفق
            assert rising.points[-1].value > rising.points[0].value
        finally:
            session.close()

    def test_stable_hospital_flat_trajectory(self):
        session = _build_traj_db(self.MONTHS, self.RISING)
        try:
            result = run_forecast_trajectory(session, "2026-08", 3)
            stable = next(t for t in result["trajectories"] if t.hospital_name == "Stable")
            assert all(p.value == pytest.approx(0.5) for p in stable.points)
            assert stable.threshold_crossing is None
        finally:
            session.close()

    def test_month_not_in_data_falls_back_to_last_month(self):
        session = _build_traj_db(self.MONTHS, self.RISING)
        try:
            result = run_forecast_trajectory(session, "2026-12", 1)
            assert result["base_month"] == "2026-08"
        finally:
            session.close()

    def test_hospital_without_base_month_data_excluded(self):
        session = _build_traj_db(self.MONTHS, self.RISING, skip_last_month_for=2)
        try:
            result = run_forecast_trajectory(session, "2026-08", 1)
            names = {t.hospital_name for t in result["trajectories"]}
            assert "Stable" not in names
            assert "Rising" in names
        finally:
            session.close()

    def test_backtest_unavailable_note_for_short_history(self):
        session = _build_traj_db(self.MONTHS[:4], self.RISING[:4])
        try:
            result = run_forecast_trajectory(session, "2026-04", 3)
            for t in result["trajectories"]:
                assert t.backtest.available is False
                assert "غير متاح" in t.backtest.note
        finally:
            session.close()

    def test_invalid_horizon_raises(self):
        session = _build_traj_db(self.MONTHS, self.RISING)
        try:
            with pytest.raises(ValueError):
                run_forecast_trajectory(session, "2026-08", 5)
        finally:
            session.close()

    def test_result_carries_statistical_disclaimer(self):
        session = _build_traj_db(self.MONTHS, self.RISING)
        try:
            result = run_forecast_trajectory(session, "2026-08", 3)
            assert "تقدير إحصائي لا تنبؤ مؤكد" in result["note"]
        finally:
            session.close()
