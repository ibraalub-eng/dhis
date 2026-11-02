# -*- coding: utf-8 -*-
"""Very High KPIs count the band the approved cap policy allows.

The scan applies the two caps when it writes a row (a comparison with no
dispersion; a peer group too small to measure a spread). Rows written before a
cap was approved keep the band they were stored with, so the dashboard's Very
High Issues KPI, the Quality Alerts KPI cards and the alerts table disagreed
with the policy — on the live store 231 of 1448 open Very High issues were Very
High only through a comparison the policy refuses to grade.

``engine.effective_severity`` recomputes the band from the row's own evidence
(the same caps, the same order the scan applies them), and every counting and
filtering path uses it:

* the dashboard card and ``/quality-alerts/summary`` report the SAME number;
* the ``severity`` filter lists exactly the issues the KPI counts;
* the row keeps its stored band as ``stored_severity`` plus ``severity_cap``
  provenance, so the screen marks the difference instead of printing a
  severity the row itself contradicts.

Nothing is rewritten: a re-scan is still what restates the stored severity.
"""
import pytest

from app.api import quality_alerts as qa
from app.api.dashboard import _very_high_quality_issue_count
from app.engine.quality_alerts import (
    CLOSED_STATUSES,
    effective_severity,
    severity_cap,
)
from app.models import Hospital, QualityAlert

MONTH = "2027-05"
OTHER_MONTH = "2027-06"

_SUMMARY_KEYS = dict(month=None, hospital_id=None, indicator=None,
                     severity=None, perspective=None, status=None,
                     ownership_id=None, governorate_id=None,
                     hospital_type_id=None, confidence=None,
                     indicator_type=None, q=None, include_closed=False)


def _alert(db, hospital_id, *, code, severity, method, peer_count,
           stats=None, month=MONTH, perspective="all", evidence=None,
           score=1.0, pooled=False):
    payload = dict(evidence or {})
    if stats is not None:
        payload["stats"] = stats
    row = QualityAlert(
        hospital_id=hospital_id, month=month, perspective=perspective,
        indicator_code=code, indicator_name=f"{code} test rate",
        unit="%", formula=f"{code}_num / {code}_den * 100",
        severity=severity, score=score, method=method,
        current_value=90.0, baseline_value=10.0, z_score=224.0,
        peer_count=peer_count, status="New", active=True,
        direction="lower_is_better", interpretation="peer_anomaly",
        confidence="low", detected_at=None, updated_at=None, evidence=payload,
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def very_high_band_rows(db_session):
    """One hospital with four stored Very High rows of different shape.

    ``RB_THIN`` — a 2-peer comparison: the band is not gradable (thin peer).
    ``RB_FLAT`` — every peer identical: no dispersion.
    ``RB_SOLID`` — four peers with real spread: genuinely Very High.
    ``RB_DONE``  — a row the scan already capped: stored HIGH, nothing to cap.
    """
    hospital = db_session.query(Hospital).order_by(Hospital.id).first()
    _alert(db_session, hospital.id, code="RB_THIN", severity="VERY_HIGH",
           method="peer_zscore", peer_count=2,
           stats={"mean": 10.2, "std": 0.28, "points": 2},
           evidence={"peer_ids": [2, 3]})
    _alert(db_session, hospital.id, code="RB_FLAT", severity="VERY_HIGH",
           method="peer_zscore", peer_count=6,
           stats={"mean": 10.0, "std": 0.0, "points": 6})
    _alert(db_session, hospital.id, code="RB_SOLID", severity="VERY_HIGH",
           method="peer_zscore", peer_count=5,
           stats={"mean": 10.2, "std": 4.4, "points": 5})
    _alert(db_session, hospital.id, code="RB_DONE", severity="HIGH",
           method="peer_zscore", peer_count=2,
           stats={"mean": 10.2, "std": 0.28, "points": 2},
           evidence={"thin_peer_group": {"capped": True}})
    return hospital


# ── The shared band rule ───────────────────────────────────────────────────

def test_effective_severity_reapplies_the_approved_caps():
    # Thin peer group: 2 peers cannot measure a spread.
    assert effective_severity("VERY_HIGH", stats={"std": 0.28},
                              method="peer_zscore", peer_count=2) == "HIGH"
    # No dispersion: the score is a fallback, not a measured magnitude.
    assert effective_severity("VERY_HIGH", stats={"std": 0.0},
                              method="peer_zscore", peer_count=6) == "HIGH"
    # A large group with real spread keeps its band.
    assert effective_severity("VERY_HIGH", stats={"std": 4.4},
                              method="peer_zscore", peer_count=5) == "VERY_HIGH"
    # Idempotent: a row the scan already capped is unchanged.
    assert effective_severity("HIGH", stats={"std": 0.28},
                              method="peer_zscore", peer_count=2) == "HIGH"
    # A percentage change against a flat baseline is measurable.
    assert effective_severity("VERY_HIGH", stats={"std": 0.0},
                              method="pct_change", peer_count=12) == "VERY_HIGH"
    # The history perspective stores baseline MONTHS in peer_count: a short
    # window is governed by the observation minimum, not the peer minimum.
    assert effective_severity("VERY_HIGH", stats={"std": 3.1},
                              method="zscore", peer_count=3) == "VERY_HIGH"


def test_severity_cap_reports_only_an_actual_cap():
    assert severity_cap("VERY_HIGH", stats={"std": 4.4},
                        method="peer_zscore", peer_count=5) is None
    cap = severity_cap("VERY_HIGH", stats={"std": 0.28},
                       method="peer_zscore", peer_count=2)
    assert cap["stored_severity"] == "VERY_HIGH"
    assert cap["severity"] == "HIGH"
    assert cap["thin_peer_group"]["capped"] is True


# ── The three surfaces agree ───────────────────────────────────────────────

def test_dashboard_kpi_and_screen_kpi_count_the_same_band(db_session,
                                                          very_high_band_rows):
    dashboard = _very_high_quality_issue_count(db_session, None, None, None, None, None)
    summary = qa.get_summary(db=db_session, **_SUMMARY_KEYS)
    assert dashboard == summary["very_high_issues"] == 1, (
        "RB_THIN and RB_FLAT are not gradable; only RB_SOLID is Very High")
    # The demoted rows are still stored as Very High where the scan wrote them
    # that way; the count is the policy band, and the stored band is untouched.
    assert summary["by_severity"]["VERY_HIGH"] == 1
    assert summary["by_severity"]["HIGH"] == 3
    assert summary["very_high_issues"] == 1, \
        "the Very High band counted in the issue unit"
    assert summary["very_high_rows"] == 1, "perspective rows, same band"


def test_very_high_filter_lists_exactly_the_counted_issues(db_session,
                                                           very_high_band_rows):
    """KPI and table are the same unit: filtering Very High cannot list more."""
    listed = qa.list_issues(db=db_session, month=None, hospital_id=None,
                            indicator=None, severity="VERY_HIGH",
                            perspective=None, status=None, ownership_id=None,
                            governorate_id=None, hospital_type_id=None,
                            confidence=None, indicator_type=None, q=None,
                            include_closed=False, sort="severity", order="desc",
                            page=1, page_size=200)
    summary = qa.get_summary(db=db_session, **dict(_SUMMARY_KEYS,
                                                   severity="VERY_HIGH"))
    codes = {item["indicator_code"] for item in listed["items"]}
    assert listed["total"] == summary["total_issues"] == summary["very_high_issues"] == 1
    assert codes == {"RB_SOLID"}
    assert "RB_THIN" not in codes and "RB_FLAT" not in codes
    # The row the scan already capped is stored HIGH, so it is not Very High
    # either.
    assert "RB_DONE" not in codes


def test_row_keeps_its_stored_band_next_to_the_policy_band(db_session,
                                                           very_high_band_rows):
    rows = {a["indicator_code"]: a for a in
            (_row_dict(db_session, code) for code in
             ("RB_THIN", "RB_FLAT", "RB_SOLID"))}
    thin = rows["RB_THIN"]
    assert thin["severity"] == "HIGH"
    assert thin["stored_severity"] == "VERY_HIGH", "the row is not rewritten"
    assert thin["severity_cap"]["severity"] == "HIGH"
    assert thin["severity_cap"]["stored_severity"] == "VERY_HIGH"
    assert thin["thin_peer_group"] is True
    assert rows["RB_FLAT"]["severity_cap"]["dispersion"]["zero_spread"] is True
    solid = rows["RB_SOLID"]
    assert solid["severity"] == solid["stored_severity"] == "VERY_HIGH"
    assert solid["severity_cap"] is None


def _row_dict(db, code):
    from app.api.quality_alerts import _alert_dict
    row = (db.query(QualityAlert)
           .filter(QualityAlert.indicator_code == code).one())
    return _alert_dict(row)


def test_closed_and_inactive_rows_stay_out_of_the_count(db_session,
                                                        very_high_band_rows):
    row = (db_session.query(QualityAlert)
           .filter(QualityAlert.indicator_code == "RB_SOLID").one())
    assert row.status not in CLOSED_STATUSES
    assert _very_high_quality_issue_count(db_session, None, None, None, None,
                                    None) == 1
    row.status = "Resolved"
    db_session.commit()
    assert _very_high_quality_issue_count(db_session, None, None, None, None, None) == 0
