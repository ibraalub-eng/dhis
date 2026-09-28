# -*- coding: utf-8 -*-
"""Regression: the anomaly Why popup must not show a false "Not verified".

The pipeline stores value/benchmark/peer_std rounded to 2dp, but computes the
stored z from FULL-PRECISION rates. The Why popup used to recompute
z = (value − rounded_benchmark) / rounded_std and flagged real rows as
"❌ Not verified" (e.g. Neonatal mortality rate, hospital 16: stored z 20.82
vs 20.35 recomputed from rounded inputs).

Fix: explain_anomaly recomputes mean/std from `peers_detail` (unrounded peer
rates, ddof=1 like the pipeline) and falls back to rounded columns only when
the detail list is missing.
"""
import math

from app.engine.audit.explain import explain_anomaly


def _seed_anomaly(db_session, hospitals, month="2027-05"):
    """3 peers with rates that lose precision at 2dp + a hospital far above."""
    from app.models import AnomalyResult, Indicator, IndicatorValue

    codes = {}
    for code in ("17", "6"):
        ind = db_session.query(Indicator).filter(Indicator.code == code).first()
        assert ind is not None, f"indicator {code} must be seeded"
        codes[code] = ind.id

    # peer rates chosen so mean/std at 2dp differ from full precision enough
    # to flip the old exact check: rates 0.0, 0.0, 0.14 → mean=0.0467, std=0.0808
    raw = {"p1": (0, 50), "p2": (0, 60), "p3": (1, 700)}
    for hid, (num, den) in raw.items():
        db_session.add(IndicatorValue(hospital_id=hid, month=month, indicator_id=codes["17"], value=num))
        db_session.add(IndicatorValue(hospital_id=hid, month=month, indicator_id=codes["6"], value=den))
    # target hospital: 1/50 = 2% → full-precision z = (2 − 0.047633)/0.082503 ≈ 23.66
    db_session.add(IndicatorValue(hospital_id=4, month=month, indicator_id=codes["17"], value=1))
    db_session.add(IndicatorValue(hospital_id=4, month=month, indicator_id=codes["6"], value=50))
    db_session.commit()

    peers = [
        {"hospital": "p1", "rate": 0.0},
        {"hospital": "p2", "rate": 0.0},
        {"hospital": "p3", "rate": round(1 / 700 * 100, 4)},  # 0.1429 full precision
    ]
    row = AnomalyResult(
        hospital_id=4,
        month=month,
        indicator_code="17",
        rate_name="Neonatal mortality rate",
        value=2.0,
        benchmark=round(sum(p["rate"] for p in peers) / 3, 2),  # 0.05 (rounded)
        z_score=23.66,   # the pipeline's full-precision result
        is_outlier=True,
        peer_count=3,
        peer_std=round(0.0808, 2),  # 0.08 (rounded)
        peer_min=0.0,
        peer_max=0.14,
        peer_median=0.0,
        peers_detail=peers,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_anomaly_z_verified_from_full_precision_peers(app, db_session):
    row = _seed_anomaly(db_session, None)
    payload = explain_anomaly(db_session, row.hospital_id, row.month, rate_name=row.rate_name)
    rep = payload["reproduce"]

    # Full-precision recompute: mean = 0.047633..., std(ddof=1) = 0.0824...
    rates = [p["rate"] for p in row.peers_detail]
    mean_full = sum(rates) / len(rates)
    std_full = math.sqrt(sum((x - mean_full) ** 2 for x in rates) / (len(rates) - 1))
    expected = round((row.value - mean_full) / std_full, 2)

    assert rep["expected_z"] == expected
    assert rep["verified"] is True, (
        "z recomputed from unrounded peers_detail must match the stored z — "
        "rounded benchmark/std columns alone produced false 'Not verified'"
    )
    # the rounded-columns shortcut must NOT be what produced the verdict
    rounded_z = round((row.value - row.benchmark) / row.peer_std, 2)
    assert rounded_z != expected, "fixture must actually exercise the precision gap"
    assert abs(rounded_z - float(row.z_score)) > 0.05, (
        "the OLD rounded-columns math must disagree with the stored z — "
        "otherwise this test does not reproduce the bug"
    )


def test_anomaly_z_fallback_without_peers_detail(app, db_session):
    """When peers_detail is missing, the rounded-columns fallback still works
    (within its own tolerance)."""
    from app.models import AnomalyResult, Indicator, IndicatorValue

    ind = db_session.query(Indicator).filter(Indicator.code == "17").first()
    db_session.add(IndicatorValue(hospital_id=4, month="2027-06", indicator_id=ind.id, value=10))
    row = AnomalyResult(
        hospital_id=4, month="2027-06", indicator_code="17",
        rate_name="Neonatal mortality rate", value=2.0, benchmark=0.0,
        z_score=5.0, is_outlier=True, peer_count=2, peer_std=0.4,
        peers_detail=None,
    )
    db_session.add(row)
    db_session.commit()

    payload = explain_anomaly(db_session, 4, "2027-06", rate_name=row.rate_name)
    rep = payload["reproduce"]
    assert rep["expected_z"] == round((2.0 - 0.0) / 0.4, 2)
    assert rep["verified"] is True
