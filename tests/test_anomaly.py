"""Tests for anomaly detection and statistical trend analysis (engine.anomaly)."""
import pytest
from app.engine.anomaly import (
    compute_rate,
    detect_anomalies,
    detect_monthly_trend,
    AnomalyResultData,
    analyze_historical_trends,
    compare_hospitals,
    detect_trend_anomalies,
    generate_historical_summary,
    RATE_DEFINITIONS,
    TrendResult,
    HospitalComparison,
)


# ── Cross-screen consistency: anomaly engine vs audit benchmark screen ─────

def _seed_hospital_month(db_session, name, month, values):
    """Create an active hospital with IndicatorValue rows for the given month."""
    from app.models import Hospital, IndicatorValue, Indicator

    hosp = Hospital(name=name, region="Region A")
    db_session.add(hosp)
    db_session.flush()
    code_to_ind = {i.code: i for i in db_session.query(Indicator).all()}
    for code, val in values.items():
        ind = code_to_ind.get(code)
        if ind is None:
            continue
        db_session.add(IndicatorValue(hospital_id=hosp.id, indicator_id=ind.id, month=month, value=val))
    db_session.flush()
    return hosp


def _hospital_id(db_session, name):
    from app.models import Hospital
    return db_session.query(Hospital).filter_by(name=name).first().id


def test_anomaly_benchmark_matches_audit_peer_average(db_session):
    """Regression: for the same month's data, the anomaly engine's cross-hospital
    benchmark and z-score must equal the audit benchmark screen's peer_average
    and z_score — both screens show peer stats EXCLUDING the target hospital.
    Uses real DB loading (get_all_hospital_data_for_month) shared by both paths.
    """
    import numpy as np
    from app.engine.pipeline import get_all_hospital_data_for_month
    from app.engine.audit.benchmark import get_benchmark

    month = "2027-07"
    # Three reporting hospitals + one with no data that month (must be
    # excluded from both screens' peer sets). C-section rates: A=30%, B=50%,
    # Target=90% -> peer average 40% for Target; Target+HospB => 70% for HospA.
    _seed_hospital_month(db_session, "Target", month, {"2": 100, "5": 90})
    _seed_hospital_month(db_session, "HospA", month, {"2": 100, "5": 30})
    _seed_hospital_month(db_session, "HospB", month, {"2": 100, "5": 50})
    _seed_hospital_month(db_session, "IdleHosp", month, {})
    db_session.commit()

    all_data = get_all_hospital_data_for_month(db_session, month)
    assert set(all_data) == {"Target", "HospA", "HospB"}  # IdleHosp has no data

    audit = get_benchmark(db_session, _hospital_id(db_session, "Target"), month)
    assert "error" not in audit

    anomaly_rows = detect_anomalies(all_data, "Target", month)

    # 1) Both screens must present the SAME rate set.
    anomaly_names = {r.rate_name for r in anomaly_rows}
    audit_names = set(audit["comparisons"].keys())
    assert anomaly_names == audit_names, (
        f"rate-set mismatch: anomaly-only={anomaly_names - audit_names}, "
        f"audit-only={audit_names - anomaly_names}"
    )

    # 2) For every listed rate, all shared stats must match exactly.
    for row in anomaly_rows:
        comp = audit["comparisons"][row.rate_name]
        assert row.benchmark == comp["peer_average"], (
            f"{row.rate_name}: anomaly benchmark {row.benchmark} != audit peer_average {comp['peer_average']}"
        )
        assert row.peer_count == comp["peer_count"]
        assert row.peer_median == comp["peer_median"]
        assert row.peer_min == comp["peer_min"]
        assert row.peer_max == comp["peer_max"]
        assert row.z_score == comp["z_score"]
        # Independent recomputation over peers (excluding Target) as ground truth
        _, num_code, den_code, _ = next(d for d in RATE_DEFINITIONS if d[0] == row.rate_name)
        peers = [p for p in (compute_rate(all_data[h], num_code, den_code) for h in all_data if h != "Target") if p is not None]
        assert row.benchmark == round(float(np.mean(peers)), 2)

    # Sanity: the fixture actually exercises a multi-rate comparison.
    assert "C-section rate" in anomaly_names

    # 3) From HospA's perspective: peers are Target + HospB -> (90 + 50) / 2 = 70
    audit_a = get_benchmark(db_session, _hospital_id(db_session, "HospA"), month)
    cs_a = next(r for r in detect_anomalies(all_data, "HospA", month) if r.rate_name == "C-section rate")
    assert cs_a.benchmark == audit_a["comparisons"]["C-section rate"]["peer_average"] == 70.0


# ── compute_rate ──────────────────────────────────────────────

def test_compute_rate_normal():
    values = {"5": 80, "2": 300}
    rate = compute_rate(values, "5", "2")
    assert rate == pytest.approx(26.67, rel=0.01)


def test_compute_rate_zero_denominator():
    values = {"5": 80, "2": 0}
    rate = compute_rate(values, "5", "2")
    assert rate is None


def test_compute_rate_missing_data():
    values = {"5": 80}
    rate = compute_rate(values, "5", "2")
    assert rate is None


def test_compute_rate_both_missing():
    rate = compute_rate({}, "5", "2")
    assert rate is None


def test_compute_rate_zero_numerator():
    rate = compute_rate({"5": 0, "2": 100}, "5", "2")
    assert rate == 0.0


# ── detect_anomalies ──────────────────────────────────────────

def test_detect_anomalies_outlier():
    normal_data = {f"Hosp{i}": {"5": 30 + i, "2": 100 + i * 2} for i in range(10)}
    normal_data["OutlierHosp"] = {"5": 90, "2": 100}
    results = detect_anomalies(normal_data, "OutlierHosp", "2026-04")
    cs_result = [r for r in results if r.rate_name == "C-section rate"]
    if cs_result:
        assert cs_result[0].is_outlier or cs_result[0].z_score > 2


def test_detect_anomalies_no_data():
    results = detect_anomalies({}, "TestHosp", "2026-04")
    assert results == []


def test_detect_anomalies_single_hospital():
    data = {"Hosp1": {"5": 50, "2": 200}}
    results = detect_anomalies(data, "Hosp1", "2026-04")
    assert len(results) == 0


def test_detect_anomalies_all_same():
    data = {f"H{i}": {"5": 50, "2": 200} for i in range(5)}
    results = detect_anomalies(data, "H0", "2026-04")
    for r in results:
        assert r.z_score == 0.0
        assert not r.is_outlier


def test_detect_anomalies_returns_anomaly_result_data():
    data = {f"H{i}": {"5": 30 + i * 5, "2": 100} for i in range(5)}
    results = detect_anomalies(data, "H0", "2026-04")
    for r in results:
        assert isinstance(r, AnomalyResultData)
        assert r.rate_name
        assert r.indicator_code


def test_detect_anomalies_custom_config():
    data = {f"H{i}": {"5": 30 + i, "2": 100} for i in range(5)}
    data["Out"] = {"5": 50, "2": 100}
    results = detect_anomalies(data, "Out", "2026-04", config={"zscore_threshold": 1.0})
    cs = [r for r in results if r.rate_name == "C-section rate"]
    if cs:
        assert cs[0].is_outlier


def test_detect_anomalies_benchmark_excludes_self():
    """Benchmark and z-score must be computed over PEER hospitals only
    (excluding the hospital itself) — the same semantics as the audit screen."""
    import numpy as np
    data = {f"Hosp{i}": {"5": 30 + i, "2": 100 + i * 2} for i in range(10)}
    data["OutlierHosp"] = {"5": 90, "2": 100}
    results = detect_anomalies(data, "OutlierHosp", "2026-04")
    cs = [r for r in results if r.rate_name == "C-section rate"]
    if cs:
        r = cs[0]
        peers = [compute_rate(data[h], "5", "2") for h in data if h != "OutlierHosp"]
        peer_mean = float(np.mean(peers))
        peer_std = float(np.std(peers, ddof=1)) if len(peers) > 1 else 0
        assert r.benchmark == round(peer_mean, 2)
        current_rate = compute_rate(data["OutlierHosp"], "5", "2")
        expected_z = (current_rate - peer_mean) / peer_std if peer_std > 0 else 0.0
        assert r.z_score == round(expected_z, 2)


def test_detect_anomalies_includes_peer_metadata():
    """Cross-hospital rows must carry the same peer stats the audit screen shows:
    count, std, min, max, median and per-peer detail over peers EXCLUDING the
    target hospital."""
    import numpy as np
    data = {
        "Target": {"5": 90, "2": 100},
        "A": {"5": 30, "2": 100},
        "B": {"5": 40, "2": 100},
        "C": {"5": 50, "2": 100},
    }
    results = detect_anomalies(data, "Target", "2026-04")
    cs = [r for r in results if r.rate_name == "C-section rate"]
    assert cs, "expected a C-section rate row"
    r = cs[0]
    peers = [compute_rate(data[h], "5", "2") for h in ("A", "B", "C")]
    assert r.peer_count == 3
    assert r.peer_std == round(float(np.std(peers, ddof=1)), 2)
    assert r.peer_min == round(float(min(peers)), 2)
    assert r.peer_max == round(float(max(peers)), 2)
    assert r.peer_median == round(float(np.median(peers)), 2)
    # Peer count excludes the target itself
    assert r.peer_count == len(data) - 1
    # Drill-down detail: every peer with its rate, sorted ascending, no target
    assert r.peers_detail == [
        {"hospital": "A", "rate": 30.0},
        {"hospital": "B", "rate": 40.0},
        {"hospital": "C", "rate": 50.0},
    ]


def test_detect_monthly_trend_has_no_peer_metadata():
    """Trend anomalies benchmark against the hospital's own history, so peer
    metadata must stay None there (the outliers screen hides it)."""
    history = {
        "2026-01": {"5": 25, "2": 200},
        "2026-02": {"5": 27, "2": 200},
        "2026-03": {"5": 26, "2": 200},
    }
    results = detect_monthly_trend(history, "2026-04", {"5": 60, "2": 200})
    assert results, "expected at least one trend row"
    for r in results:
        assert r.peer_count is None
        assert r.peer_std is None
        assert r.peers_detail is None


def test_outliers_api_returns_peer_metadata(db_session):
    """/analysis/outliers must surface the peer stats persisted by the pipeline
    so the outliers screen matches the audit benchmark screen."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.models import Hospital, AnomalyResult
    from app.cache import cache

    cache.invalidate("analysis:outliers")
    h = db_session.query(Hospital).first()
    db_session.add(AnomalyResult(
        hospital_id=h.id, month="2027-06", indicator_code="5",
        rate_name="C-section rate", value=90.0, benchmark=40.0,
        z_score=3.1, is_outlier=True,
        peer_count=4, peer_std=5.5, peer_min=30.0, peer_max=50.0, peer_median=45.0,
        peers_detail=[
            {"hospital": "P1", "rate": 30.0},
            {"hospital": "P2", "rate": 40.0},
            {"hospital": "P3", "rate": 45.0},
            {"hospital": "P4", "rate": 50.0},
        ],
    ))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = TestClient(app).get("/analysis/outliers?month=2027-06")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 200
    row = next(r for r in resp.json()["data"] if r["month"] == "2027-06")
    assert row["peer_count"] == 4
    assert row["peer_std"] == 5.5
    assert row["peer_min"] == 30.0
    assert row["peer_max"] == 50.0
    assert row["peer_median"] == 45.0
    # Drill-down detail round-trips through persistence + API
    assert row["peers_detail"] == [
        {"hospital": "P1", "rate": 30.0},
        {"hospital": "P2", "rate": 40.0},
        {"hospital": "P3", "rate": 45.0},
        {"hospital": "P4", "rate": 50.0},
    ]


def test_detect_anomalies_no_peers_after_exclusion():
    """A hospital with no peers for a rate must not produce a benchmark row."""
    data = {
        "H0": {"5": 50, "2": 200},
        "H1": {"5": 30, "2": 200, "17": 5, "6": 200, "11": 1, "10": 3, "7": 2, "16": 9, "6.f": 8},
        "H2": {"5": 31, "2": 200},
    }
    results = detect_anomalies(data, "H0", "2026-04")
    for r in results:
        assert r.rate_name != "Maternal mortality ratio"  # only H1 reports '11'/'2'


# ── detect_monthly_trend ──────────────────────────────────────

def test_detect_monthly_trend_outlier():
    history = {
        "2026-01": {"5": 25, "2": 200},
        "2026-02": {"5": 27, "2": 200},
        "2026-03": {"5": 26, "2": 200},
    }
    current = {"5": 60, "2": 200}
    results = detect_monthly_trend(history, "2026-04", current)
    cs = [r for r in results if "C-section" in r.rate_name]
    if cs:
        assert cs[0].is_outlier or cs[0].z_score > 2


def test_detect_monthly_trend_stable():
    history = {
        "2026-01": {"5": 25, "2": 200},
        "2026-02": {"5": 25, "2": 200},
        "2026-03": {"5": 25, "2": 200},
    }
    current = {"5": 25, "2": 200}
    results = detect_monthly_trend(history, "2026-04", current)
    for r in results:
        assert not r.is_outlier


def test_detect_monthly_trend_insufficient_history():
    history = {"2026-03": {"5": 25, "2": 200}}
    current = {"5": 60, "2": 200}
    results = detect_monthly_trend(history, "2026-04", current)
    assert len(results) == 0


# ── analyze_historical_trends ─────────────────────────────────

def test_analyze_historical_trends_basic():
    monthly = {
        "2026-01": {"5": 25, "2": 200},
        "2026-02": {"5": 28, "2": 200},
        "2026-03": {"5": 30, "2": 200},
        "2026-04": {"5": 35, "2": 200},
    }
    results = analyze_historical_trends("TestHosp", monthly)
    assert len(results) > 0
    for t in results:
        assert isinstance(t, TrendResult)
        assert t.rate_name
        assert t.trend_direction in ("increasing", "decreasing", "stable")
        assert t.trend_severity in ("negligible", "low", "moderate", "high", "critical")


def test_analyze_historical_trends_increasing():
    monthly = {f"2026-{i:02d}": {"5": 20 + i * 10, "2": 200} for i in range(1, 5)}
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs:
        assert cs[0].trend_direction == "increasing"


def test_analyze_historical_trends_decreasing():
    monthly = {f"2026-{i:02d}": {"5": 50 - i * 5, "2": 200} for i in range(1, 5)}
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs:
        assert cs[0].trend_direction == "decreasing"


def test_analyze_historical_trends_stable():
    monthly = {f"2026-{i:02d}": {"5": 30, "2": 200} for i in range(1, 5)}
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs:
        assert cs[0].trend_direction == "stable"


def test_analyze_historical_trends_insufficient_data():
    monthly = {"2026-01": {"5": 25, "2": 200}}
    results = analyze_historical_trends("TestHosp", monthly)
    assert len(results) == 0


def test_analyze_historical_trends_findings():
    monthly = {f"2026-{i:02d}": {"5": 20 + i * 15, "2": 200} for i in range(1, 5)}
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs and cs[0].is_significant:
        assert len(cs[0].findings) > 0


def test_analyze_historical_trends_consecutive():
    monthly = {
        "2026-01": {"5": 30, "2": 200},
        "2026-02": {"5": 32, "2": 200},
        "2026-03": {"5": 34, "2": 200},
        "2026-04": {"5": 36, "2": 200},
    }
    results = analyze_historical_trends("TestHosp", monthly)
    cs = [t for t in results if "C-section" in t.rate_name]
    if cs:
        assert cs[0].consecutive_count >= 1


# ── compare_hospitals ─────────────────────────────────────────

def test_compare_hospitals_basic():
    all_data = {
        "Hosp1": {"2026-04": {"5": 30, "2": 200}},
        "Hosp2": {"2026-04": {"5": 25, "2": 200}},
        "Hosp3": {"2026-04": {"5": 35, "2": 200}},
    }
    comparisons = compare_hospitals(all_data, "2026-04")
    assert len(comparisons) >= 3
    for c in comparisons:
        assert isinstance(c, HospitalComparison)
        assert c.comparison_label


def test_compare_hospitals_single():
    all_data = {"Hosp1": {"2026-04": {"5": 30, "2": 200}}}
    comparisons = compare_hospitals(all_data, "2026-04")
    assert len(comparisons) == 0


def test_compare_hospitals_no_month():
    all_data = {
        "Hosp1": {"2026-03": {"5": 30, "2": 200}},
        "Hosp2": {"2026-03": {"5": 25, "2": 200}},
    }
    comparisons = compare_hospitals(all_data, "2026-04")
    assert len(comparisons) == 0


def test_compare_hospitals_labels():
    all_data = {
        "Hosp1": {"2026-04": {"5": 50, "2": 200}},
        "Hosp2": {"2026-04": {"5": 25, "2": 200}},
        "Hosp3": {"2026-04": {"5": 25, "2": 200}},
    }
    comparisons = compare_hospitals(all_data, "2026-04")
    labels = [c.comparison_label for c in comparisons]
    assert any("above" in label or "below" in label or "normal" in label for label in labels)


# ── detect_trend_anomalies ────────────────────────────────────

def test_detect_trend_anomalies_outlier():
    monthly = {
        "2026-01": {"5": 25, "2": 200},
        "2026-02": {"5": 26, "2": 200},
        "2026-03": {"5": 27, "2": 200},
        "2026-04": {"5": 80, "2": 200},
    }
    results = detect_trend_anomalies("TestHosp", monthly)
    cs = [r for r in results if "C-section" in r.rate_name]
    if cs:
        assert cs[0].is_outlier


def test_detect_trend_anomalies_insufficient():
    monthly = {"2026-01": {"5": 25, "2": 200}, "2026-02": {"5": 26, "2": 200}}
    results = detect_trend_anomalies("TestHosp", monthly)
    assert len(results) == 0


# ── generate_historical_summary ───────────────────────────────

def test_generate_historical_summary():
    trends = [TrendResult(
        hospital="H", indicator_code="5", rate_name="C-section rate",
        months=["2026-01", "2026-02"], values=[25, 30],
        mean=27.5, std=2.5, slope=2.5, slope_pct=9.1,
        trend_direction="increasing", trend_severity="moderate",
        is_significant=True, cv=9.1, last_vs_mean_pct_change=9.1,
        consecutive_direction="increasing", consecutive_count=2,
        findings=["test finding"],
    )]
    comparisons = [HospitalComparison(
        hospital="H", indicator_code="5", rate_name="C-section rate",
        value=30, benchmark=25, deviation_pct=20,
        percentile_rank=80, comparison_label="above average",
    )]
    summary = generate_historical_summary(trends, comparisons, [], [])
    assert "total_rates_analyzed" in summary
    assert summary["total_rates_analyzed"] >= 1
    assert summary["increasing_trends"] >= 1


def test_generate_historical_summary_empty():
    summary = generate_historical_summary([], [], [], [])
    assert summary["total_rates_analyzed"] == 0


# ── RATE_DEFINITIONS ──────────────────────────────────────────

def test_rate_definitions_count():
    assert len(RATE_DEFINITIONS) == 7


def test_rate_definitions_structure():
    for entry in RATE_DEFINITIONS:
        assert len(entry) == 4
        name, num, den, typical = entry
        assert isinstance(name, str)
        assert isinstance(num, str)
        assert isinstance(den, str)