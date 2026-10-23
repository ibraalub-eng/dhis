"""Severity normalization, temporal-trend configuration and resolution tests.

Covers the acceptance criteria of the System Control centralization:

* one shared severity vocabulary with the original engine level preserved;
* trend settings saved through System Control, validated, persisted and used
  by the real trend engine / Quality Alerts scan;
* three distinguishable outputs (base / trend / final) on persisted results;
* the single authoritative Z-score threshold (saved 2.5);
* a saved policy only takes effect on the next scan: stored results are marked
  stale first, then re-resolved by the scan that applies the new policy;
* missing configuration is reported, never silently replaced.
"""
import pytest
from fastapi.testclient import TestClient

from app.engine import severity as sev
from app.engine.anomaly import analyze_historical_trends
from app.engine.severity import (
    LEVEL_HIGH,
    LEVEL_LOW,
    LEVEL_MODERATE,
    LEVEL_NONE,
    LEVEL_VERY_HIGH,
    AnalysisConfigError,
    TrendAssessment,
    UnknownSeverityError,
    assess_trend,
    load_analysis_config,
    normalize_severity,
    raise_level,
    resolve_severity,
    resolve_trend_settings,
)
from app.models import (
    AppConfig,
    Hospital,
    Indicator,
    IndicatorDefinition,
    IndicatorValue,
    QualityAlert,
    QualityAlertAudit,
    SystemSetting,
)


@pytest.fixture
def client(app):
    return TestClient(app)


def _trend(**overrides) -> TrendAssessment:
    data = dict(
        enabled=True,
        evaluated=True,
        direction="increasing",
        direction_relevant=True,
        points=6,
        months=tuple(f"2026-{i:02d}" for i in range(1, 7)),
        slope_pct=8.0,
        cumulative_change_pct=30.0,
        persistence_months=4,
        min_persistence=3,
        min_cumulative_change_pct=5.0,
        r_squared=0.9,
        severity=LEVEL_HIGH,
        qualifies=True,
        reason="increasing trend",
    )
    data.update(overrides)
    return TrendAssessment(**data)


# ── One shared severity vocabulary ─────────────────────────────────────────

def test_normalize_preserves_engine_level_and_maps_aliases():
    critical = normalize_severity("CRITICAL", source=sev.SOURCE_CLINICAL_RULE)
    assert critical.level == LEVEL_VERY_HIGH
    assert critical.engine_level == "CRITICAL"
    assert critical.source == sev.SOURCE_CLINICAL_RULE
    assert "CRITICAL" in critical.reason

    medium = normalize_severity("MEDIUM", source=sev.SOURCE_DATA_QUALITY)
    assert medium.level == LEVEL_MODERATE
    assert medium.engine_level == "MEDIUM"

    assert normalize_severity("negligible", source=sev.SOURCE_TEMPORAL_TREND).level == LEVEL_NONE
    assert normalize_severity("very high", source=sev.SOURCE_STATISTICAL_OUTLIER).level == LEVEL_VERY_HIGH
    assert normalize_severity("HIGH", source=sev.SOURCE_PEER_COMPARISON).level == LEVEL_HIGH


def test_unknown_severity_is_rejected_not_downgraded():
    with pytest.raises(UnknownSeverityError):
        normalize_severity("banana", source=sev.SOURCE_PEER_COMPARISON)


def test_raise_level_caps_at_very_high():
    assert raise_level(LEVEL_MODERATE, 1) == LEVEL_HIGH
    assert raise_level(LEVEL_HIGH, 4) == LEVEL_VERY_HIGH


# ── Severity resolution: base / trend / final ──────────────────────────────

def test_default_policy_reports_trend_without_changing_severity():
    cfg = resolve_trend_settings({})
    assert cfg.policy == "none"
    resolution = resolve_severity(LEVEL_HIGH, sev.SOURCE_PEER_COMPARISON,
                                  trend=_trend(), config=cfg)
    assert resolution.base.level == LEVEL_HIGH
    assert resolution.final.level == LEVEL_HIGH
    assert resolution.applied is False
    dumped = resolution.as_dict()
    assert dumped["trend_assessment"]["direction"] == "increasing"
    assert dumped["final_severity"]["level"] == LEVEL_HIGH


def test_escalation_requires_a_qualifying_trend():
    cfg = resolve_trend_settings({
        "trend_severity_policy": "escalate",
        "trend_severity_escalation": 1,
    })
    qualified = resolve_severity(LEVEL_MODERATE, sev.SOURCE_STATISTICAL_OUTLIER,
                                 trend=_trend(), config=cfg)
    assert qualified.final.level == LEVEL_HIGH
    assert qualified.applied is True
    assert qualified.base.level == LEVEL_MODERATE, "base is preserved for audit"

    # Persistence below the configured minimum -> recorded but not escalated.
    weak = resolve_severity(LEVEL_MODERATE, sev.SOURCE_STATISTICAL_OUTLIER,
                            trend=_trend(persistence_months=1), config=cfg)
    assert weak.final.level == LEVEL_MODERATE
    assert weak.applied is False


def test_direction_gate_is_re_evaluated_against_current_settings():
    trend = _trend(direction="decreasing")
    increasing_only = resolve_trend_settings({
        "trend_severity_policy": "escalate",
        "trend_direction": "increasing",
    })
    blocked = resolve_severity(LEVEL_HIGH, sev.SOURCE_STATISTICAL_OUTLIER,
                               trend=trend, config=increasing_only)
    assert blocked.final.level == LEVEL_HIGH
    assert blocked.trend.qualifies is False

    any_direction = resolve_trend_settings({"trend_severity_policy": "escalate"})
    applied = resolve_severity(LEVEL_HIGH, sev.SOURCE_STATISTICAL_OUTLIER,
                               trend=trend, config=any_direction)
    assert applied.final.level == LEVEL_VERY_HIGH


def test_override_sets_configured_target():
    cfg = resolve_trend_settings({
        "trend_severity_policy": "override",
        "trend_severity_target": "LOW",
    })
    resolution = resolve_severity(LEVEL_HIGH, sev.SOURCE_PEER_COMPARISON,
                                  trend=_trend(), config=cfg)
    assert resolution.final.level == LEVEL_LOW
    assert resolution.base.level == LEVEL_HIGH
    assert resolution.applied is True


def test_data_quality_gate_blocks_escalation():
    cfg = resolve_trend_settings({
        "trend_severity_policy": "escalate",
        "trend_min_completeness": 80.0,
    })
    blocked = resolve_severity(LEVEL_HIGH, sev.SOURCE_PEER_COMPARISON,
                               trend=_trend(), config=cfg, data_quality=55.0)
    assert blocked.final.level == LEVEL_HIGH
    assert "completeness" in blocked.reason

    unknown = resolve_severity(LEVEL_HIGH, sev.SOURCE_PEER_COMPARISON,
                               trend=_trend(), config=cfg, data_quality=None)
    assert unknown.final.level == LEVEL_HIGH

    allowed = resolve_severity(LEVEL_HIGH, sev.SOURCE_PEER_COMPARISON,
                               trend=_trend(), config=cfg, data_quality=95.0)
    assert allowed.final.level == LEVEL_VERY_HIGH


def test_base_none_is_never_escalated():
    cfg = resolve_trend_settings({"trend_severity_policy": "escalate"})
    resolution = resolve_severity(LEVEL_NONE, sev.SOURCE_STATISTICAL_OUTLIER,
                                  trend=_trend(), config=cfg)
    assert resolution.final.level == LEVEL_NONE


def test_legacy_rows_stay_readable():
    resolution = sev.legacy_resolution("VERY_HIGH")
    assert resolution.base.level == LEVEL_VERY_HIGH
    assert resolution.final.level == LEVEL_VERY_HIGH
    assert resolution.policy == "legacy"


# ── Trend assessment ───────────────────────────────────────────────────────

def test_assessment_qualifies_on_persistence_and_cumulative_change():
    values = [10, 11, 12, 13, 14, 15]
    months = [f"2026-{i:02d}" for i in range(1, 7)]
    assessment = assess_trend(values, months, config=resolve_trend_settings({}))
    assert assessment.evaluated is True
    assert assessment.direction == "increasing"
    assert assessment.persistence_months == 5
    assert assessment.cumulative_change_pct == pytest.approx(50.0)
    assert assessment.qualifies is True

    strict = resolve_trend_settings({"trend_min_cumulative_change_pct": 80})
    assert assess_trend(values, months, config=strict).qualifies is False

    persistent = resolve_trend_settings({"trend_finding_consecutive": 6})
    assert assess_trend(values, months, config=persistent).qualifies is False


def test_assessment_honours_indicator_specific_direction():
    values = [10, 11, 12, 13, 14, 15]
    cfg = resolve_trend_settings({"trend_direction": "indicator_specific"})
    worse_when_higher = assess_trend(values, config=cfg,
                                     indicator_direction="lower_is_better")
    assert worse_when_higher.direction_relevant is True
    assert worse_when_higher.qualifies is True

    better_when_higher = assess_trend(values, config=cfg,
                                      indicator_direction="higher_is_better")
    assert better_when_higher.direction_relevant is False
    assert better_when_higher.qualifies is False


def test_assessment_disabled_and_insufficient_history():
    disabled = assess_trend([1, 2, 3, 4],
                            config=resolve_trend_settings(
                                {"trend_assessment_enabled": False}))
    assert disabled.enabled is False and disabled.evaluated is False
    assert "disabled" in (disabled.skipped_reason or "")

    short = assess_trend([1, 2],
                         config=resolve_trend_settings(
                             {"trend_min_history_months": 4}))
    assert short.evaluated is False
    assert "usable period" in (short.skipped_reason or "")


# ── The real trend engine uses the saved settings ──────────────────────────

def _monthly(values, code="5"):
    return {f"2026-{i:02d}": {code: v, "2": 200}
            for i, v in enumerate(values, start=1)}


def test_trend_engine_respects_enable_window_and_min_history():
    monthly = _monthly([20, 24, 28, 32, 36, 40])
    baseline = analyze_historical_trends("H", monthly)
    assert baseline

    assert analyze_historical_trends(
        "H", monthly, config={"trend_assessment_enabled": False}) == []

    windowed = analyze_historical_trends(
        "H", monthly, config={"trend_analysis_window": 3})
    assert windowed
    assert all(len(t.months) == 3 for t in windowed)
    assert all(t.trend_assessment["points"] == 3 for t in windowed)

    assert analyze_historical_trends(
        "H", monthly, config={"trend_min_history_months": 8}) == []


def test_trend_engine_direction_gate_scopes_significance():
    falling = _monthly([60, 55, 50, 45, 40, 35])
    rows = analyze_historical_trends(
        "H", falling, config={"trend_direction": "increasing"})
    row = next(t for t in rows if "C-section" in t.rate_name)
    assert row.trend_direction == "decreasing"
    assert row.is_significant is False
    assert row.trend_assessment["qualifies"] is False

    rows = analyze_historical_trends(
        "H", falling, config={"trend_direction": "decreasing"})
    row = next(t for t in rows if "C-section" in t.rate_name)
    assert row.trend_assessment["direction_relevant"] is True


def test_trend_engine_uses_saved_band_and_zscore_config():
    monthly = _monthly([20, 24, 28, 32, 36, 40])
    loose = analyze_historical_trends(
        "H", monthly, config={"trend_slope_stable": 50.0})
    row = next(t for t in loose if "C-section" in t.rate_name)
    assert row.trend_direction == "stable"


# ── System Control: persistence, validation, effective config ──────────────

def test_control_settings_expose_effective_severity_config(client, db_session):
    payload = client.get("/config/control/settings").json()
    block = payload["severity_trend"]
    assert block["loaded"] is True
    assert payload["anomaly_zscore_threshold"] == 2.5, \
        "the saved Z-score threshold stays 2.5"
    for key in (
        "trend_assessment_enabled", "trend_analysis_window",
        "trend_min_history_months", "trend_direction",
        "trend_finding_consecutive", "trend_min_cumulative_change_pct",
        "trend_severity_policy", "trend_severity_escalation",
        "trend_severity_target", "trend_min_completeness",
    ):
        meta = block["settings"][key]
        assert "value" in meta and "default" in meta and "source" in meta
        assert meta["source"] in ("database", "default", "invalid")
    assert block["effective"]["trend_severity_policy"] == "none"
    assert block["errors"] == []
    # ONE shared Z-score range for System Control and the Settings slider (which
    # used to stop at 4 with 0.5 steps while the API allowed 1-5).
    bounds = block["zscore_bounds"]
    assert (bounds["min"], bounds["max"], bounds["default"]) == (1.0, 5.0, 2.5)
    assert bounds["step"] == 0.1


def test_control_settings_persist_and_reload(client, db_session):
    response = client.put("/config/control/settings", json={
        "trend_assessment_enabled": False,
        "trend_analysis_window": 6,
        "trend_min_history_months": 4,
        "trend_direction": "increasing",
        "trend_finding_consecutive": 4,
        "trend_min_cumulative_change_pct": 12.5,
        "trend_severity_policy": "escalate",
        "trend_severity_escalation": 2,
        "trend_severity_target": "MODERATE",
        "trend_min_completeness": 75,
    })
    assert response.status_code == 200, response.text

    # Row-level persistence: new controls in SystemSetting, the reused
    # persistence knob stays in AppConfig (no duplicate key of either).
    stored = {row.key: row.value for row in db_session.query(SystemSetting).all()}
    assert stored["trend_assessment_enabled"] == "false"
    assert stored["trend_analysis_window"] == "6"
    assert stored["trend_severity_policy"] == "escalate"
    assert "trend_finding_consecutive" not in stored
    persistence = db_session.query(AppConfig).filter_by(
        key="trend_finding_consecutive").first()
    assert persistence is not None and persistence.value == 4.0

    block = client.get("/config/control/settings").json()["severity_trend"]
    assert block["settings"]["trend_analysis_window"]["value"] == 6
    assert block["settings"]["trend_analysis_window"]["source"] == "database"
    assert block["settings"]["trend_severity_policy"]["value"] == "escalate"
    assert block["effective"]["trend_severity_target"] == "MODERATE"

    # Runtime loader sees the same saved values.
    cfg = load_analysis_config(db_session)
    assert cfg.trend.enabled is False
    assert cfg.trend.window == 6
    assert cfg.trend.min_history == 4
    assert cfg.trend.policy == "escalate"
    assert cfg.trend.escalation == 2
    assert cfg.source in ("database", "mixed")


def test_control_settings_validate_and_clamp(client, db_session):
    invalid = client.put("/config/control/settings",
                         json={"trend_severity_policy": "please-escalate"})
    assert invalid.status_code == 422
    assert any("trend_severity_policy" in e
               for e in invalid.json()["detail"]["errors"])

    bad_number = client.put("/config/control/settings",
                            json={"trend_analysis_window": "many"})
    assert bad_number.status_code == 422

    clamped = client.put("/config/control/settings",
                         json={"trend_analysis_window": 999,
                               "trend_severity_escalation": 99,
                               "trend_min_completeness": -5})
    assert clamped.status_code == 200
    block = client.get("/config/control/settings").json()["severity_trend"]
    assert block["settings"]["trend_analysis_window"]["value"] == 36
    assert block["settings"]["trend_severity_escalation"]["value"] == 4
    assert block["settings"]["trend_min_completeness"]["value"] == 0


def test_startup_seeding_is_insert_only(db_session):
    """Defaults are seeded once; an operator's saved value is never overwritten."""
    from app.engine.severity import NEW_TREND_KEYS, seed_severity_trend_settings

    created = seed_severity_trend_settings(db_session)
    assert created == len(NEW_TREND_KEYS)
    stored = {row.key: row.value for row in db_session.query(SystemSetting).all()}
    assert stored["trend_analysis_window"] == "12"

    existing = db_session.query(SystemSetting).filter_by(
        key="trend_analysis_window").first()
    existing.value = "8"
    db_session.commit()
    assert seed_severity_trend_settings(db_session) == 0
    cfg = load_analysis_config(db_session)
    assert cfg.trend.window == 8
    assert cfg.settings["trend_analysis_window"]["source"] == "database"


def test_zscore_stays_single_authoritative_setting(client, db_session):
    client.put("/config/control/settings", json={"anomaly_zscore_threshold": 3.0})
    row = db_session.query(AppConfig).filter_by(key="zscore_threshold").first()
    assert row is not None and row.value == 3.0
    assert row.category == "thresholds"
    assert db_session.query(SystemSetting).filter_by(
        key="anomaly_zscore_threshold").first() is None

    # A stale duplicate (older release) is removed on save.
    db_session.add(SystemSetting(key="anomaly_zscore_threshold", value="2.0"))
    db_session.commit()
    client.put("/config/control/settings", json={"anomaly_zscore_threshold": 2.5})
    assert db_session.query(SystemSetting).filter_by(
        key="anomaly_zscore_threshold").first() is None
    cfg = load_analysis_config(db_session)
    assert cfg.zscore_threshold == 2.5
    assert cfg.zscore_threshold_source == "database"


def test_missing_configuration_is_reported_not_hidden(client, db_session):
    cfg = load_analysis_config(db_session)
    assert cfg.trend.window == 12
    assert cfg.settings["trend_analysis_window"]["source"] == "default"

    # A read failure is surfaced by the endpoint with an explicit error.
    import app.config_utils as config_utils

    def boom(*_args, **_kwargs):
        raise RuntimeError("config table unreadable")

    original = config_utils.get_config_dict
    config_utils.get_config_dict = boom
    try:
        payload = client.get("/config/control/settings").json()
    finally:
        config_utils.get_config_dict = original
    assert payload["severity_trend"]["loaded"] is False
    assert payload["severity_trend"]["config_source"] == "unavailable"
    # The allowed range is a compile-time constant, so it survives a read error.
    assert payload["severity_trend"]["zscore_bounds"]["default"] == 2.5
    assert any("unreadable" in e for e in payload["severity_trend"]["errors"])
    assert payload["anomaly_zscore_threshold"] is None

    config_utils.get_config_dict = boom
    try:
        with pytest.raises(AnalysisConfigError):
            load_analysis_config(db_session)
    finally:
        config_utils.get_config_dict = original


# ── Quality Alerts integration: persisted base / trend / final ─────────────

@pytest.fixture
def alerts_dataset(db_session):
    """A rising hospital against five peers with a real spread.

    The target lands ~2.6σ above the peer mean at the scan month, which the
    layered band engine scores as MODERATE — so a configured escalation is
    observable (VERY_HIGH base severities cannot escalate any further). Its
    own prior months rise monotonically, so the trend qualifies.
    """
    num = Indicator(code="ST_NUM", name="ST numerator")
    den = Indicator(code="ST_DEN", name="ST denominator")
    db_session.add_all([num, den])
    db_session.flush()
    definition = IndicatorDefinition(
        code="ST_RATE", name="ST Rate", formula_type="ratio",
        numerator_codes=["ST_NUM"], denominator_codes=["ST_DEN"],
        operator="/", multiplier=100.0, result_type="percentage", unit="%",
        direction="lower_is_better", is_active=True,
    )
    db_session.add(definition)
    db_session.flush()

    for name in ("Peer D", "Peer E", "Peer F"):
        db_session.add(Hospital(name=name, region="Region A"))
    db_session.flush()
    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()[:6]
    assert len(hospitals) == 6
    months = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    rising = [10.0, 11.0, 12.0, 13.0, 14.1]
    peer_value = {1: 8.0, 2: 9.0, 3: 10.0, 4: 11.0, 5: 12.0}
    for hi, hospital in enumerate(hospitals):
        series = rising if hi == 0 else [peer_value[hi]] * len(months)
        for month, num_value in zip(months, series, strict=False):
            db_session.add(IndicatorValue(hospital_id=hospital.id,
                                          indicator_id=num.id, month=month,
                                          value=float(num_value)))
            db_session.add(IndicatorValue(hospital_id=hospital.id,
                                          indicator_id=den.id, month=month,
                                          value=100.0))
    db_session.commit()
    return {"hospitals": hospitals, "months": months, "month": months[-1]}


def test_scan_persists_base_trend_and_final_severity(client, db_session,
                                                     alerts_dataset):
    resp = client.post("/quality-alerts/scan",
                       json={"month": alerts_dataset["month"]})
    assert resp.status_code == 200, resp.text
    alerts = db_session.query(QualityAlert).all()
    assert alerts

    for alert in alerts:
        evidence = alert.evidence or {}
        assert evidence["base_severity"]["level"] in sev.LEVELS
        assert evidence["final_severity"]["level"] == alert.severity
        assert evidence["severity_policy"]["policy"] == "none"
        assert evidence["base_severity"]["source"] in sev.SOURCES

    assert any((a.evidence or {}).get("trend_assessment", {}).get("evaluated")
               for a in alerts), "the history series must yield a trend assessment"


def test_scan_applies_configured_escalation_and_keeps_base(client, db_session,
                                                           alerts_dataset):
    client.post("/quality-alerts/scan", json={"month": alerts_dataset["month"]})
    client.put("/config/control/settings", json={
        "trend_severity_policy": "escalate",
        "trend_severity_escalation": 1,
        "trend_min_completeness": 0,
    })
    db_session.query(QualityAlert).delete()
    db_session.commit()
    resp = client.post("/quality-alerts/scan",
                       json={"month": alerts_dataset["month"]})
    assert resp.status_code == 200, resp.text

    alerts = db_session.query(QualityAlert).all()
    assert alerts
    escalated = 0
    for alert in alerts:
        evidence = alert.evidence or {}
        base = evidence["base_severity"]["level"]
        trend = evidence.get("trend_assessment") or {}
        expected = (raise_level(base, 1)
                    if trend.get("qualifies") and sev.LEVEL_RANK[base] >= sev.LEVEL_RANK[LEVEL_LOW]
                    else base)
        assert alert.severity == expected
        assert evidence["final_severity"]["level"] == expected
        assert evidence["base_severity"]["level"] == base
        if expected != base:
            escalated += 1
    assert escalated >= 1, "a qualifying trend must escalate its base severity"


def test_severity_preview_reports_impact_without_writing(client, db_session,
                                                          alerts_dataset):
    client.post("/quality-alerts/scan", json={"month": alerts_dataset["month"]})
    before = {(a.id, a.severity) for a in db_session.query(QualityAlert).all()}

    resp = client.post("/config/control/severity-preview",
                       json={"trend_severity_policy": "escalate"})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["preview"] is True
    assert payload["rows_examined"] == len(before)
    assert payload["rows_changing"] >= 1
    assert payload["transitions"]
    assert "unchanged" in payload["note"]

    after = {(a.id, a.severity) for a in db_session.query(QualityAlert).all()}
    assert after == before, "preview must not rewrite stored results"


def test_alert_api_exposes_three_severity_outputs(client, db_session,
                                                  alerts_dataset):
    client.post("/quality-alerts/scan", json={"month": alerts_dataset["month"]})
    alert = db_session.query(QualityAlert).first()
    listed = client.get("/quality-alerts/issues",
                        params={"month": alerts_dataset["month"]}).json()
    perspective = next(p for issue in listed["items"]
                       for p in issue["perspectives"] if p["id"] == alert.id)
    assert perspective["base_severity"]["level"] in sev.LEVELS
    assert perspective["final_severity"]["level"] == alert.severity
    assert "trend_assessment" in perspective
    assert perspective["severity_provenance"]["legacy"] is False

    detail = client.get(f"/quality-alerts/{alert.id}").json()
    assert detail["alert"]["base_severity"]["level"] in sev.LEVELS
    assert detail["evidence"]["final_severity"]["level"] == alert.severity


def test_alerts_learn_which_policy_computed_them(client, db_session,
                                                alerts_dataset):
    client.post("/quality-alerts/scan", json={"month": alerts_dataset["month"]})
    alerts = db_session.query(QualityAlert).all()
    assert alerts
    for alert in alerts:
        fingerprint = alert.evidence["severity_policy"]["fingerprint"]
        assert len(fingerprint) == 16
    # Every row of one scan shares the same configuration fingerprint.
    assert len({a.evidence["severity_policy"]["fingerprint"] for a in alerts}) == 1

    issues = client.get("/quality-alerts/issues",
                        params={"month": alerts_dataset["month"]}).json()["items"]
    assert issues
    assert all(issue["policy_state"] == "current" for issue in issues)
    assert all(issue["policy_stale"] is False for issue in issues)


def test_alerts_under_older_policy_are_marked_stale_without_rewrite(
        client, db_session, alerts_dataset):
    client.post("/quality-alerts/scan", json={"month": alerts_dataset["month"]})
    month = alerts_dataset["month"]

    def snapshot():
        return {
            (a.id, a.severity,
             (a.evidence or {}).get("severity_policy", {}).get("fingerprint"),
             (a.evidence or {}).get("severity_policy", {}).get("policy"))
            for a in db_session.query(QualityAlert).all()
        }

    before = snapshot()
    issues = client.get("/quality-alerts/issues",
                        params={"month": month}).json()["items"]
    assert all(issue["policy_state"] == "current" for issue in issues)

    # A setting that can change a resolution, saved without re-running the scan.
    resp = client.put("/config/control/settings",
                      json={"trend_analysis_window": 6})
    assert resp.status_code == 200, resp.text

    issues = client.get("/quality-alerts/issues",
                        params={"month": month}).json()["items"]
    assert issues
    assert all(issue["policy_state"] == "stale" for issue in issues)
    assert all(issue["policy_stale"] is True for issue in issues)
    assert all(issue["policy_stale_count"] >= 1 for issue in issues)

    # Marked only: stored severities, evidence and fingerprints are untouched.
    assert snapshot() == before

    # The detail view reports the same state for the opened alert.
    alert_id, _severity, stored_fingerprint, _policy = sorted(before)[0]
    detail = client.get(f"/quality-alerts/{alert_id}").json()
    assert detail["alert"]["policy_state"] == "stale"
    assert detail["evidence"]["severity_policy"]["fingerprint"] == stored_fingerprint


def test_unreadable_config_never_accuses_alerts_of_being_stale(
        client, db_session, alerts_dataset, monkeypatch):
    client.post("/quality-alerts/scan", json={"month": alerts_dataset["month"]})
    month = alerts_dataset["month"]

    import app.config_utils as config_utils

    def boom(*_args, **_kwargs):
        raise RuntimeError("config table unreadable")

    monkeypatch.setattr(config_utils, "get_config_dict", boom)
    issues = client.get("/quality-alerts/issues",
                        params={"month": month}).json()["items"]
    assert issues
    assert all(issue["policy_state"] == "unknown" for issue in issues)
    assert all(issue["policy_stale"] is False for issue in issues)


def test_rescan_after_saving_escalation_changes_severity_and_clears_stale(
        client, db_session, alerts_dataset):
    """Operator loop end to end: save → marked stale → rescan → new level.

    Drives the same endpoints the System Control and Quality Alerts screens
    call, in order. The badge is derived only from what the list reports
    (``policy_stale`` / ``policy_state``), so clearing it here means it clears
    in the UI: no rewrite happens while the marker shows, and one deliberate
    rescan both applies the saved policy and removes the marker.
    """
    month = alerts_dataset["month"]
    first = client.post("/quality-alerts/scan", json={"month": month})
    assert first.status_code == 200, first.text

    def listed():
        items = client.get("/quality-alerts/issues",
                           params={"month": month}).json()["items"]
        perspectives = {p["id"]: p for issue in items
                        for p in issue["perspectives"]}
        return items, perspectives

    def persisted():
        return {a.id: (a.severity, (a.evidence or {})["base_severity"]["level"])
                for a in db_session.query(QualityAlert).all()}

    issues, before = listed()
    stored_before = persisted()
    assert issues and before
    assert all(issue["policy_state"] == "current" for issue in issues)
    assert all(issue["policy_stale"] is False for issue in issues)
    assert all(p["policy_state"] == "current" for p in before.values())

    saved = client.put("/config/control/settings", json={
        "trend_severity_policy": "escalate",
        "trend_severity_escalation": 1,
        "trend_min_completeness": 0,
    })
    assert saved.status_code == 200, saved.text

    # Saved but not yet applied: every row is marked, no value is moved.
    issues, marked = listed()
    assert all(issue["policy_state"] == "stale" for issue in issues)
    assert all(issue["policy_stale"] is True for issue in issues)
    assert all(issue["policy_stale_count"] >= 1 for issue in issues)
    assert all(p["policy_state"] == "stale" for p in marked.values())
    assert persisted() == stored_before, "marking must not rewrite stored results"

    rescanned = client.post("/quality-alerts/scan", json={"month": month})
    assert rescanned.status_code == 200, rescanned.text

    issues, after = listed()
    stored_after = persisted()
    assert after.keys() == before.keys(), \
        "the rescan must re-resolve the existing rows, not replace them"
    assert stored_after.keys() == stored_before.keys()

    # Badge cleared: the unchanged stored results now match the live policy.
    assert all(issue["policy_state"] == "current" for issue in issues)
    assert all(issue["policy_stale"] is False for issue in issues)
    assert all(issue["policy_stale_count"] == 0 for issue in issues)
    assert all(p["policy_state"] == "current" for p in after.values())

    changed = [alert_id for alert_id in before
               if before[alert_id]["severity"] != after[alert_id]["severity"]]
    assert changed, "a saved escalation must change at least one severity"
    for alert_id in changed:
        base = after[alert_id]["base_severity"]["level"]
        expected = (raise_level(base, 1)
                    if sev.LEVEL_RANK[base] >= sev.LEVEL_RANK[LEVEL_LOW]
                    else base)
        assert after[alert_id]["severity"] == expected
        assert after[alert_id]["final_severity"]["level"] == expected
        assert stored_after[alert_id][0] == expected, \
            "the list must read the severity the scan persisted"
        # The policy moves the final level only: base stays a fact about data.
        assert after[alert_id]["base_severity"]["level"] == \
            before[alert_id]["base_severity"]["level"]

    for alert_id in before:
        if alert_id not in changed:
            assert after[alert_id]["severity"] == before[alert_id]["severity"]

    # The detail header (its own badge) agrees with the list.
    detail = client.get(f"/quality-alerts/{changed[0]}").json()
    assert detail["alert"]["policy_state"] == "current"
    assert detail["alert"]["severity"] == after[changed[0]]["severity"]


# ── Recompute stale months (preview → confirm → rescan) ───────────────────

def _active_rows(db_session):
    return (db_session.query(QualityAlert)
            .filter(QualityAlert.active.is_(True)).all())


def _policy_snapshot(db_session):
    return {a.id: (a.severity, a.updated_at,
                   (a.evidence or {}).get("severity_policy", {}).get("fingerprint"))
            for a in _active_rows(db_session)}


@pytest.fixture
def multi_month_alerts(db_session):
    """A target hospital far above five peers in two consecutive months.

    Two affected periods are needed to prove the recompute action scans only
    the months it reports as stale. The target's value is clear of the peer
    band in both months, so both get alerts regardless of trend capture.
    """
    num = Indicator(code="MM_NUM", name="MM numerator")
    den = Indicator(code="MM_DEN", name="MM denominator")
    db_session.add_all([num, den])
    db_session.flush()
    db_session.add(IndicatorDefinition(
        code="MM_RATE", name="MM Rate", formula_type="ratio",
        numerator_codes=["MM_NUM"], denominator_codes=["MM_DEN"],
        operator="/", multiplier=100.0, result_type="percentage", unit="%",
        direction="lower_is_better", is_active=True,
    ))
    db_session.flush()
    for name in ("Peer G", "Peer H", "Peer I"):
        db_session.add(Hospital(name=name, region="Region A"))
    db_session.flush()
    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()[:6]
    assert len(hospitals) == 6
    months = ["2026-08", "2026-09"]
    peer_value = {1: 10.0, 2: 11.0, 3: 12.0, 4: 13.0, 5: 14.0}
    for hi, hospital in enumerate(hospitals):
        series = [45.0, 47.0] if hi == 0 else [peer_value[hi]] * len(months)
        for month, value in zip(months, series, strict=False):
            db_session.add(IndicatorValue(hospital_id=hospital.id,
                                          indicator_id=num.id, month=month,
                                          value=float(value)))
            db_session.add(IndicatorValue(hospital_id=hospital.id,
                                          indicator_id=den.id, month=month,
                                          value=100.0))
    db_session.commit()
    return {"months": months}


@pytest.fixture
def two_indicator_alerts(db_session):
    """Two independent indicators, both clear peer outliers in one month.

    Lets a test prove the recompute touches only the rows that are actually
    stale: one indicator's rows are marked current, the other's stay stale.
    """
    num = Indicator(code="TI_NUM", name="TI numerator")
    den = Indicator(code="TI_DEN", name="TI denominator")
    db_session.add_all([num, den])
    db_session.flush()
    for code in ("TI_A", "TI_B"):
        db_session.add(IndicatorDefinition(
            code=code, name=f"{code} rate", formula_type="ratio",
            numerator_codes=["TI_NUM"], denominator_codes=["TI_DEN"],
            operator="/", multiplier=100.0, result_type="percentage",
            unit="%", direction="lower_is_better", is_active=True,
        ))
    db_session.flush()
    for name in ("Peer J", "Peer K", "Peer L"):
        db_session.add(Hospital(name=name, region="Region A"))
    db_session.flush()
    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()[:6]
    assert len(hospitals) == 6
    month = "2026-09"
    peer_value = {1: 10.0, 2: 11.0, 3: 12.0, 4: 13.0, 5: 14.0}
    for hi, hospital in enumerate(hospitals):
        value = 45.0 if hi == 0 else peer_value[hi]
        db_session.add(IndicatorValue(hospital_id=hospital.id,
                                      indicator_id=num.id, month=month,
                                      value=value))
        db_session.add(IndicatorValue(hospital_id=hospital.id,
                                      indicator_id=den.id, month=month,
                                      value=100.0))
    db_session.commit()
    return {"month": month}


def _save_escalation(client):
    saved = client.put("/config/control/settings", json={
        "trend_severity_policy": "escalate",
        "trend_severity_escalation": 1,
        "trend_min_completeness": 0,
    })
    assert saved.status_code == 200, saved.text


def test_rescan_stale_previews_affected_months_without_writing(
        client, db_session, multi_month_alerts):
    first = client.post("/quality-alerts/scan", json={})
    assert first.status_code == 200, first.text
    active = _active_rows(db_session)
    months = sorted({a.month for a in active})
    assert months == multi_month_alerts["months"], \
        "the fixture must produce alerts in both periods"
    before = _policy_snapshot(db_session)

    _save_escalation(client)
    assert _policy_snapshot(db_session) == before, \
        "saving the policy must not touch stored results"

    resp = client.post("/quality-alerts/rescan-stale", json={})
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["confirm_required"] is True
    assert [entry["month"] for entry in payload["months"]] == months
    assert payload["total_alerts"] == len(active)
    assert payload["total_issues"] >= len(months)
    assert payload["total_hospitals"] >= 1
    assert all(entry["alerts"] >= 1 and entry["issues"] >= 1
               for entry in payload["months"])
    # A preview is read-only — no stored result and no audit entry.
    assert _policy_snapshot(db_session) == before
    assert db_session.query(QualityAlertAudit).count() == 0


def test_rescan_stale_scans_only_the_months_asked_for(client, db_session,
                                                      multi_month_alerts):
    assert client.post("/quality-alerts/scan", json={}).status_code == 200
    up_to_date_month, stale_month = multi_month_alerts["months"]
    base_before = {a.id: (a.evidence or {})["base_severity"]["level"]
                   for a in _active_rows(db_session)}

    _save_escalation(client)
    # One period is brought up to date on its own; it must not be rescanned
    # again by the stale action.
    assert client.post("/quality-alerts/scan",
                       json={"month": up_to_date_month}).status_code == 200
    untouched = {a.id: a.updated_at for a in _active_rows(db_session)
                 if a.month == up_to_date_month}
    stale_before = {a.id: a.updated_at for a in _active_rows(db_session)
                    if a.month == stale_month}

    preview = client.post("/quality-alerts/rescan-stale", json={})
    assert preview.status_code == 200, preview.text
    assert [entry["month"] for entry in preview.json()["months"]] == [stale_month]

    done = client.post("/quality-alerts/rescan-stale", json={
        "confirm": True,
        "months": [entry["month"] for entry in preview.json()["months"]],
    })
    assert done.status_code == 200, done.text
    result = done.json()
    assert result["confirm_required"] is False
    assert [entry["month"] for entry in result["rescanned"]] == [stale_month]

    # The already-current period was NOT touched...
    assert {a.id: a.updated_at for a in _active_rows(db_session)
            if a.month == up_to_date_month} == untouched, \
        "a month that already matched the policy must not be scanned"
    # ...while the stale one was re-resolved.
    assert {a.id: a.updated_at for a in _active_rows(db_session)
            if a.month == stale_month} != stale_before
    # Every stored result now matches the live policy, so the badges clear.
    issues = client.get("/quality-alerts/issues").json()["items"]
    assert issues
    assert all(issue["policy_state"] == "current" for issue in issues)

    # The recompute is recorded for audit: who ran it and which months it
    # touched, not just a transient server log line.
    audit = db_session.query(QualityAlertAudit).one()
    assert audit.action == "rescan_stale"
    assert audit.actor == "testadmin"
    assert audit.months == [stale_month]
    assert audit.details["hospitals"] == 1
    assert audit.details["alerts_rewritten"] == preview.json()["total_alerts"]
    assert [scope["month"] for scope in audit.details["scopes"]] == [stale_month]
    assert result["audit"]["id"] == audit.id
    assert result["audit"]["months"] == [stale_month]
    # Base severity is a fact about the data; a recompute never rewrites it.
    for alert in _active_rows(db_session):
        assert (alert.evidence or {})["base_severity"]["level"] == \
            base_before[alert.id]


def test_rescan_stale_rewrites_only_the_stale_rows(client, db_session,
                                                   two_indicator_alerts):
    """Row-level targeting: a sibling indicator of the SAME hospital/month that
    already matches the policy is neither rewritten nor deactivated."""
    month = two_indicator_alerts["month"]
    assert client.post("/quality-alerts/scan", json={}).status_code == 200
    _save_escalation(client)

    rows = _active_rows(db_session)
    codes = {alert.indicator_code for alert in rows}
    assert {"TI_A", "TI_B"} <= codes

    # Pretend every OTHER indicator (including the raw numerator, which is an
    # alertable element in its own right) was already recomputed after the
    # policy change; only TI_B is still stale. The policy was saved by the API
    # in its own session, so end this session's read transaction first.
    db_session.commit()
    current = sev.policy_fingerprint(load_analysis_config(db_session))
    a_ids, b_ids = set(), set()
    for alert in rows:
        if alert.indicator_code == "TI_B":
            b_ids.add(alert.id)
            continue
        evidence = dict(alert.evidence or {})
        stored = dict(evidence.get("severity_policy") or {})
        stored["fingerprint"] = current
        evidence["severity_policy"] = stored
        alert.evidence = evidence  # reassign so the JSON column sees the change
        a_ids.add(alert.id)
    db_session.commit()

    def _rows(ids):
        return (db_session.query(QualityAlert)
                .filter(QualityAlert.id.in_(ids)).all())

    untouched = {a.id: (a.updated_at, a.severity, a.active) for a in _rows(a_ids)}
    b_before = {a.id: a.updated_at for a in _rows(b_ids)}

    preview = client.post("/quality-alerts/rescan-stale", json={}).json()
    assert preview["total_issues"] == 1, "only TI_B is still stale"
    assert [entry["month"] for entry in preview["months"]] == [month]

    done = client.post("/quality-alerts/rescan-stale", json={"confirm": True})
    assert done.status_code == 200, done.text
    result = done.json()
    assert len(result["rescanned"]) == 1
    assert result["rescanned"][0]["indicators"] == 1, \
        "one indicator scope, not the whole hospital/month"

    # TI_A: not rewritten, not deactivated by another indicator's rescan.
    for alert in _rows(a_ids):
        db_session.refresh(alert)
        assert (alert.updated_at, alert.severity, alert.active) == \
            untouched[alert.id]

    # TI_B: re-resolved under the live policy.
    for alert in _rows(b_ids):
        db_session.refresh(alert)
        assert alert.active is True
        assert alert.updated_at > b_before[alert.id]
        assert (alert.evidence or {})["severity_policy"]["fingerprint"] == current

    issues = client.get("/quality-alerts/issues").json()["items"]
    assert all(issue["policy_state"] == "current" for issue in issues)


def test_hospital_scoped_scan_still_compares_against_peer_hospitals(
        client, db_session, alerts_dataset):
    """Scoping a scan to one hospital must not starve the peer comparison.

    The comparison universe is every hospital; only persistence is scoped.
    Otherwise a targeted recompute would "lose" alerts it should have kept.
    """
    month = alerts_dataset["month"]
    client.post("/quality-alerts/scan", json={"month": month})
    hospital_id = _active_rows(db_session)[0].hospital_id
    before = {a.id for a in _active_rows(db_session)
              if a.hospital_id == hospital_id}
    assert before

    resp = client.post("/quality-alerts/scan",
                       json={"month": month, "hospital_id": hospital_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["deactivated"] == 0
    after = {a.id for a in _active_rows(db_session)
             if a.hospital_id == hospital_id}
    assert after == before, \
        "a hospital-scoped scan must keep its existing outliers"


def test_rescan_stale_drops_months_that_are_no_longer_stale(
        client, db_session, alerts_dataset):
    client.post("/quality-alerts/scan", json={})
    month = sorted({a.month for a in _active_rows(db_session)})[0]
    _save_escalation(client)
    assert client.post("/quality-alerts/scan",
                       json={"month": month}).status_code == 200
    before = _policy_snapshot(db_session)

    # Confirming a period that the server no longer considers stale is a no-op,
    # never a blind rescan.
    payload = client.post("/quality-alerts/rescan-stale", json={
        "confirm": True, "months": [month]}).json()
    assert payload["months"] == []
    assert payload["rescanned"] == []
    assert payload["audit"] is None
    assert db_session.query(QualityAlertAudit).count() == 0, \
        "nothing was recomputed, so nothing is recorded as recomputed"
    assert _policy_snapshot(db_session) == before


def test_rescan_stale_refuses_when_policy_is_unreadable(
        client, db_session, alerts_dataset, monkeypatch):
    client.post("/quality-alerts/scan", json={})
    before = _policy_snapshot(db_session)

    import app.config_utils as config_utils

    def boom(*_args, **_kwargs):
        raise RuntimeError("config table unreadable")

    monkeypatch.setattr(config_utils, "get_config_dict", boom)
    resp = client.post("/quality-alerts/rescan-stale", json={"confirm": True})
    assert resp.status_code == 409
    assert "unreadable" in resp.json()["detail"]
    assert _policy_snapshot(db_session) == before


# ── Dashboard: policy-drift count ─────────────────────────────────────────

def test_dashboard_reports_stale_policy_alerts(client, db_session, alerts_dataset):
    month = alerts_dataset["month"]
    assert client.post("/quality-alerts/scan",
                       json={"month": month}).status_code == 200
    active = _active_rows(db_session)
    assert active

    assert client.get("/dashboard/overview").json()["stale_policy_alerts"] == 0

    _save_escalation(client)
    overview = client.get("/dashboard/overview").json()
    assert overview["stale_policy_alerts"] == len(active)

    # The count obeys the same scope as the other summary cards.
    hospital_id = active[0].hospital_id
    scoped = client.get("/dashboard/overview",
                        params={"hospital_id": hospital_id}).json()
    assert scoped["stale_policy_alerts"] == sum(
        1 for alert in active if alert.hospital_id == hospital_id)

    assert client.get("/dashboard/overview", params={
        "month_from": "2020-01", "month_to": "2020-02"
    }).json()["stale_policy_alerts"] == 0
    assert client.get("/dashboard/overview",
                      params={"year": month[:4]}).json()["stale_policy_alerts"] == len(active)
    assert client.get("/dashboard/overview",
                      params={"year": "2019"}).json()["stale_policy_alerts"] == 0

    # Recomputing clears the drift: the card tracks the policy, not history.
    assert client.post("/quality-alerts/rescan-stale",
                       json={"confirm": True}).status_code == 200
    assert client.get("/dashboard/overview").json()["stale_policy_alerts"] == 0


def test_dashboard_drift_count_excludes_rows_without_a_policy(
        client, db_session, alerts_dataset):
    client.post("/quality-alerts/scan", json={"month": alerts_dataset["month"]})
    _save_escalation(client)
    before = client.get("/dashboard/overview").json()["stale_policy_alerts"]
    assert before > 0

    # A row written before fingerprints existed cannot be attributed to any
    # policy: it is unknown, not stale, and must not inflate the drift count.
    db_session.add(QualityAlert(
        hospital_id=alerts_dataset["hospitals"][0].id,
        month=alerts_dataset["month"], perspective="history",
        indicator_code="LEGACY_RATE", indicator_name="Legacy Rate",
        severity="HIGH", method="zscore", status="New", active=True,
        evidence={"base_severity": {"level": "HIGH"}},
    ))
    db_session.commit()
    assert client.get("/dashboard/overview").json()["stale_policy_alerts"] == before


def test_dashboard_drift_is_null_when_policy_is_unreadable(
        client, db_session, alerts_dataset, monkeypatch):
    client.post("/quality-alerts/scan", json={"month": alerts_dataset["month"]})

    import app.config_utils as config_utils

    def boom(*_args, **_kwargs):
        raise RuntimeError("config table unreadable")

    monkeypatch.setattr(config_utils, "get_config_dict", boom)
    overview = client.get("/dashboard/overview").json()
    # Never 0: with an unreadable policy the count is unknown, not "no drift".
    assert overview["stale_policy_alerts"] is None


# ── Regression guards ──────────────────────────────────────────────────────

def test_existing_quality_alert_severity_vocabulary_is_unchanged():
    from app.models import QUALITY_ALERT_SEVERITIES
    assert QUALITY_ALERT_SEVERITIES == ("LOW", "MODERATE", "HIGH", "VERY_HIGH")


def test_outlier_engine_bands_are_unchanged():
    from app.engine.anomaly import layered
    assert layered.LEVELS == ("NONE", "LOW", "MODERATE", "HIGH", "VERY_HIGH")
    assert layered.OUTLIER_LEVEL_MIN == "MODERATE"
    assert layered.PEER_Z_THRESHOLD_DEFAULT == 2.5
