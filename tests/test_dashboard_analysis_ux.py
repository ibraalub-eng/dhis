"""Tests: dashboard answers "compared to what?" and "what should I look at?".

Modern DHIS-style contracts:
- /dashboard/kpi carries a period-over-period delta per KPI (previous window
  of the same length, ghost rows excluded) + a data_epoch stamp.
- /dashboard/attention lists worst movers, hospitals with critical/high rule
  failures, and hospitals with low completeness — each row carrying the exact
  params its Why popup needs (kind/hospital_id/month, rule_code for rule rows).
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.models import (
    ConfidenceScore,
    Hospital,
    Indicator,
    IndicatorValue,
    QualityScore,
    ValidationResult,
)


@pytest.fixture()
def ux_data(db_session):
    """Two hospitals across three analyzed months with a clear story:
    - Good Hospital: 70 → 75 → 85 (improving)
    - Bad Hospital:  80 → 60 → 50 (declining, plus critical failures + low
      completeness in the latest month)
    """
    h1 = db_session.query(Hospital).first()
    h2 = db_session.query(Hospital).offset(1).first()
    ind = db_session.query(Indicator).first()

    for hid in (h1.id, h2.id):
        for m in ("2026-01", "2026-02", "2026-03"):
            db_session.add(IndicatorValue(hospital_id=hid, month=m, indicator_id=ind.id, value=10))

    for hid, scores in ((h1.id, (70.0, 75.0, 85.0)), (h2.id, (80.0, 60.0, 50.0))):
        for m, sc in zip(("2026-01", "2026-02", "2026-03"), scores):
            db_session.add(QualityScore(
                hospital_id=hid, month=m, score=sc,
                rule_compliance=sc, consistency=sc,
                completeness=90.0 if hid == h1.id else 40.0,
            ))
    db_session.add(ConfidenceScore(hospital_id=h1.id, month="2026-03", overall_confidence=70.0, level="HIGH"))

    # Critical + HIGH failures for Bad Hospital in the latest month
    db_session.add(ValidationResult(
        hospital_id=h2.id, month="2026-03", rule_code="R010",
        rule_description="Missing deliveries", status="FAIL", severity="CRITICAL", rule_type="LOGIC"))
    db_session.add(ValidationResult(
        hospital_id=h2.id, month="2026-03", rule_code="R020",
        rule_description="Negative value", status="FAIL", severity="HIGH", rule_type="LOGIC"))
    db_session.commit()
    from app.cache import cache
    cache.invalidate("analysis:months")
    return {"good": h1.id, "bad": h2.id}


def test_kpi_carries_period_over_period_delta(app, db_session, ux_data):
    client = TestClient(app)
    # Query one hospital: an unfiltered call averages the whole network.
    r = client.get(f"/dashboard/kpi?month_from=2026-02&month_to=2026-03&hospital_id={ux_data['good']}").json()

    assert r["data_epoch"], "kpi payload must carry a data_epoch stamp"
    assert r["prev_period"] == {"from": "2025-12", "to": "2026-01"}

    by_id = {k["id"]: k for k in r["kpis"]}
    qs = by_id["quality_score"]
    # window avg = (75+85)/2 = 80; prev window (2025-12..2026-01) = 70 → +10
    assert qs["value"] == 80.0
    assert qs["prev_value"] == 70.0
    assert qs["delta"] == 10.0


def test_kpi_single_month_compares_against_previous_month(app, db_session, ux_data):
    client = TestClient(app)
    r = client.get(f"/dashboard/kpi?month=2026-03&hospital_id={ux_data['good']}").json()
    assert r["prev_period"] is not None
    by_id = {k["id"]: k for k in r["kpis"]}
    qs = by_id["quality_score"]
    # 2026-03 = 85 vs 2026-02 = 75 → +10
    assert qs["value"] == 85.0 and qs["prev_value"] == 75.0 and qs["delta"] == 10.0


def test_kpi_prev_window_with_no_analyzed_data_yields_no_comparison(app, db_session, ux_data):
    """A ghost month (QualityScore row, never analyzed) must not poison the
    delta — and when the previous window has no analyzed data at all, the
    payload carries no comparison rather than a fake 0.0 baseline."""
    db_session.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == ux_data["good"],
        IndicatorValue.month == "2026-02",
    ).delete(synchronize_session=False)
    db_session.commit()
    client = TestClient(app)
    r = client.get(f"/dashboard/kpi?month=2026-03&hospital_id={ux_data['good']}").json()
    qs = {k["id"]: k for k in r["kpis"]}["quality_score"]
    assert qs["value"] == 85.0
    # ghost 75.0 in 2026-02 ignored → no prev window → no comparison
    assert "prev_value" not in qs and "delta" not in qs


def test_kpi_carries_network_benchmark_when_hospital_selected(app, db_session, ux_data):
    """Peer benchmark (modern DHIS-style): with a hospital selected, each KPI
    also carries the network average for the SAME window, excluding the
    hospital itself. Unfiltered calls must NOT carry it (there is no peer)."""
    client = TestClient(app)
    r = client.get(f"/dashboard/kpi?month_from=2026-02&month_to=2026-03&hospital_id={ux_data['good']}").json()
    qs = {k["id"]: k for k in r["kpis"]}["quality_score"]
    # good = 80.0; network (bad only, same window) = (60+50)/2 = 55.0
    assert qs["value"] == 80.0
    assert qs["network_value"] == 55.0

    unfiltered = client.get("/dashboard/kpi?month_from=2026-02&month_to=2026-03").json()
    qs2 = {k["id"]: k for k in unfiltered["kpis"]}["quality_score"]
    assert qs2.get("network_value") is None  # no peer when showing the network


def test_kpi_benchmark_excludes_hospital_and_ghost_months(app, db_session, ux_data):
    """The network average must exclude the selected hospital's rows and
    ghost (never-analyzed) months, exactly like the main value."""
    db_session.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == ux_data["bad"],
        IndicatorValue.month == "2026-02",
    ).delete(synchronize_session=False)
    db_session.commit()
    client = TestClient(app)
    r = client.get(f"/dashboard/kpi?month_from=2026-02&month_to=2026-03&hospital_id={ux_data['good']}").json()
    qs = {k["id"]: k for k in r["kpis"]}["quality_score"]
    # bad's 2026-02 is now a ghost month → network window avg = 50.0 only
    assert qs["network_value"] == 50.0


def test_kpi_cards_render_benchmark_line(app, db_session, ux_data):
    """UI contract: with a hospital selected, the KPI cards show a
    "you vs the other hospitals" line driven by k.network_value from
    /dashboard/kpi. The user-facing label is descriptive (never the bare
    word "network") in both languages — see docs/ARABIC-TERMINOLOGY.md."""
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / "rules-manager.js").read_text(encoding="utf-8")
    cards = js[js.index("function renderKpiCards"):js.index("function renderKpiCards") + 4800]
    assert "network_value" in cards
    assert "vs other hospitals" in cards
    assert "Other hospitals average" in cards


def test_attention_why_button_passes_rule_code_in_correct_slot(app, db_session, ux_data):
    """Why buttons use the object form showWhyPopup({kind, hospitalId, month,
    component?, ruleCode?}) — the earlier positional call put the rule code
    in the rateName slot (5th arg) and kind=rule opened with no rule_code
    (404). Object keys can never swap by position."""
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / "rules-manager.js").read_text(encoding="utf-8")
    strip = js[js.index("function loadAttentionStrip"):js.index("window.applyDashboardFilter")]
    btn = strip[strip.index("window.showWhyPopup"):strip.index("window.showWhyPopup") + 700]
    assert "kind:" in btn and "hospitalId:" in btn and "month:" in btn
    assert "ruleCode:" in btn, "rule code must be passed as a named key"
    assert "r.why.component" in btn, "component anomalies must pass their component"


def test_attention_lists_declining_movers_first(app, db_session, ux_data):
    client = TestClient(app)
    r = client.get("/dashboard/attention?month_from=2026-01&month_to=2026-03").json()
    assert r["month"] == "2026-03"

    movers = {m["hospital_id"]: m for m in r["movers"]}
    assert movers[ux_data["bad"]]["delta"] == -10.0  # 60 → 50
    assert movers[ux_data["bad"]]["why"]["kind"] == "quality_score"
    # improving hospital is NOT in the attention list
    assert ux_data["good"] not in movers


def test_anomaly_flags_abnormal_drop_with_zscore(app, db_session):
    """A sudden drop far below the hospital's own history is a z-score
    outlier (≥2σ) and lands in the anomalies list — even though the
    month-over-month mover logic would also catch it."""
    h = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).first()
    scores = {"2026-01": 90.0, "2026-02": 91.0, "2026-03": 90.0, "2026-04": 89.0, "2026-05": 30.0}
    for m, sc in scores.items():
        db_session.add(IndicatorValue(hospital_id=h.id, month=m, indicator_id=ind.id, value=10))
        db_session.add(QualityScore(hospital_id=h.id, month=m, score=sc, rule_compliance=sc,
                                    consistency=sc, completeness=90.0))
    db_session.commit()
    from app.cache import cache
    cache.invalidate("analysis:months")
    client = TestClient(app)
    r = client.get("/dashboard/attention").json()
    a = next(x for x in r["anomalies"] if x["hospital_id"] == h.id)
    assert a["kind"] == "drop"
    assert a["zscore"] <= -2.0
    assert a["value"] == 30.0
    assert a["why"]["kind"] == "quality_score"


def test_anomaly_flags_slow_drift_hidden_from_movers(app, db_session):
    """Three consecutive small drops never trip the movers list — the drift
    detector is what catches this quiet decline."""
    h = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).first()
    scores = {"2026-01": 90.0, "2026-02": 89.3, "2026-03": 88.6, "2026-04": 87.9}
    for m, sc in scores.items():
        db_session.add(IndicatorValue(hospital_id=h.id, month=m, indicator_id=ind.id, value=10))
        db_session.add(QualityScore(hospital_id=h.id, month=m, score=sc, rule_compliance=sc,
                                    consistency=sc, completeness=90.0))
    db_session.commit()
    from app.cache import cache
    cache.invalidate("analysis:months")
    client = TestClient(app)
    r = client.get("/dashboard/attention").json()
    a = next(x for x in r["anomalies" if "anomalies" in r else []] + r["movers"] if x["hospital_id"] == h.id)
    assert a["kind"] == "drift"
    assert a["start"] == 90.0 and a["value"] == 87.9
    # (movers may also list it — movers is simply the top-N decliners; the
    # drift detector is what catches quiet declines BEYOND that list.)


def test_anomaly_ignores_stable_hospital(app, db_session):
    """A hospital hovering within noise must NOT be flagged — the anomaly
    list must stay trustworthy, not cry wolf on every wiggle."""
    h = db_session.query(Hospital).first()
    ind = db_session.query(Indicator).first()
    scores = {"2026-01": 90.0, "2026-02": 89.0, "2026-03": 91.0, "2026-04": 90.0}
    for m, sc in scores.items():
        db_session.add(QualityScore(hospital_id=h.id, month=m, score=sc, rule_compliance=sc,
                                    consistency=sc, completeness=90.0))
    db_session.commit()
    from app.cache import cache
    cache.invalidate("analysis:months")
    client = TestClient(app)
    r = client.get("/dashboard/attention").json()
    assert all(x["hospital_id"] != h.id for x in r["anomalies"])


def test_anomaly_thresholds_configurable_in_settings(app, db_session):
    """Z-score threshold and drift length are admin-configurable via
    /config/control/settings (clamped to sane ranges), and changing them
    changes what the attention strip flags."""
    from app.cache import cache
    client = TestClient(app)
    ind = db_session.query(Indicator).first()
    h = db_session.query(Hospital).first()
    # Mild sudden drop: baseline [90,85,95,90] → sd 3.54, latest 82 → z ≈ −2.26
    # (flagged at threshold 2.0/1.5, NOT at 3.0).
    for m, sc in {"2026-01": 90.0, "2026-02": 85.0, "2026-03": 95.0, "2026-04": 90.0, "2026-05": 82.0}.items():
        db_session.add(IndicatorValue(hospital_id=h.id, month=m, indicator_id=ind.id, value=10))
        db_session.add(QualityScore(hospital_id=h.id, month=m, score=sc, rule_compliance=sc,
                                    consistency=sc, completeness=90.0))
    db_session.commit()
    cache.invalidate("analysis:months")

    # Defaults are exposed in the settings payload.
    s = client.get("/config/control/settings").json()
    assert s["anomaly_zscore_threshold"] == 2.0
    assert s["anomaly_drift_months"] == 3

    # Raising the threshold to 3.0 stops flagging the z≈−2.26 drop.
    client.put("/config/control/settings", json={"anomaly_zscore_threshold": 3.0})
    r = client.get("/dashboard/attention").json()
    assert all(x["hospital_id"] != h.id for x in r["anomalies"])

    # Lowering it to 1.5 flags it.
    client.put("/config/control/settings", json={"anomaly_zscore_threshold": 1.5})
    r = client.get("/dashboard/attention").json()
    assert any(x["hospital_id"] == h.id and x["kind"] == "drop" for x in r["anomalies"])

    # Out-of-range clamps to 5.0; unparseable input is ignored.
    client.put("/config/control/settings", json={"anomaly_zscore_threshold": 99})
    assert client.get("/config/control/settings").json()["anomaly_zscore_threshold"] == 5.0
    client.put("/config/control/settings", json={"anomaly_zscore_threshold": "abc"})
    assert client.get("/config/control/settings").json()["anomaly_zscore_threshold"] == 5.0

    # Drift length: 3 consecutive small drops flagged at 3, not at 4.
    client.put("/config/control/settings", json={"anomaly_zscore_threshold": 2.0})
    h2 = db_session.query(Hospital).offset(1).first()
    for m, sc in {"2026-01": 90.0, "2026-02": 89.3, "2026-03": 88.6, "2026-04": 87.9}.items():
        db_session.add(IndicatorValue(hospital_id=h2.id, month=m, indicator_id=ind.id, value=10))
        db_session.add(QualityScore(hospital_id=h2.id, month=m, score=sc, rule_compliance=sc,
                                    consistency=sc, completeness=90.0))
    db_session.commit()
    cache.invalidate("analysis:months")
    client.put("/config/control/settings", json={"anomaly_drift_months": 4})
    r = client.get("/dashboard/attention").json()
    assert all(x["hospital_id"] != h2.id for x in r["anomalies"])
    client.put("/config/control/settings", json={"anomaly_drift_months": 3})
    r = client.get("/dashboard/attention").json()
    d = next((x for x in r["anomalies"] if x["hospital_id"] == h2.id), None)
    assert d is not None and d["kind"] == "drift" and d["months"] == 3

    # Restore defaults so later tests see stock behavior.
    client.put("/config/control/settings", json={"anomaly_zscore_threshold": 2.0, "anomaly_drift_months": 3})


def test_why_popup_quality_score_carries_score_trend(app, db_session, ux_data):
    """The quality_score Why payload carries the hospital's own recent score
    trend (last ≤6 analyzed months, oldest first) so the popup can render a
    sparkline putting the anomaly in context."""
    client = TestClient(app)
    r = client.get("/audit/explain", params={
        "kind": "quality_score", "hospital_id": ux_data["good"], "month": "2026-03",
    }).json()
    assert "error" not in r, r.get("error")
    tr = r["score_trend"]
    assert [d["month"] for d in tr] == ["2026-01", "2026-02", "2026-03"]
    assert [d["score"] for d in tr] == [70.0, 75.0, 85.0]
    assert r["component"] == "quality_score"


def test_why_popup_component_trend_uses_component_column(app, db_session, ux_data):
    """Asking for a component plots THAT component's history — same request
    as the overall trend but a different series (completeness is flat 90
    here while the score climbs 70→85)."""
    client = TestClient(app)
    r = client.get("/audit/explain", params={
        "kind": "quality_score", "hospital_id": ux_data["good"], "month": "2026-03",
        "component": "completeness",
    }).json()
    assert r["component"] == "completeness"
    assert [d["score"] for d in r["score_trend"]] == [90.0, 90.0, 90.0]
    # outlier_score plots the INVERTED penalty (100−penalty), never the raw one
    r2 = client.get("/audit/explain", params={
        "kind": "quality_score", "hospital_id": ux_data["good"], "month": "2026-03",
        "component": "outlier_score",
    }).json()
    assert r2["component"] == "outlier_score"
    assert all(0.0 <= d["score"] <= 100.0 for d in r2["score_trend"])


def test_component_anomaly_why_params_carry_component(app, db_session):
    """Component anomaly rows must carry their component in why[], so the
    popup opens with THAT component's sparkline."""
    from app.cache import cache
    client = TestClient(app)
    ind = db_session.query(Indicator).first()
    h = db_session.query(Hospital).first()
    for i, m in enumerate(("2026-01", "2026-02", "2026-03", "2026-04", "2026-05")):
        db_session.add(IndicatorValue(hospital_id=h.id, month=m, indicator_id=ind.id, value=10))
        db_session.add(QualityScore(hospital_id=h.id, month=m, score=90.0, rule_compliance=90.0,
                                    consistency=90.0, outlier_penalty=90.0,
                                    completeness=(95.0, 94.0, 93.0, 92.0, 60.0)[i]))
    db_session.commit()
    cache.invalidate("analysis:months")
    r = client.get("/dashboard/attention").json()
    comp = next(x for x in r["anomalies"] if x["hospital_id"] == h.id and x["component"] == "completeness")
    assert comp["why"]["component"] == "completeness"
    assert comp["why"]["kind"] == "quality_score"


def test_why_popup_trend_skips_ghost_month(app, db_session, ux_data):
    """Ghost months (no raw values) never pollute the trend — the sparkline
    plots analyzed months only. (scores are NOT NULL by schema, so no
    null-score case exists.)"""
    from app.models import IndicatorValue
    db_session.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == ux_data["good"],
        IndicatorValue.month == "2026-02",
    ).delete(synchronize_session=False)
    db_session.add(QualityScore(hospital_id=ux_data["good"], month="2026-02", score=0.0))
    db_session.commit()
    client = TestClient(app)
    r = client.get("/audit/explain", params={
        "kind": "quality_score", "hospital_id": ux_data["good"], "month": "2026-03",
    }).json()
    assert [d["month"] for d in r["score_trend"]] == ["2026-01", "2026-03"]
    assert [d["score"] for d in r["score_trend"]] == [70.0, 85.0]


def test_why_popup_explain_js_renders_sparkline():
    """UI contract: explain.js renders p.score_trend as an inline SVG
    sparkline with the first→last values and the translated title."""
    js = (Path(__file__).resolve().parent.parent / "static" / "js" / "explain.js").read_text(encoding="utf-8")
    tr = js[js.index("_renderScoreTrend"):]
    body = tr[:tr.index("function _renderPayload")]
    assert "<svg" in body and "<path" in body and "<circle" in body
    assert "score_trend" in body
    assert "Recent score trend" in body
    assert "first.score + ' \\u2192 ' + last.score" in body


def test_anomaly_detected_per_component_not_only_overall(app, db_session):
    """A hospital can look stable overall while one component quietly
    collapses — the detector must flag the COMPONENT (completeness here)
    and leave the stable overall score unflagged."""
    from app.cache import cache
    client = TestClient(app)
    ind = db_session.query(Indicator).first()
    h = db_session.query(Hospital).first()
    series = {
        # stable overall score ...
        "score": (90.0, 90.5, 89.5, 90.0, 90.0),
        # ... but completeness collapsing in the latest month
        "completeness": (95.0, 94.0, 93.0, 92.0, 60.0),
        "rule_compliance": (90.0,) * 5,
        "consistency": (90.0,) * 5,
        "outlier_penalty": (90.0,) * 5,
    }
    for i, m in enumerate(("2026-01", "2026-02", "2026-03", "2026-04", "2026-05")):
        db_session.add(IndicatorValue(hospital_id=h.id, month=m, indicator_id=ind.id, value=10))
        db_session.add(QualityScore(
            hospital_id=h.id, month=m,
            score=series["score"][i],
            completeness=series["completeness"][i],
            rule_compliance=series["rule_compliance"][i],
            consistency=series["consistency"][i],
            outlier_penalty=series["outlier_penalty"][i],
        ))
    db_session.commit()
    cache.invalidate("analysis:months")
    r = client.get("/dashboard/attention").json()
    mine = [x for x in r["anomalies"] if x["hospital_id"] == h.id]
    comp = next((x for x in mine if x["component"] == "completeness"), None)
    assert comp is not None, "collapsing completeness must be flagged"
    assert comp["kind"] == "drop" and comp["value"] == 60.0 and comp["zscore"] <= -2.0
    assert all(x["component"] != "quality_score" for x in mine), (
        "stable overall score must NOT be flagged"
    )
    assert all(m["hospital_id"] != h.id for m in r["movers"]), (
        "stable movers list proves this anomaly is invisible without per-component detection"
    )


def test_attention_alert_rows_carry_representative_rule_code(app, db_session, ux_data):
    """kind=rule explanations need a rule_code — the payload must pick the
    hospital's most-severe failure so the Why popup opens correctly."""
    client = TestClient(app)
    r = client.get("/dashboard/attention?month_from=2026-01&month_to=2026-03").json()
    alerts = {a["hospital_id"]: a for a in r["alerts"]}
    bad = alerts[ux_data["bad"]]
    assert bad["count"] == 2
    assert bad["top_severity"] == "CRITICAL"
    assert bad["top_rule_code"] == "R010"
    assert bad["why"]["kind"] == "rule"
    assert bad["why"]["rule_code"] == "R010"


def test_attention_flags_low_completeness_as_data_problem(app, db_session, ux_data):
    client = TestClient(app)
    r = client.get("/dashboard/attention?month_from=2026-01&month_to=2026-03").json()
    problems = {p["hospital_id"]: p for p in r["problems"]}
    assert problems[ux_data["bad"]]["completeness"] == 40.0
    assert ux_data["good"] not in problems  # 90% completeness is healthy
