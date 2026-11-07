"""Shadow comparison-identity classification (Step 10D-4).

Pure classification tests build stored-shaped alert rows in memory: the unit
under test is ``_issue_comparison_evidence`` and the helper in
``app/engine/comparison_identity.py``, not the scan. The API test proves the
summary publishes the shadow fields beside the unchanged published KPI.
"""
import pytest

from app.api import quality_alerts as qa
from app.models import Hospital, QualityAlert


class _Alert:
    """One stored-quality-alert-shaped row, built without a session.

    Only the attributes the classification and ``_effective_severity`` read are
    set; ``peer_ids`` writes the nested ``comparison_policy`` block the scan
    stores, unless ``evidence`` is given verbatim (the legacy/unknown cases).
    """

    def __init__(self, perspective, *, peer_ids=None, peer_count=None,
                 severity="VERY_HIGH", z=3.2, current=80.0, baseline=10.0,
                 method=None, direction="lower_is_better", hospital_id=1,
                 month="2026-01", formula="QA_TEST_RATE", unit="%",
                 code="QA_TEST_RATE", alert_id=1, version="2026-10-24.1",
                 group=None, history=None, stats=None, evidence=None):
        self.perspective = perspective
        self.severity = severity
        self.z_score = z
        self.current_value = current
        self.baseline_value = baseline
        self.method = method or ("zscore" if perspective == "history"
                                 else "peer_zscore")
        self.direction = direction
        self.hospital_id = hospital_id
        self.month = month
        self.formula = formula
        self.unit = unit
        self.indicator_code = code
        self.indicator_name = "Test rate"
        self.formula_version = None
        self.id = alert_id
        self.status = "New"
        self.confidence = "high"
        self.detected_at = None
        self.peer_count = peer_count if peer_count is not None else (
            len(peer_ids) if peer_ids is not None else None)
        payload = dict(evidence or {})
        if history is not None:
            payload["history"] = [[f"2025-{i:02d}", value]
                                  for i, value in enumerate(history, start=1)]
        if stats is not None:
            payload["stats"] = stats
        if peer_ids is not None:
            policy = {"peer": {"peer_ids": list(peer_ids),
                               "group": group or f"stratified:{perspective}"}}
            if version:
                policy["peer"]["policy_version"] = version
            payload["comparison_policy"] = policy
        self.evidence = payload


def _detail(*rows):
    return qa._issue_comparison_evidence(list(rows))


# ── Identity: identical peer ids collapse ────────────────────────────────────

def test_identical_peer_ids_from_two_labels_count_once():
    """`all` + `facility_type` on one peer set is ONE comparison."""
    rows = [_Alert("all", peer_ids=[1, 2, 3, 4, 5], alert_id=1),
            _Alert("facility_type", peer_ids=[5, 4, 3, 2, 1], alert_id=2)]
    detail = _detail(*rows)
    assert detail["distinct_peer_comparisons"] == 1
    assert detail["comparison_category"] == "single_peer"
    assert detail["perspective_count"] == 2
    assert detail["distinct_perspective_count"] == 2
    assert detail["relationship_class"] == "not_applicable"
    (identity,) = detail["comparison_identities"]
    assert identity["perspectives"] == ["facility_type", "all"]
    assert identity["peer_ids"] == [1, 2, 3, 4, 5]
    assert identity["row_ids"] == [1, 2]


def test_identical_peer_ids_with_different_groups_still_collapse():
    """The group label is provenance, not identity."""
    rows = [_Alert("all", peer_ids=[1, 2, 3], group="all_active_reporting",
                   alert_id=1),
            _Alert("facility_type", peer_ids=[1, 2, 3],
                   group="stratified:facility_type", alert_id=2)]
    assert _detail(*rows)["distinct_peer_comparisons"] == 1


# ── Relationships: nested / overlapping / disjoint ──────────────────────────

def test_nested_groups_are_multiple_peer_and_nested_only():
    rows = [_Alert("governorate", peer_ids=[1, 2, 3, 4, 5], alert_id=1),
            _Alert("ownership", peer_ids=[1, 2, 3, 4, 5, 6, 7], alert_id=2)]
    detail = _detail(*rows)
    assert detail["comparison_category"] == "multiple_peer"
    assert detail["distinct_peer_comparisons"] == 2
    assert detail["relationship_class"] == "nested_only"
    by_label = {v["perspectives"][0]: v for v in detail["comparison_identities"]}
    (relation,) = by_label["governorate"]["relationships"]
    assert relation["relationship"] == "nested"
    assert relation["shared_peers"] == 5


def test_overlapping_groups_are_overlapping_only():
    rows = [_Alert("governorate", peer_ids=[1, 2, 3, 4], alert_id=1),
            _Alert("ownership", peer_ids=[3, 4, 5, 6, 7], alert_id=2)]
    detail = _detail(*rows)
    assert detail["comparison_category"] == "multiple_peer"
    assert detail["relationship_class"] == "overlapping_only"
    (relation,) = detail["comparison_identities"][0]["relationships"]
    assert relation["relationship"] == "overlapping"
    assert relation["shared_peers"] == 2


def test_disjoint_groups_are_all_disjoint():
    rows = [_Alert("governorate", peer_ids=[1, 2, 3], alert_id=1),
            _Alert("ownership", peer_ids=[40, 41, 42, 43], alert_id=2)]
    detail = _detail(*rows)
    assert detail["relationship_class"] == "all_disjoint"
    assert detail["comparison_identities"][0]["relationships"][0][
        "shared_peers"] == 0


def test_relationship_summary_refines_without_contradicting_the_two_way_view():
    """The 10D-2 audit reported a two-way split; the finer class must
    collapse back onto it exactly."""
    nested_and_disjoint = [
        _Alert("governorate", peer_ids=[1, 2, 3], alert_id=1),
        _Alert("ownership", peer_ids=[1, 2, 3, 4], alert_id=2),
        _Alert("type", peer_ids=[90, 91], alert_id=3)]
    detail = _detail(*nested_and_disjoint)
    assert detail["relationship_class"] == "mixed_relationships"
    assert detail["relationship_summary"] == "nested"

    nested_and_overlapping = [
        _Alert("governorate", peer_ids=[1, 2, 3], alert_id=1),
        _Alert("ownership", peer_ids=[1, 2, 3, 4], alert_id=2),
        _Alert("type", peer_ids=[4, 5, 6], alert_id=3)]
    detail = _detail(*nested_and_overlapping)
    assert detail["relationship_class"] == "mixed_relationships"
    assert detail["relationship_summary"] == "overlapping"


def test_single_comparison_has_no_relationship_summary():
    detail = _detail(_Alert("all", peer_ids=[1, 2, 3]))
    assert detail["relationship_class"] == "not_applicable"
    assert detail["relationship_summary"] is None


def test_mixed_relationships_are_named_mixed():
    rows = [_Alert("governorate", peer_ids=[1, 2, 3], alert_id=1),
            _Alert("ownership", peer_ids=[1, 2, 3, 4], alert_id=2),
            _Alert("type", peer_ids=[90, 91], alert_id=3)]
    assert _detail(*rows)["relationship_class"] == "mixed_relationships"


# ── Temporal evidence is not a peer comparison ──────────────────────────────

def test_temporal_row_is_excluded_from_the_peer_count():
    rows = [_Alert("ownership", peer_ids=[1, 2, 3, 4, 5, 6, 7], alert_id=1),
            _Alert("history", history=[9.0, 10.0, 11.0, 10.5], alert_id=2)]
    detail = _detail(*rows)
    assert detail["distinct_peer_comparisons"] == 1
    assert detail["comparison_category"] == "single_peer"
    assert detail["temporal_present"] is True
    assert detail["temporal_state"] == "valid"
    assert detail["temporal_bands"] == ["VERY_HIGH"]
    assert detail["perspective_count"] == 2


def test_temporal_only_requires_a_readable_window():
    rows = [_Alert("history", history=[9.0, 10.0, 11.0], alert_id=1)]
    detail = _detail(*rows)
    assert detail["comparison_category"] == "temporal_only"
    assert detail["distinct_peer_comparisons"] == 0


def test_legacy_history_without_a_window_is_unknown_not_temporal():
    """A history row whose stored window is gone cannot be counted as usable."""
    rows = [_Alert("history", evidence={"stats": {"z": 3.3}}, alert_id=1)]
    detail = _detail(*rows)
    assert detail["comparison_category"] == "unknown_identity"
    assert detail["temporal_present"] is True
    assert detail["temporal_state"] == "unknown"


# ── Peer + invalid / unknown evidence is preserved, not discarded ───────────

def test_peer_plus_invalid_evidence_keeps_the_peer_count():
    rows = [_Alert("governorate", peer_ids=[1, 2, 3], alert_id=1),
            _Alert("ownership", peer_ids=[1, 2, 3], peer_count=2, alert_id=2)]
    detail = _detail(*rows)
    assert detail["comparison_category"] == "single_peer"
    assert detail["invalid_evidence_present"] is True
    assert detail["invalid_perspectives"] == ["ownership"]
    assert detail["distinct_peer_comparisons"] == 1


def test_peer_plus_unknown_evidence_keeps_the_peer_count():
    rows = [_Alert("governorate", peer_ids=[1, 2, 3], alert_id=1),
            _Alert("ownership", peer_count=9, alert_id=2)]
    detail = _detail(*rows)
    assert detail["comparison_category"] == "single_peer"
    assert detail["unknown_evidence_present"] is True
    assert detail["unknown_perspectives"] == ["ownership"]


def test_invalid_only_issue_is_invalid_evidence():
    rows = [_Alert("governorate", peer_ids="not-a-list", alert_id=1),
            _Alert("ownership", peer_ids=[1, 1, 2], alert_id=2)]
    detail = _detail(*rows)
    assert detail["comparison_category"] == "invalid_evidence"
    assert detail["invalid_evidence_present"] is True
    assert detail["distinct_peer_comparisons"] == 0


def test_unknown_beats_invalid_when_a_row_cannot_name_its_comparison():
    rows = [_Alert("governorate", peer_count=4, alert_id=1),
            _Alert("ownership", peer_ids=[1, 1], alert_id=2)]
    assert _detail(*rows)["comparison_category"] == "unknown_identity"


def test_empty_issue_is_unknown_identity():
    detail = qa._issue_comparison_evidence([])
    assert detail["comparison_category"] == "unknown_identity"
    assert detail["perspective_count"] == 0
    assert detail["distinct_peer_comparisons"] == 0


# ── Conflicts and policy provenance ─────────────────────────────────────────

def test_conflicting_statistics_on_one_identity_are_surfaced():
    rows = [_Alert("governorate", peer_ids=[1, 2, 3, 4], z=4.1, alert_id=1),
            _Alert("ownership", peer_ids=[1, 2, 3, 4], z=2.2, alert_id=2)]
    detail = _detail(*rows)
    assert detail["distinct_peer_comparisons"] == 1
    assert detail["evidence_conflict"] is True
    assert "z_score" in detail["comparison_identities"][0]["conflict_fields"]
    assert detail["comparison_category"] == "single_peer"


def test_identical_statistics_are_not_a_conflict():
    rows = [_Alert("all", peer_ids=[1, 2, 3], alert_id=1),
            _Alert("facility_type", peer_ids=[1, 2, 3], alert_id=2)]
    assert _detail(*rows)["evidence_conflict"] is False


def test_mixed_policy_versions_stay_one_identity():
    rows = [_Alert("governorate", peer_ids=[1, 2, 3], version="2026-10-24.1",
                   alert_id=1),
            _Alert("ownership", peer_ids=[1, 2, 3], version="2026-11-01.1",
                   alert_id=2)]
    detail = _detail(*rows)
    assert detail["distinct_peer_comparisons"] == 1
    assert detail["policy_mixed"] is True
    assert detail["policy_versions"] == ["2026-10-24.1", "2026-11-01.1"]


def test_policy_version_is_not_part_of_the_identity():
    first = _detail(_Alert("all", peer_ids=[1, 2, 3], version="v1"))
    second = _detail(_Alert("all", peer_ids=[1, 2, 3], version="v2"))
    assert (first["comparison_identities"][0]["identity"]
            == second["comparison_identities"][0]["identity"])


def test_classification_does_not_depend_on_the_band():
    """Identity is the sample; the band is an outcome, so a lower band changes
    nothing about the comparison count."""
    very_high = _detail(
        _Alert("governorate", peer_ids=[1, 2, 3], alert_id=1),
        _Alert("ownership", peer_ids=[1, 2, 3, 4], alert_id=2))
    lower = _detail(
        _Alert("governorate", peer_ids=[1, 2, 3], severity="HIGH", alert_id=1),
        _Alert("ownership", peer_ids=[1, 2, 3, 4], severity="MODERATE",
               alert_id=2))
    assert (very_high["comparison_category"] == lower["comparison_category"]
            == "multiple_peer")
    assert (very_high["relationship_class"]
            == lower["relationship_class"] == "nested_only")


# ── Shadow aggregation ──────────────────────────────────────────────────────

def test_shadow_aggregation_partitions_and_balances():
    nested = [_Alert("governorate", peer_ids=[1, 2, 3], alert_id=1),
              _Alert("ownership", peer_ids=[1, 2, 3, 4], alert_id=2)]
    single = [_Alert("all", peer_ids=[7, 8, 9], alert_id=3)]
    temporal = [_Alert("history", history=[9.0, 10.0], alert_id=4)]
    mixed = [_Alert("governorate", peer_ids=[1, 2, 3], severity="HIGH",
                    alert_id=5)]
    evidence = {("a", 1): nested, ("b", 2): single,
                ("c", 3): temporal, ("d", 4): mixed}
    grouped = {key: rows for key, rows in evidence.items()}
    fits = {("a", 1): "only", ("b", 2): "only",
            ("c", 3): "only", ("d", 4): "mixed"}
    shadow = qa._comparison_shadow(fits, grouped, evidence,
                                   legacy_corroborated=2)
    assert shadow["total"] == 3
    assert shadow["multiple_peer"] == 1
    assert shadow["single_peer"] == 1
    assert shadow["temporal_only"] == 1
    assert shadow["unknown_identity"] == 0
    assert shadow["invalid_evidence"] == 0
    assert shadow["balances"] is True
    assert shadow["multiple_peer_by_relationship"]["nested_only"] == 1
    assert shadow["multiple_peer_by_relationship_summary"]["nested"] == 1
    assert shadow["legacy_corroborated_perspective_labels"] == 2


def test_shadow_counts_only_very_high_only_issues():
    rows = [_Alert("all", peer_ids=[1, 2, 3], alert_id=1)]
    evidence = {("a", 1): rows}
    shadow = qa._comparison_shadow({("a", 1): "mixed"}, evidence, evidence,
                                   legacy_corroborated=0)
    assert shadow["total"] == 0
    assert shadow["balances"] is True


# ── API: shadow fields beside the unchanged published KPI ──────────────────

def test_summary_publishes_shadow_fields_without_changing_the_kpi(db_session):
    hospital = db_session.query(Hospital).first()
    rows = [
        # One genuinely multi-comparison Very-High-only issue (nested groups).
        QualityAlert(
            hospital_id=hospital.id, month="2026-01",
            indicator_code="QA_SHADOW", indicator_name="Shadow rate",
            unit="%", formula="QA_SHADOW", perspective="governorate",
            severity="VERY_HIGH", method="peer_zscore", current_value=80.0,
            baseline_value=10.0, z_score=3.4, peer_count=5, direction="lower_is_better",
            status="New", active=True,
            evidence={"comparison_policy": {"peer": {
                "peer_ids": [1, 2, 3, 4, 5], "group": "stratified:governorate",
                "policy_version": "2026-10-24.1"}}, "stats": {"z": 3.4}}),
        QualityAlert(
            hospital_id=hospital.id, month="2026-01",
            indicator_code="QA_SHADOW", indicator_name="Shadow rate",
            unit="%", formula="QA_SHADOW", perspective="ownership",
            severity="VERY_HIGH", method="peer_zscore", current_value=80.0,
            baseline_value=10.0, z_score=3.1, peer_count=7, direction="lower_is_better",
            status="New", active=True,
            evidence={"comparison_policy": {"peer": {
                "peer_ids": [1, 2, 3, 4, 5, 6, 7],
                "group": "stratified:ownership",
                "policy_version": "2026-10-24.1"}}, "stats": {"z": 3.1}}),
        # A history-only issue: never a peer comparison.
        QualityAlert(
            hospital_id=hospital.id, month="2026-01",
            indicator_code="QA_SHADOW_HIST", indicator_name="Shadow history",
            unit="%", formula="QA_SHADOW_HIST", perspective="history",
            severity="VERY_HIGH", method="zscore", current_value=80.0,
            baseline_value=10.0, z_score=3.0, direction="lower_is_better",
            status="New", active=True,
            evidence={"history": [["2025-01", 9.0], ["2025-02", 10.0]],
                      "stats": {"z": 3.0}}),
    ]
    db_session.add_all(rows)
    db_session.commit()

    # Direct call: FastAPI's Query sentinels must be resolved explicitly,
    # exactly as the read-only Step 10D-2 scripts called the endpoint.
    summary = qa.get_summary(
        month=None, hospital_id=None, indicator=None, severity=None,
        perspective=None, status=None, ownership_id=None,
        governorate_id=None, hospital_type_id=None, confidence=None,
        indicator_type=None, very_high_scope=None, q=None,
        include_closed=False, db=db_session)

    for field in ("very_high_multiple_peer_issues",
                  "very_high_single_peer_issues",
                  "very_high_temporal_only_issues",
                  "very_high_unknown_identity_issues",
                  "very_high_invalid_evidence_issues"):
        assert isinstance(summary[field], int)
    shadow = summary["very_high_comparison_shadow"]
    assert shadow["balances"] is True
    assert (shadow["multiple_peer"] + shadow["single_peer"]
            + shadow["temporal_only"] + shadow["unknown_identity"]
            + shadow["invalid_evidence"]) == shadow["total"]
    # Population identity: the shadow total is the published Very-High-only
    # count, and the five categories partition it.
    assert shadow["total"] == summary["very_high_only_issues"]
    # The legacy perspective-label metric is untouched by the shadow fields.
    assert summary["very_high_only_corroborated_issues"] == (
        summary["very_high_only_breakdown"]["corroborated"])


def test_issue_payload_exposes_identity_per_comparison(db_session):
    hospital = db_session.query(Hospital).first()
    db_session.add(QualityAlert(
        hospital_id=hospital.id, month="2026-02",
        indicator_code="QA_SHADOW_ISSUE", indicator_name="Shadow issue",
        unit="%", formula="QA_SHADOW_ISSUE", perspective="governorate",
        severity="VERY_HIGH", method="peer_zscore", current_value=80.0,
        baseline_value=10.0, z_score=3.4, peer_count=4,
        direction="lower_is_better", status="New", active=True,
        evidence={"comparison_policy": {"peer": {
            "peer_ids": [1, 2, 3, 4], "group": "stratified:governorate",
            "policy_version": "2026-10-24.1"}}, "stats": {"z": 3.4}}))
    db_session.commit()

    rows = db_session.query(QualityAlert).filter(
        QualityAlert.indicator_code == "QA_SHADOW_ISSUE").all()
    detail = qa._issue_comparison_evidence(rows)
    assert detail["comparison_category"] == "single_peer"
    (identity,) = detail["comparison_identities"]
    assert identity["identity_hash"] == detail["comparison_identities"][0][
        "identity_hash"]
    assert len(identity["identity_hash"]) == 64
    assert identity["identity"] == identity["identity_hash"][:12]
    assert identity["source"] == "nested"
    assert identity["peer_count"] == 4
    assert identity["peer_ids"] == [1, 2, 3, 4]
    assert identity["perspectives"] == ["governorate"]
    assert identity["policy_versions"] == ["2026-10-24.1"]
    assert identity["evidence_state"] == "valid"


@pytest.mark.parametrize("bad", [
    {"comparison_policy": {"peer": {"peer_ids": [1, 2], "peer_count": 5}}},
    {"comparison_policy": {"peer": {"peer_ids": "1,2"}}},
])
def test_malformed_evidence_never_becomes_an_identity(bad):
    row = _Alert("governorate", evidence=bad, peer_count=5)
    detail = qa._issue_comparison_evidence([row])
    assert detail["distinct_peer_comparisons"] == 0
    assert detail["comparison_category"] in ("invalid_evidence",
                                             "unknown_identity")


# ── API: the breakdown cells are filters ──────────────────────────────────
# The five cells partition Very High only, so clicking one must list exactly
# the issues that cell counted — read from each issue's WHOLE evidence, never
# from the rows the band filter let through.

def _category_fixture(db_session):
    hospital = db_session.query(Hospital).first()

    def row(perspective, *, code, severity="VERY_HIGH", peer_ids=None,
            history=None):
        payload = {"stats": {"z": 3.2}}
        if peer_ids is not None:
            payload["comparison_policy"] = {"peer": {
                "peer_ids": list(peer_ids),
                "group": "stratified:" + perspective,
                "policy_version": "2026-10-24.1"}}
        if history is not None:
            payload["history"] = [[f"2025-{i:02d}", value]
                                  for i, value in enumerate(history, start=1)]
        return QualityAlert(
            hospital_id=hospital.id, month="2027-05", indicator_code=code,
            indicator_name=code, unit="%", formula=code, perspective=perspective,
            severity=severity,
            method=("zscore" if perspective == "history" else "peer_zscore"),
            current_value=80.0, baseline_value=10.0, z_score=3.2,
            peer_count=len(peer_ids) if peer_ids else None,
            direction="lower_is_better", status="New", active=True,
            evidence=payload)

    db_session.add_all([
        # multiple_peer: two distinct peer groups on one issue.
        row("governorate", code="QA_CAT_MULTI", peer_ids=[1, 2, 3, 4, 5]),
        row("ownership", code="QA_CAT_MULTI", peer_ids=[1, 2, 3, 4, 5, 6, 7]),
        # temporal_only: no peer group was compared at all. Twelve observed
        # months clear the history minimum, so the band is not capped.
        row("history", code="QA_CAT_TEMPORAL",
            history=[9.0 + i / 10.0 for i in range(12)]),
        # mixed: a Very High row beside a lower band.
        row("governorate", code="QA_CAT_MIXED", peer_ids=[1, 2, 3, 4, 5]),
        row("ownership", code="QA_CAT_MIXED", severity="HIGH",
            peer_ids=[1, 2, 3, 4, 5]),
    ])
    db_session.commit()


def _summary(db_session, **overrides):
    params = dict(
        month=None, hospital_id=None, indicator=None, severity=None,
        perspective=None, status=None, ownership_id=None, governorate_id=None,
        hospital_type_id=None, confidence=None, indicator_type=None,
        very_high_scope=None, comparison_category=None, q="QA_CAT",
        include_closed=False, db=db_session)
    params.update(overrides)
    return qa.get_summary(**params)


def _issues(db_session, **overrides):
    params = dict(
        month=None, hospital_id=None, indicator=None, severity=None,
        perspective=None, status=None, ownership_id=None, governorate_id=None,
        hospital_type_id=None, confidence=None, indicator_type=None,
        very_high_scope=None, comparison_category=None, q="QA_CAT",
        include_closed=False, sort="severity", order="desc", page=1,
        page_size=0, db=db_session)
    params.update(overrides)
    return qa.list_issues(**params)


def test_comparison_category_lists_exactly_the_cell_it_counts(db_session):
    _category_fixture(db_session)
    summary = _summary(db_session)
    assert summary["very_high_only_issues"] == 2
    assert summary["very_high_multiple_peer_issues"] == 1

    filtered = _summary(db_session, comparison_category="multiple_peer")
    assert filtered["total_issues"] == 1
    # The cells keep describing the whole Very High population, so the cell
    # that was clicked still shows the number it was clicked for.
    assert filtered["very_high_only_issues"] == 2
    assert filtered["very_high_multiple_peer_issues"] == 1

    issues = _issues(db_session, comparison_category="multiple_peer")
    assert issues["total"] == 1
    assert issues["items"][0]["canonical_code"] == "QA_CAT_MULTI"


def test_comparison_category_excludes_issues_outside_very_high_only(
        db_session):
    _category_fixture(db_session)
    # The mixed issue does carry a peer group, but a lower band keeps it out of
    # Very High only — so no cell counted it and no cell may list it.
    issues = _issues(db_session, comparison_category="multiple_peer")
    assert {item["canonical_code"] for item in issues["items"]} == {
        "QA_CAT_MULTI"}

    filtered = _summary(db_session, comparison_category="temporal_only")
    assert filtered["total_issues"] == 1
    assert filtered["very_high_temporal_only_issues"] == 1


def test_comparison_category_rejects_an_unknown_value(db_session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _summary(db_session, comparison_category="mostly")
    assert exc.value.status_code == 422
    assert "comparison_category" in exc.value.detail
