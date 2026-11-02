"""Step 10D-5 — Explain separates perspective LABELS from peer SETS.

Backend only. These tests drive the real Explain cross-check payload and pin:

* identical peer ids under two labels collapse to one comparison;
* nested / overlapping / disjoint groups are named with peer-set terms;
* temporal (history) evidence never becomes a peer comparison, and a missing
  window is ``unknown`` rather than an invented comparison;
* unknown, invalid, conflicting and mixed-version evidence stays visible
  beside a valid comparison instead of being dropped;
* effective severity keeps the meaning the Quality Alerts screen shows;
* explaining writes nothing.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import Hospital, LayeredOutlierResult, QualityAlert

LEVEL_VERY_HIGH = "VERY_HIGH"
LEVEL_HIGH = "HIGH"
METHOD_PEER = "peer_zscore"


@pytest.fixture()
def client(app):
    """TestClient over the conftest app (auth + db already overridden)."""
    return TestClient(app)


def _evidence(code, month, perspective, peer_ids, *,
              version="2026-10-24.1"):
    values = {str(peer_id): float(index)
              for index, peer_id in enumerate(peer_ids)}
    return {
        "z_threshold": 2.5,
        "comparison_policy": {
            "perspective_scope": ("detection_baseline" if perspective == "all"
                                  else "stratified"),
            "peer": {
                "policy_version": version,
                "group": "stratified:" + perspective,
                "group_label": perspective,
                "month": month,
                "min_peers": 2,
                "eligible_count": len(peer_ids),
                "peer_ids": list(peer_ids),
                "values": values,
            },
        },
        "canonical": {"key": f"test-{code}-{month}", "code": code,
                      "registered_codes": [code]},
    }


def _add_alert(db, hospital_id, *, alert_id, code, month, perspective,
               current, peer_ids=(), evidence=None, peer_count=None,
               severity=LEVEL_VERY_HIGH, method=METHOD_PEER):
    if evidence is None:
        evidence = _evidence(code, month, perspective, peer_ids)
    alert = QualityAlert(
        id=alert_id, hospital_id=hospital_id, month=month,
        perspective=perspective, indicator_code=code,
        indicator_name="Test indicator", unit="%", formula=None,
        severity=severity, score=1.0, method=method,
        current_value=current, baseline_value=None, z_score=None,
        peer_count=(len(peer_ids) if peer_count is None else peer_count),
        status="New", active=True, direction="none",
        interpretation="statistical_only", confidence="high",
        evidence=evidence,
    )
    db.add(alert)
    db.commit()
    return alert


def _add_row(db, hospital_id, month, code):
    row = LayeredOutlierResult(
        hospital_id=hospital_id, analysis_code=code, month=month,
        raw_value=24.0, previous_value=10.0, denominator=100.0, rate=24.0,
        raw_value_outlier_score=1.0, rate_outlier_score=1.0,
        historical_outlier_score=1.0, volume_anomaly_score=0.0,
        outlier_level=LEVEL_VERY_HIGH, outlier_type="HISTORICAL_ANOMALY",
        outlier_method="zscore", interpretation="statistical_only",
        investigation_route="none",
        history_provenance={"values": [1.0, 2.0, 3.0, 4.0]},
        classification_provenance={},
    )
    db.add(row)
    db.commit()
    return row


def _cross_check(client, hospital_id, month, code):
    resp = client.get(
        f"/audit/explain?kind=layered_outlier&hospital_id={hospital_id}"
        f"&month={month}&indicator_code={code}")
    assert resp.status_code == 200, resp.text
    return resp.json()["cross_check"]


def _narrative_text(narrative):
    parts = [narrative["labels_vs_comparisons"], narrative["temporal"] or ""]
    for key in ("comparisons", "relationships", "caveats"):
        parts.extend(narrative[key])
    return "\n".join(parts)


def test_identical_peer_sets_under_two_labels_are_one_comparison(
        db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    ids = [1000, 1001, 1002, 1003, 1004, 1005]
    _add_alert(db_session, hospital.id, alert_id=7001, code="2.l",
               month="2026-07", perspective="all", current=13.0,
               peer_ids=ids)
    _add_alert(db_session, hospital.id, alert_id=7002, code="2.l",
               month="2026-07", perspective="facility_type", current=13.0,
               peer_ids=ids)

    cc = _cross_check(client, hospital.id, "2026-07", "2.l")
    ce = cc["comparison_evidence"]
    assert ce["perspective_rows"] == 2
    assert ce["peer_rows"] == 2
    assert ce["distinct_peer_comparisons"] == 1
    assert ce["duplicate_perspective_rows"] == 1
    only = ce["comparisons"][0]
    assert set(only["perspectives"]) == {"all", "facility_type"}
    assert len(only["perspective_labels"]) == 2
    assert only["alert_ids"] == [7001, 7002]
    assert only["peer_ids"] == ids
    assert "counted once" in ce["narrative"]["labels_vs_comparisons"]
    for card in cc["peer_perspectives"]:
        assert card["comparison_identity"] == only["identity"]
        assert card["identity_hash"] == only["identity_hash"]
        assert card["peer_ids"] == ids


def test_nested_groups_are_named_nested(db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    _add_alert(db_session, hospital.id, alert_id=7011, code="2.l",
               month="2026-07", perspective="type", current=13.0,
               peer_ids=[1, 2, 3, 4, 5, 6])
    _add_alert(db_session, hospital.id, alert_id=7012, code="2.l",
               month="2026-07", perspective="ownership", current=13.0,
               peer_ids=[1, 2, 3, 4])

    ce = _cross_check(client, hospital.id, "2026-07", "2.l")[
        "comparison_evidence"]
    assert ce["distinct_peer_comparisons"] == 2
    assert ce["relationships"] == ["nested"]
    entry = next(item for item in ce["comparisons"]
                 if item["perspectives"] == ["type"])
    relation = entry["relationships"][0]
    assert relation["relationship"] == "nested"
    assert relation["shared_peers"] == 4
    text = "\n".join(ce["narrative"]["relationships"])
    assert "nested" in text
    assert "independent" not in text.lower()


def test_overlapping_and_disjoint_groups_use_peer_set_terms(
        db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    _add_alert(db_session, hospital.id, alert_id=7021, code="2.l",
               month="2026-07", perspective="type", current=13.0,
               peer_ids=[1, 2, 3, 4, 5, 6])
    _add_alert(db_session, hospital.id, alert_id=7022, code="2.l",
               month="2026-07", perspective="ownership", current=13.0,
               peer_ids=[5, 6, 7, 8, 9, 10])
    _add_alert(db_session, hospital.id, alert_id=7023, code="2.l",
               month="2026-07", perspective="governorate", current=13.0,
               peer_ids=[90, 91, 92, 93, 94, 95])

    ce = _cross_check(client, hospital.id, "2026-07", "2.l")[
        "comparison_evidence"]
    assert set(ce["relationships"]) == {"overlapping", "disjoint"}
    text = _narrative_text(ce["narrative"])
    assert "overlap" in text
    assert "disjoint" in text
    for banned in ("independent", "clinical", "confirmed"):
        assert banned not in text.lower()


def test_temporal_evidence_is_separate_and_never_a_peer_comparison(
        db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    _add_alert(db_session, hospital.id, alert_id=7031, code="2.l",
               month="2026-07", perspective="type", current=13.0,
               peer_ids=[1, 2, 3, 4, 5, 6])
    history_evidence = {
        "history": [["2026-05", 1.0], ["2026-06", 2.0]],
        "canonical": {"key": "test-2.l-2026-07", "code": "2.l",
                      "registered_codes": ["2.l"]},
    }
    _add_alert(db_session, hospital.id, alert_id=7032, code="2.l",
               month="2026-07", perspective="history", current=13.0,
               evidence=history_evidence, peer_count=0, method="zscore")

    ce = _cross_check(client, hospital.id, "2026-07", "2.l")[
        "comparison_evidence"]
    assert ce["distinct_peer_comparisons"] == 1
    assert ce["peer_rows"] == 1
    assert ce["temporal_rows"] == 1
    assert ce["temporal_state"] == "valid"
    assert ce["temporal"][0]["observations"] == 2
    assert 7032 not in ce["comparisons"][0]["alert_ids"]
    assert "temporal evidence" in ce["narrative"]["temporal"]


def test_history_without_window_is_unknown_not_invented(db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    _add_alert(db_session, hospital.id, alert_id=7041, code="2.l",
               month="2026-07", perspective="history", current=13.0,
               evidence={"canonical": {"key": "test-2.l-2026-07",
                                       "code": "2.l",
                                       "registered_codes": ["2.l"]}},
               peer_count=0, method="zscore")

    ce = _cross_check(client, hospital.id, "2026-07", "2.l")[
        "comparison_evidence"]
    assert ce["distinct_peer_comparisons"] == 0
    assert ce["peer_rows"] == 0
    assert ce["temporal_state"] == "unknown"
    assert ce["temporal"][0]["reason"] == "no_readable_history_window"
    assert "unknown" in ce["narrative"]["temporal"]
    assert "No stored label" in ce["narrative"]["labels_vs_comparisons"]


def test_truncated_top_level_group_is_unknown_and_flagged(
        db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    ids = list(range(2000, 2060))
    _add_alert(
        db_session, hospital.id, alert_id=7051, code="2.l", month="2026-07",
        perspective="type", current=13.0,
        evidence={"peer_ids": ids,
                  "canonical": {"key": "test-2.l-2026-07", "code": "2.l",
                                "registered_codes": ["2.l"]}},
        peer_count=60)

    ce = _cross_check(client, hospital.id, "2026-07", "2.l")[
        "comparison_evidence"]
    assert ce["distinct_peer_comparisons"] == 0
    assert ce["unknown_evidence_present"] is True
    assert ce["truncated_evidence_present"] is True
    assert ce["unreadable"][0]["reason"] == "top_level_truncation_possible"
    assert "incomplete" in "\n".join(ce["narrative"]["caveats"])


def test_contradictory_peer_evidence_is_invalid_and_kept(db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    _add_alert(db_session, hospital.id, alert_id=7061, code="2.l",
               month="2026-07", perspective="type", current=13.0,
               peer_ids=[1, 2, 3, 4, 5, 6], peer_count=5)

    ce = _cross_check(client, hospital.id, "2026-07", "2.l")[
        "comparison_evidence"]
    assert ce["distinct_peer_comparisons"] == 0
    assert ce["invalid_evidence_present"] is True
    assert ce["unknown_evidence_present"] is False
    assert ce["unreadable"][0]["state"] == "invalid"
    assert "contradicts itself" in "\n".join(ce["narrative"]["caveats"])


def test_conflicting_statistics_are_one_comparison(db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    ids = [1, 2, 3, 4, 5, 6]
    _add_alert(db_session, hospital.id, alert_id=7071, code="2.l",
               month="2026-07", perspective="type", current=13.0,
               peer_ids=ids)
    _add_alert(db_session, hospital.id, alert_id=7072, code="2.l",
               month="2026-07", perspective="ownership", current=14.0,
               peer_ids=ids)

    ce = _cross_check(client, hospital.id, "2026-07", "2.l")[
        "comparison_evidence"]
    assert ce["distinct_peer_comparisons"] == 1
    assert ce["evidence_conflict"] is True
    assert ce["comparisons"][0]["conflict_fields"] == ["current_value"]
    text = "\n".join(ce["narrative"]["caveats"])
    assert "conflicting statistics" in text
    assert "not a second comparison" in text


def test_mixed_policy_versions_are_provenance_not_another_sample(
        db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    ids = [1, 2, 3, 4, 5, 6]
    _add_alert(db_session, hospital.id, alert_id=7081, code="2.l",
               month="2026-07", perspective="type", current=13.0,
               peer_ids=ids, evidence=_evidence("2.l", "2026-07", "type",
                                                ids,
                                                version="2026-06-01.1"))
    _add_alert(db_session, hospital.id, alert_id=7082, code="2.l",
               month="2026-07", perspective="ownership", current=13.0,
               peer_ids=ids)

    ce = _cross_check(client, hospital.id, "2026-07", "2.l")[
        "comparison_evidence"]
    assert ce["distinct_peer_comparisons"] == 1
    assert ce["policy_mixed"] is True
    assert ce["policy_versions"] == ["2026-06-01.1", "2026-10-24.1"]
    assert "provenance" in "\n".join(ce["narrative"]["caveats"])


def test_unreadable_evidence_stays_visible_beside_a_valid_comparison(
        db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    _add_alert(db_session, hospital.id, alert_id=7091, code="2.l",
               month="2026-07", perspective="type", current=13.0,
               peer_ids=[1, 2, 3, 4, 5, 6])
    _add_alert(
        db_session, hospital.id, alert_id=7092, code="2.l", month="2026-07",
        perspective="ownership", current=13.0,
        evidence={"peer_ids": list(range(2000, 2060)),
                  "canonical": {"key": "test-2.l-2026-07", "code": "2.l",
                                "registered_codes": ["2.l"]}},
        peer_count=60)
    _add_alert(db_session, hospital.id, alert_id=7093, code="2.l",
               month="2026-07", perspective="history", current=13.0,
               evidence={"canonical": {"key": "test-2.l-2026-07",
                                       "code": "2.l",
                                       "registered_codes": ["2.l"]}},
               peer_count=0, method="zscore")

    ce = _cross_check(client, hospital.id, "2026-07", "2.l")[
        "comparison_evidence"]
    assert ce["distinct_peer_comparisons"] == 1
    assert ce["peer_rows"] == 1
    assert ce["unknown_evidence_present"] is True
    assert ce["temporal_present"] is True
    assert ce["temporal_state"] == "unknown"
    assert ce["invalid_evidence_present"] is False
    assert 7091 in ce["comparisons"][0]["alert_ids"]


def test_effective_severity_matches_what_the_screen_shows(db_session, client):
    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    _add_alert(db_session, hospital.id, alert_id=7101, code="2.l",
               month="2026-07", perspective="type", current=13.0,
               peer_ids=[1, 2, 3, 4, 5, 6])

    cc = _cross_check(client, hospital.id, "2026-07", "2.l")
    ce = cc["comparison_evidence"]
    assert ce["comparisons"][0]["effective_severity"] == LEVEL_VERY_HIGH
    assert ce["comparisons"][0]["stored_severities"] == [LEVEL_VERY_HIGH]
    shown = {item["perspective"]: item["severity"]
             for item in cc["perspectives"]}
    assert shown["type"] == LEVEL_VERY_HIGH
    assert ce["comparisons"][0]["effective_severity"] == shown["type"]
    # Stored and displayed bands stay separate fields (an approved cap can
    # lower the second); this row is uncapped, so both are published.
    assert cc["perspectives"][0]["stored_severity"] == LEVEL_VERY_HIGH
    for card in cc["peer_perspectives"]:
        assert (card["comparison_identity"]
                == ce["comparisons"][0]["identity"])


def test_explaining_the_comparison_writes_nothing(db_session):
    """The engine path builds the block without touching a stored row.

    The HTTP route runs the app's own month scan on access, so this test calls
    the engine function the route delegates to: the question is whether the
    comparison block writes, not what unrelated middleware does.
    """
    from app.engine.audit.explain import explain_layered_outlier

    hospital = db_session.query(Hospital).first()
    _add_row(db_session, hospital.id, "2026-07", "2.l")
    ids = [1, 2, 3, 4, 5, 6]
    _add_alert(db_session, hospital.id, alert_id=7111, code="2.l",
               month="2026-07", perspective="type", current=13.0,
               peer_ids=ids)
    _add_alert(db_session, hospital.id, alert_id=7112, code="2.l",
               month="2026-07", perspective="ownership", current=13.0,
               peer_ids=ids)

    def snapshot():
        db_session.expire_all()
        return [
            (alert.id, alert.severity, alert.current_value, alert.peer_count,
             dict(alert.evidence or {}), alert.status, alert.active)
            for alert in db_session.query(QualityAlert)
            .filter(QualityAlert.hospital_id == hospital.id,
                    QualityAlert.month == "2026-07")
            .order_by(QualityAlert.id).all()
        ]

    before = snapshot()
    payload = explain_layered_outlier(db_session, hospital.id, "2026-07",
                                      "2.l")
    assert "error" not in payload
    evidence = payload["cross_check"]["comparison_evidence"]
    assert evidence["distinct_peer_comparisons"] == 1
    assert evidence["duplicate_perspective_rows"] == 1
    assert snapshot() == before
