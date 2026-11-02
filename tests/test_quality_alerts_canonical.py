"""Canonical formula identity across Anomaly Diagnostics and Quality Alerts.

The Indicators Registry keeps one row per analysis site (``sys_zscore_*``,
``sys_clinical_*``, ``sys_forecast_*``) even when two rows hold the SAME
formula. For a logical rate that is one number computed one way, so the
diagnostics scan and the alert scan must identify it once — otherwise a single
finding is reported (and counted) once per registered code.

These tests pin the user story's acceptance criteria:

1. equivalent formulas resolve to the same canonical identity;
2. one hospital + month + canonical formula yields ONE logical alert;
3. every perspective stays available, while unique issues stay distinct from
   perspective-level rows in the dashboard totals;
4. the Very High issue KPI uses the same unique-issue policy;
5. an alert traces back to its canonical formula (and the diagnostic spec);
6. rebuilding never deletes or loses a legitimate, investigated alert;
7. unrelated formulas remain distinct.
"""
import pytest
from fastapi.testclient import TestClient

from app.engine import indicator_service
from app.engine.anomaly.layered import _spec_key, build_analysis_specs
from app.engine.canonical_identity import identity_key, ratio_identity
from app.models import (
    FacilityOwnership,
    FacilityType,
    Governorate,
    Hospital,
    HospitalType,
    Indicator,
    IndicatorDefinition,
    IndicatorValue,
    QualityAlert,
    QualityAlertEvent,
)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def duplicate_formula_dataset(db_session):
    """One logical rate registered twice under different codes.

    ``CANON_RATE`` and ``CANON_RATE_ALIAS`` carry an identical formula
    (QA_NUM / QA_DEN * 100), exactly like the seeded per-site copies of
    ``rate_cs``. ``CANON_OTHER_RATE`` uses a different denominator, so it must
    stay a separate identity.
    """
    num = Indicator(code="QA_NUM", name="QA numerator")
    den = Indicator(code="QA_DEN", name="QA denominator")
    other = Indicator(code="QA_OTHER", name="QA other denominator")
    db_session.add_all([num, den, other])
    db_session.flush()

    canonical = IndicatorDefinition(
        code="CANON_RATE", name="Canonical QA rate",
        formula_type="ratio", numerator_codes=["QA_NUM"],
        denominator_codes=["QA_DEN"], operator="/", multiplier=100.0,
        result_type="percentage", unit="%", direction="lower_is_better",
        is_active=True,
    )
    alias = IndicatorDefinition(
        code="CANON_RATE_ALIAS", name="Canonical QA rate (site copy)",
        formula_type="ratio", numerator_codes=["QA_NUM"],
        denominator_codes=["QA_DEN"], operator="/", multiplier=100.0,
        result_type="percentage", unit="%", direction="lower_is_better",
        is_active=True, source_site="clinical",
    )
    unrelated = IndicatorDefinition(
        code="CANON_OTHER_RATE", name="Unrelated QA rate",
        formula_type="ratio", numerator_codes=["QA_NUM"],
        denominator_codes=["QA_OTHER"], operator="/", multiplier=100.0,
        result_type="percentage", unit="%", is_active=True,
    )
    db_session.add_all([canonical, alias, unrelated])
    db_session.flush()

    hospitals = db_session.query(Hospital).order_by(Hospital.id).all()[:3]
    # Shared metadata so every supported perspective (type, ownership,
    # facility type, governorate) has a real peer group, not just history/all.
    governorate = Governorate(name="Test Governorate")
    hospital_type = HospitalType(name="Test Type")
    ownership = FacilityOwnership(name="Test Ownership")
    facility_type = FacilityType(name="Test Facility Type")
    db_session.add_all([governorate, hospital_type, ownership, facility_type])
    db_session.flush()
    for hospital in hospitals:
        hospital.governorate_id = governorate.id
        hospital.hospital_type_id = hospital_type.id
        hospital.facility_ownership_id = ownership.id
        hospital.facility_type_id = facility_type.id

    months = ["2026-05", "2026-06", "2026-07", "2026-08"]
    base = {0: 10.0, 1: 10.0, 2: 9.0}
    spike = {(0, 3): 80.0}
    # The unrelated formula deviates for a DIFFERENT hospital, so it can never
    # be confused with the canonical rate's issue.
    other_spike = {(2, 3): 5.0}
    for hi, hospital in enumerate(hospitals):
        for mi, month in enumerate(months):
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=num.id, month=month,
                value=spike.get((hi, mi), base[hi])))
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=den.id, month=month,
                value=100.0))
            db_session.add(IndicatorValue(
                hospital_id=hospital.id, indicator_id=other.id, month=month,
                value=other_spike.get((hi, mi), 50.0)))
    db_session.commit()
    return {
        "definitions": {"canonical": canonical, "alias": alias,
                        "unrelated": unrelated},
        "hospitals": hospitals, "months": months, "scan_month": months[-1],
    }


def _scan(client, month, hospital_id=None):
    return client.post("/quality-alerts/scan",
                       json={"month": month, "hospital_id": hospital_id})


# ── 1-2. Equivalent formulas → one canonical identity, one logical alert ─────

def test_duplicate_formula_definitions_produce_one_alert_issue(
        client, db_session, duplicate_formula_dataset):
    """A formula registered under two codes must not alert twice."""
    month = duplicate_formula_dataset["scan_month"]
    spike_hospital = duplicate_formula_dataset["hospitals"][0]

    resp = _scan(client, month)
    assert resp.status_code == 200, resp.text

    codes = {"CANON_RATE", "CANON_RATE_ALIAS"}
    rows = db_session.query(QualityAlert).filter(
        QualityAlert.hospital_id == spike_hospital.id,
        QualityAlert.month == month,
        QualityAlert.indicator_code.in_(codes)).all()
    assert rows, "the spiking hospital must still be detected"

    issues = client.get("/quality-alerts/issues", params={
        "month": month, "hospital_id": spike_hospital.id,
    }).json()["items"]
    mine = [i for i in issues
            if i["indicator_code"] in codes
            or i.get("canonical_code") in codes]
    assert len(mine) == 1, (
        "one hospital+month+canonical formula must be ONE logical alert, "
        f"got {[i['indicator_code'] for i in mine]}")
    assert mine[0]["perspective_count"] >= 2, "perspectives must be preserved"


def test_only_the_canonical_code_is_scanned(client, db_session,
                                            duplicate_formula_dataset):
    month = duplicate_formula_dataset["scan_month"]
    spike_hospital = duplicate_formula_dataset["hospitals"][0]
    assert _scan(client, month).status_code == 200

    alias_rows = db_session.query(QualityAlert).filter(
        QualityAlert.hospital_id == spike_hospital.id,
        QualityAlert.month == month,
        QualityAlert.indicator_code == "CANON_RATE_ALIAS").all()
    assert alias_rows == [], "the duplicate registration must not be scanned"


# ── 3. Perspectives remain, but totals distinguish issues from rows ─────────

def test_summary_separates_unique_issues_from_perspective_rows(
        client, duplicate_formula_dataset):
    month = duplicate_formula_dataset["scan_month"]
    assert _scan(client, month).status_code == 200

    summary = client.get("/quality-alerts/summary",
                         params={"month": month}).json()
    listed = client.get("/quality-alerts/issues",
                        params={"month": month}).json()
    assert summary["total_issues"] == listed["total"]
    assert summary["total_issues"] < summary["total_active"], (
        "perspective rows stay counted separately from unique issues")


# ── 6. Historical rebuild must not lose investigated alerts ─────────────────

def test_rebuild_retires_alias_rows_without_losing_investigation(
        client, db_session, duplicate_formula_dataset):
    """A pre-existing alert on the duplicate code is merged, never deleted."""
    month = duplicate_formula_dataset["scan_month"]
    spike_hospital = duplicate_formula_dataset["hospitals"][0]

    legacy = QualityAlert(
        hospital_id=spike_hospital.id, month=month, perspective="history",
        indicator_code="CANON_RATE_ALIAS", indicator_name="Canonical QA rate",
        formula="{QA_NUM} / {QA_DEN} * 100", unit="%",
        severity="HIGH", score=0.75, method="zscore", current_value=80.0,
        baseline_value=10.0, status="Confirmed Issue", assignee="analyst",
        active=True,
    )
    db_session.add(legacy)
    db_session.commit()
    legacy_id = legacy.id

    scan_result = _scan(client, month)
    assert scan_result.status_code == 200
    assert scan_result.json()["deduplicated"] >= 1

    retired = db_session.query(QualityAlert).filter_by(id=legacy_id).one()
    assert retired.active is False, "the duplicate row is retired, not deleted"

    canonical = db_session.query(QualityAlert).filter_by(
        hospital_id=spike_hospital.id, month=month,
        indicator_code="CANON_RATE", perspective="history").one()
    assert canonical.active is True
    assert canonical.status == "Confirmed Issue", "investigation state moved over"
    assert canonical.assignee == "analyst"
    notes = [e.note or "" for e in db_session.query(QualityAlertEvent)
             .filter_by(alert_id=canonical.id).all()]
    assert any("CANON_RATE_ALIAS" in note for note in notes), (
        "the merge itself must be auditable")

    # A legitimate finding on a genuinely different formula is untouched.
    other = db_session.query(QualityAlert).filter_by(
        hospital_id=spike_hospital.id, month=month,
        indicator_code="CANON_OTHER_RATE").all()
    assert other and all(row.active for row in other), (
        "deduplication must not retire unrelated legitimate alerts")


# ── 3. Every perspective stays available on one canonical issue ─────────────

def test_same_formula_supports_every_registered_perspective(
        client, duplicate_formula_dataset):
    month = duplicate_formula_dataset["scan_month"]
    spike_hospital = duplicate_formula_dataset["hospitals"][0]
    assert _scan(client, month).status_code == 200

    codes = {"CANON_RATE", "CANON_RATE_ALIAS"}
    issue = next(i for i in client.get("/quality-alerts/issues", params={
        "month": month, "hospital_id": spike_hospital.id,
    }).json()["items"]
        if i["indicator_code"] in codes or i["canonical_code"] in codes)

    perspectives = {p["perspective"] for p in issue["perspectives"]}
    assert perspectives == {"history", "type", "ownership", "facility_type",
                            "governorate", "all"}, (
        "every supported analytical perspective must survive canonicalisation")
    assert issue["perspective_count"] == len(issue["perspectives"])
    assert issue["canonical_key"], "the issue must carry its canonical identity"


# ── 2-3. Historical duplicate rows collapse without a rebuild ───────────────

def test_stored_duplicate_rows_count_as_one_issue(client, db_session,
                                                duplicate_formula_dataset):
    month = duplicate_formula_dataset["scan_month"]
    spike_hospital = duplicate_formula_dataset["hospitals"][0]
    for perspective, code, severity in (("history", "CANON_RATE", "HIGH"),
                                        ("all", "CANON_RATE_ALIAS", "HIGH")):
        db_session.add(QualityAlert(
            hospital_id=spike_hospital.id, month=month, perspective=perspective,
            indicator_code=code, indicator_name="Canonical QA rate",
            # Stored findings carry the formula they were computed with; that
            # is what identifies the logical finding.
            formula="{QA_NUM} / {QA_DEN} * 100", unit="%",
            severity=severity, score=0.8, method="zscore", current_value=80.0,
            baseline_value=10.0, status="New", active=True,
        ))
    db_session.commit()

    listed = client.get("/quality-alerts/issues", params={
        "month": month, "hospital_id": spike_hospital.id}).json()
    codes = {"CANON_RATE", "CANON_RATE_ALIAS"}
    mine = [i for i in listed["items"]
            if i["indicator_code"] in codes or i["canonical_code"] in codes]
    assert len(mine) == 1, "stored duplicate rows are one logical alert"
    assert mine[0]["perspective_count"] == 2, (
        "both perspective rows stay visible as evidence")
    assert set(mine[0]["registered_codes"]) >= codes, (
        "the issue traces back to every registration of the formula")

    summary = client.get("/quality-alerts/summary", params={
        "month": month, "hospital_id": spike_hospital.id}).json()
    assert summary["total_issues"] == 1
    assert summary["total_active"] == 2


# ── 4. One counting policy for issues and the Very High KPI ─────────────────

def test_very_high_kpi_uses_the_canonical_issue_policy(
        client, db_session, duplicate_formula_dataset):
    from app.api.dashboard import _very_high_quality_issue_count

    month = duplicate_formula_dataset["scan_month"]
    spike_hospital = duplicate_formula_dataset["hospitals"][0]
    assert _scan(client, month).status_code == 200

    summary = client.get("/quality-alerts/summary", params={
        "month": month, "hospital_id": spike_hospital.id}).json()
    kpi = _very_high_quality_issue_count(
        db_session, None, spike_hospital.id, month, month, None)
    assert kpi == summary["very_high_issues"], (
        "the dashboard card and the screen must use the same issue policy")

    # The duplicated formula contributes exactly ONE Very High issue, whatever
    # the number of perspectives (or registered codes) behind it.
    codes = {"CANON_RATE", "CANON_RATE_ALIAS"}
    canon_very_high = [i for i in client.get("/quality-alerts/issues", params={
        "month": month, "hospital_id": spike_hospital.id,
    }).json()["items"]
        if i["primary_severity"] == "VERY_HIGH"
        and (i["indicator_code"] in codes or i["canonical_code"] in codes)]
    assert len(canon_very_high) == 1
    baseline = summary["very_high_issues"]

    # A stale duplicate-code row must not inflate either total.
    db_session.add(QualityAlert(
        hospital_id=spike_hospital.id, month=month, perspective="all",
        indicator_code="CANON_RATE_ALIAS", indicator_name="Canonical QA rate",
        formula="{QA_NUM} / {QA_DEN} * 100", unit="%",
        severity="VERY_HIGH", score=1.0, method="zscore", current_value=80.0,
        baseline_value=10.0, status="New", active=True,
    ))
    db_session.commit()
    assert _very_high_quality_issue_count(
        db_session, None, spike_hospital.id, month, month, None) == baseline
    assert client.get("/quality-alerts/summary", params={
        "month": month, "hospital_id": spike_hospital.id,
    }).json()["very_high_issues"] == baseline


# ── 5. Traceability: alert -> canonical formula -> diagnostic spec ──────────

def test_alert_traces_to_canonical_formula_and_diagnostic_spec(
        client, db_session, duplicate_formula_dataset):
    month = duplicate_formula_dataset["scan_month"]
    spike_hospital = duplicate_formula_dataset["hospitals"][0]
    assert _scan(client, month).status_code == 200

    alert = db_session.query(QualityAlert).filter_by(
        hospital_id=spike_hospital.id, month=month,
        indicator_code="CANON_RATE").first()
    assert alert is not None
    canonical = (alert.evidence or {}).get("canonical")
    assert canonical, "every alert must record its canonical formula identity"
    assert set(canonical["registered_codes"]) == {
        "CANON_RATE", "CANON_RATE_ALIAS"}
    assert canonical["formula"] == "{QA_NUM} / {QA_DEN} * 100"
    assert canonical["key"] == identity_key(
        ("formula", "{QA_NUM} / {QA_DEN} * 100", 100.0))

    # The same identity is what Anomaly Diagnostics keys its analysis spec by,
    # so the alert can be traced to its diagnostic result.
    spec = next(s for s in build_analysis_specs(db_session)
                if s.analysis_code == canonical["code"])
    assert identity_key(_spec_key(spec)) == canonical["key"]

    detail = client.get(f"/quality-alerts/{alert.id}").json()
    assert detail["canonical"]["key"] == canonical["key"]


# ── 7. Unrelated formulas stay distinct ────────────────────────────────────

def test_unrelated_formulas_remain_distinct(client, db_session,
                                           duplicate_formula_dataset):
    month = duplicate_formula_dataset["scan_month"]
    assert _scan(client, month).status_code == 200

    formulas = {f.code: f for f in indicator_service.canonical_formulas(db_session)}
    assert formulas["CANON_RATE"].key != formulas["CANON_OTHER_RATE"].key, (
        "a different denominator is a different formula")
    assert "CANON_RATE_ALIAS" not in formulas, (
        "the duplicate registration is not a separate candidate")
    assert set(formulas["CANON_RATE"].registered_codes) == {
        "CANON_RATE", "CANON_RATE_ALIAS"}

    spike_hospital = duplicate_formula_dataset["hospitals"][0]
    unrelated_hospital = duplicate_formula_dataset["hospitals"][2]
    codes = {"CANON_RATE", "CANON_RATE_ALIAS"}
    canon_issues = [i for i in client.get("/quality-alerts/issues", params={
        "month": month}).json()["items"]
        if i["indicator_code"] in codes or i["canonical_code"] in codes]
    assert len(canon_issues) == 1
    assert canon_issues[0]["hospital_id"] == spike_hospital.id
    unrelated = [i for i in client.get("/quality-alerts/issues", params={
        "month": month, "hospital_id": unrelated_hospital.id,
    }).json()["items"] if i["indicator_code"] == "CANON_OTHER_RATE"]
    assert len(unrelated) == 1, "the unrelated formula alerts on its own merits"


# ── Existing formula identities are preserved (no behavior drift) ──────────

def test_canonical_identity_keeps_the_previous_spec_grouping():
    """The shared identity must group exactly like the old ``_spec_key``.

    ``_spec_key`` used (numerator, denominator, multiplier); the canonical
    identity adds the formula expression and unit scale. For every builtin
    rate these must produce the SAME equivalence classes — otherwise a rate
    that used to be deduplicated would now be scanned twice.
    """
    from app.engine.rate_config import BUILTIN_RATE_SPECS

    old: dict = {}
    new: dict = {}
    for spec in BUILTIN_RATE_SPECS.values():
        old.setdefault(
            (spec.numerator_codes, spec.denominator_codes,
             round(float(spec.rate_multiplier), 6)), set()).add(spec.spec_key)
        new.setdefault(ratio_identity(
            spec.numerator_codes, spec.denominator_codes,
            "/" if spec.denominator_codes else "*",
            spec.rate_multiplier, spec.unit), set()).add(spec.spec_key)
    assert {frozenset(v) for v in old.values()} == {
        frozenset(v) for v in new.values()}


def test_stored_formula_is_the_identity_after_a_definition_edit(
        client, db_session, duplicate_formula_dataset):
    """A later formula edit must not re-file historical alerts."""
    month = duplicate_formula_dataset["scan_month"]
    spike_hospital = duplicate_formula_dataset["hospitals"][0]
    for perspective, formula in (("history", "{QA_NUM} / {QA_DEN} * 100"),
                                 ("all", "{QA_NUM} / {QA_DEN} * 10")):
        db_session.add(QualityAlert(
            hospital_id=spike_hospital.id, month=month, perspective=perspective,
            indicator_code="CANON_RATE", indicator_name="Canonical QA rate",
            formula=formula, unit="%", severity="HIGH", score=0.8,
            method="zscore", current_value=80.0, baseline_value=10.0,
            status="New", active=True,
        ))
    db_session.commit()

    # Both rows share a code but were computed from DIFFERENT formulas, so
    # they are different findings — not one issue with two perspectives.
    issues = [i for i in client.get("/quality-alerts/issues", params={
        "month": month, "hospital_id": spike_hospital.id}).json()["items"]
        if i["indicator_code"] == "CANON_RATE"]
    assert len(issues) == 2
    assert len({i["canonical_key"] for i in issues}) == 2


def test_outlier_candidates_still_pick_one_code_per_formula(db_session):
    codes = {r.code for r in indicator_service.resolve_outlier_candidates(db_session)}
    # The seeded per-site copies of the C-section rate are one candidate.
    assert "sys_zscore_rate_cs" in codes
    assert "sys_clinical_rate_cs" not in codes
    assert "sys_forecast_cs_rate" not in codes
