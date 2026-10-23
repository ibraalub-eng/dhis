"""The outlier scan covers EVERY derivative indicator, once.

Before: the analysis candidate set was `resolve_active_definitions(site=
"zscore")` — seven rates — so the Outlier Analysis screen could never show the
clinical-only indicators (breastfeeding, low birth weight, hysterectomy, …)
even though the Indicators screen lists them as derivative indicators. The
screen's own "Derivative Indicator" filter made it worse: its options were
rebuilt from the returned rows, so the list shrank to whichever rates happened
to have an outlier.

Now: `resolve_outlier_candidates` returns one candidate per derivative
indicator (grouping the per-site copies of a rate by formula + unit scale, the
zscore copy representing its group), the pipeline analyzes that set, and the
filter is populated from the registry.
"""
import pytest
from fastapi.testclient import TestClient

from app.cache import cache
from app.models import AnomalyResult, Hospital, Indicator, IndicatorValue


def _seed_values(db, hospital, month, values):
    for code, value in values.items():
        ind = db.query(Indicator).filter(Indicator.code == code).first()
        if ind is not None:
            db.add(IndicatorValue(hospital_id=hospital.id, month=month,
                                  indicator_id=ind.id, value=value))
    db.commit()


def _candidates(db):
    from app.engine import indicator_service

    return indicator_service.resolve_outlier_candidates(db)


def test_candidates_cover_clinical_only_rates_once(db_session):
    candidates = _candidates(db_session)
    codes = {r.code for r in candidates}

    # Clinical-only derivatives are part of the scan (they were invisible).
    assert "sys_clinical_rate_lbw" in codes
    assert "sys_clinical_rate_bf" in codes
    assert "sys_clinical_rate_hysterectomy" in codes

    # A rate stored per analysis site appears ONCE, represented by its zscore
    # copy — the name the scan has always reported, so stored rows stay stable.
    by_name = {r.name: r for r in candidates}
    assert by_name["C-section rate"].site == "zscore"
    assert "C-Section Rate" not in by_name          # clinical duplicate merged
    assert sum(1 for r in candidates if r.code.endswith("rate_cs")) == 1

    # …and each candidate is a distinct formula (nothing is lost in grouping).
    keys = [(r.formula, r.unit) for r in candidates]
    assert len(keys) == len(set(keys))


def test_candidates_follow_registry_active_flag(db_session):
    from app.models import IndicatorDefinition

    lbw = (db_session.query(IndicatorDefinition)
           .filter(IndicatorDefinition.code == "sys_clinical_rate_lbw").one())
    lbw.is_active = False
    db_session.commit()
    try:
        assert "sys_clinical_rate_lbw" not in {r.code for r in _candidates(db_session)}
    finally:
        lbw.is_active = True
        db_session.commit()


def test_pipeline_scans_clinical_only_rates(db_session, sample_values):
    from app.engine.pipeline import run_full_analysis

    hospitals = db_session.query(Hospital).order_by(Hospital.id).limit(2).all()
    for hospital in hospitals:
        _seed_values(db_session, hospital, "2026-04", sample_values)

    run_full_analysis(db_session, hospitals[0].id, "2026-04", force=True)

    rows = (db_session.query(AnomalyResult)
            .filter(AnomalyResult.hospital_id == hospitals[0].id,
                    AnomalyResult.month == "2026-04")
            .all())
    names = {r.rate_name for r in rows}
    # Clinical-only derivative on the ingested values (13 / 6) — the zscore
    # slice never contained it before.
    assert "Breastfeeding within 1 Hour" in names, names
    assert "Hysterectomy per 1,000 Deliveries" in names, names

    bf = next(r for r in rows if r.rate_name == "Breastfeeding within 1 Hour")
    assert bf.formula == "{13} / {6} * 100"
    assert bf.value is not None

    # The same rate must not also appear under its other per-site copy.
    assert "C-section rate" in names
    assert "C-Section Rate" not in names


def test_outlier_indicators_endpoint_and_code_filter(app, db_session):
    hospitals = db_session.query(Hospital).order_by(Hospital.id).limit(2).all()
    for code, name, value in (
        ("sys_zscore_rate_nmr", "Neonatal mortality rate", 12.5),
        ("sys_clinical_rate_bf", "Breastfeeding within 1 Hour", 91.0),
    ):
        db_session.add(AnomalyResult(
            hospital_id=hospitals[0].id, month="2026-05",
            indicator_code=code, rate_name=name, value=value,
            benchmark=10.0, z_score=3.1, is_outlier=True, peer_count=4,
        ))
    db_session.commit()
    cache.invalidate()

    client = TestClient(app)
    resp = client.get("/analysis/outlier-indicators")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    codes = {i["code"] for i in items}
    assert "sys_clinical_rate_lbw" in codes
    assert "sys_zscore_rate_nmr" in codes

    # Filtering by definition code returns exactly that indicator's rows
    # (name filtering would mix same-name rates such as the two stillbirths).
    resp = client.get("/analysis/outliers", params={"indicator_code": "sys_zscore_rate_nmr"})
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert rows, "the seeded month must produce an NMR row"
    assert {r["indicator_code"] for r in rows} == {"sys_zscore_rate_nmr"}
