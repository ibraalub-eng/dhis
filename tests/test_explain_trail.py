"""Tests for the US-11 unified audit trail (trail + 8-stage chain)."""
from app.engine.audit.explain import (
    _bilingual,
    _chain_from_trail,
    _deep_link,
    _evidence_item,
    _na_stage,
    _stage,
)


def test_bilingual_equal_returns_string():
    assert _bilingual("A", "A") == "A"


def test_bilingual_diff_returns_dict():
    assert _bilingual("\u0623", "A") == {"ar": "\u0623", "en": "A"}


def test_na_stage_carries_reason_and_status():
    st = _na_stage("root_cause", 5, "\u0627\u0644\u0633\u0628\u0628", "Root Cause", "\u0644\u0627", "No")
    assert st["status"] == "na"
    assert st["key"] == "root_cause"
    assert st["order"] == 5
    assert st["detail"] is None
    assert st["na_reason"] == {"ar": "\u0644\u0627", "en": "No"}


def test_evidence_item_optional_unit():
    assert _evidence_item("Effort AR", "Effort", "low") == {
        "label_ar": "Effort AR", "label_en": "Effort", "value": "low",
    }
    assert _evidence_item("p", "Points", 3, unit="quality points")["unit"] == "quality points"


def test_deep_link_builds_endpoint_and_hash():
    assert _deep_link(endpoint="/x") == {"endpoint": "/x"}
    assert _deep_link(hash_="audit?mode=trail") == {"hash": "audit?mode=trail"}
    assert _deep_link() is None


def test_chain_from_trail_uses_legacy_step_names_and_english_detail():
    trail = [
        _stage("raw_data", 1, "\u0623", "12 indicator values"),
        _stage("validation", 2, "\u0628", "none failed"),
        _stage("issue", 3, "\u062c", "issue"),
        _stage("evidence", 4, "\u062f", "evidence"),
        _stage("root_cause", 5, "\u0647", "rc"),
        _stage("impact", 6, "\u0648", "impact"),
        _stage("recommendation", 7, "\u0632", "rec"),
        _stage("action", 8, "\u062d", "act"),
    ]
    chain = _chain_from_trail(trail)
    assert len(chain) == 8
    assert chain[0]["step"] == "Source Data"
    assert chain[1]["step"] == "Validation"
    assert chain[2]["step"] == "Issue"
    assert chain[0]["detail"] == "12 indicator values"
    assert chain[0]["key"] == "raw_data"


from app.engine.audit.explain import (
    _action_from_narrowed,
    _impact_from_narrowed,
    _narrow_root_cause,
    _recommendation_from_narrowed,
)
from app.engine.root_cause import (
    CausalChain,
    PriorityActionDetail,
    QualityDriver,
    RootCauseReport,
    RuleFailurePattern,
)


def _sample_report():
    return RootCauseReport(
        hospital="General Hospital", hospital_id=1, month="2026-04",
        overall_quality_score=60.0, overall_confidence=50.0, critical_issues_count=1,
        top_rule_failures=[RuleFailurePattern(
            rule_code="R001", rule_description="deliveries total", severity="HIGH",
            failure_count=3, total_runs=4, failure_rate=75.0,
            primary_cause="totals mismatch", recommendation="reconcile totals",
            primary_cause_ar="\u0639\u062f\u0645 \u062a\u0637\u0627\u0628\u0642",
        )],
        quality_drivers=[QualityDriver(
            component="completeness", value=40.0, weight=0.25, impact=15.0,
            status="needs_improvement", recommendation="improve completeness",
        )],
        confidence_gaps=[], anomaly_patterns=[],
        summary="s", priority_actions=["reconcile totals"],
        priority_action_details=[PriorityActionDetail(
            action="Reconcile delivery totals for R001", source="rule",
            severity="HIGH", impact=12.0, effort=2, roi=6.0,
        )],
        causal_chains=[CausalChain(
            root_cause="R001 failing at 75%", root_cause_arabic="\u0641\u0634\u0644 R001",
            confidence=0.8, evidence=["e"], affected_factors=["R001"],
            recommended_action="Repair totals", impact_if_fixed=12.0,
            implementation_priority="HIGH", chain_path=["R001"],
            chain_path_arabic="R001",
        )],
    )


def test_narrow_rule_matches_by_rule_code():
    n = _narrow_root_cause(_sample_report(), "rule", rule_code="R001")
    assert n["rule_fail"].rule_code == "R001"
    assert n["chain"] is not None
    assert n["general"] is False


def test_narrow_quality_score_matches_component_driver():
    n = _narrow_root_cause(_sample_report(), "quality_score", component="completeness")
    assert n["qdriver"].component == "completeness"
    assert n["general"] is False


def test_narrow_unknown_falls_back_to_general_chain():
    n = _narrow_root_cause(_sample_report(), "anomaly", rate_name="No Such Rate")
    assert n["general"] is True
    assert n["chain"] is not None  # top chain reused as general context


def test_impact_quantified_from_chain():
    n = _narrow_root_cause(_sample_report(), "rule", rule_code="R001")
    imp = _impact_from_narrowed(n)
    assert imp["quantified"] is True
    assert imp["value"] == 12.0
    assert imp["unit"] == "quality points"


def test_recommendation_prefers_causal_chain():
    n = _narrow_root_cause(_sample_report(), "rule", rule_code="R001")
    rec = _recommendation_from_narrowed(n, "rule")
    assert rec["en"] == "Repair totals"
    assert rec["source"] == "causal_chain"


def test_action_prefers_priority_action_detail():
    n = _narrow_root_cause(_sample_report(), "rule", rule_code="R001")
    act = _action_from_narrowed(n, "rule")
    assert act["en"] == "Reconcile delivery totals for R001"
    assert act["effort"] == 2 and act["roi"] == 6.0


def test_load_root_cause_cached_calls_once(monkeypatch, db_session):
    from app.engine.audit import explain
    from app.models import ConfidenceScore, QualityScore

    db_session.add(QualityScore(
        hospital_id=1, month="2026-04", score=50.0,
        rule_compliance=50.0, completeness=50.0, consistency=50.0, outlier_penalty=0.0,
    ))
    db_session.add(ConfidenceScore(
        hospital_id=1, month="2026-04", overall_confidence=50.0, level="MEDIUM",
    ))
    db_session.commit()

    calls = {"n": 0}

    def fake_generate(session, hid, month, **kwargs):
        calls["n"] += 1
        return None

    monkeypatch.setattr("app.engine.root_cause.generate_root_cause_analysis", fake_generate)
    cache = {}
    explain._load_root_cause_cached(db_session, 1, "2026-04", cache)
    explain._load_root_cause_cached(db_session, 1, "2026-04", cache)
    assert calls["n"] == 1


from app.engine.audit.explain import (
    _evidence_stage,
    _issue_stage,
    _raw_data_stage,
    _validation_stage,
)


def test_raw_data_stage_for_anomaly_names_the_indicator(db_session):
    payload = {
        "kind": "anomaly", "month": "2026-04", "hospital_id": 1,
        "where": {"indicator_name": "Caesarean Sections", "source_files": ["upload.xlsx"]},
    }
    st = _raw_data_stage(db_session, 1, "2026-04", "anomaly", payload)
    assert st["key"] == "raw_data"
    assert "Caesarean Sections" in st["detail"] or "Caesarean Sections" in st["detail"]["en"]
    assert st["deep_link"]["endpoint"] == "/audit/data-auditor/1"


def test_validation_stage_names_failed_rule_codes():
    payload = {"failed_rules": [
        {"rule_code": "R_TEST", "severity": "HIGH"},
        {"rule_code": "R_OTHER", "severity": "LOW"},
    ]}
    st = _validation_stage(None, 1, "2026-04", "quality_score", payload)
    detail = st["detail"] if isinstance(st["detail"], str) else st["detail"]["en"]
    assert "R_TEST" in detail
    assert st["status"] == "has_content"


def test_issue_stage_is_always_content():
    st = _issue_stage("quality_score", {"what": "Score 42 for 2026-04"})
    assert st["status"] == "has_content"
    assert st["key"] == "issue"


def test_layered_evidence_stage_links_analysis_view():
    st = _evidence_stage(None, 1, "2026-04", "layered_outlier", {"reproduce": {}})
    assert st["deep_link"]["endpoint"] == "/analysis/layered"


from app.engine.audit.explain import _build_issue_trail, _root_cause_stages


def test_root_cause_stages_are_na_without_report(monkeypatch, db_session):
    from app.engine.audit import explain

    monkeypatch.setattr(explain, "_load_root_cause_cached",
                        lambda db, hid, month, cache: None)
    stages = _root_cause_stages(
        db_session, 1, "2026-04", "quality_score",
        None, None, None, "completeness", {}, {},
    )
    assert [s["key"] for s in stages] == ["root_cause", "impact", "recommendation", "action"]
    assert all(s["status"] == "na" for s in stages)
    assert all(s["na_reason"]["ar"] and s["na_reason"]["en"] for s in stages)


def test_root_cause_stages_use_narrowed_chain(monkeypatch, db_session):
    from app.engine.audit import explain

    monkeypatch.setattr(explain, "_load_root_cause_cached",
                        lambda db, hid, month, cache: _sample_report())
    stages = _root_cause_stages(
        db_session, 1, "2026-04", "rule", None, "R001", None, None, {}, {},
    )
    assert stages[0]["key"] == "root_cause"
    assert stages[0]["status"] == "has_content"
    assert stages[0]["deep_link"]["endpoint"] == "/root-cause/1"
    assert stages[1]["key"] == "impact"
    assert stages[2]["detail"]["en"] == "Repair totals"
    assert stages[3]["evidence_items"][0]["value"] == 2  # effort


def test_build_issue_trail_has_eight_ordered_stages(monkeypatch, db_session):
    from app.engine.audit import explain

    monkeypatch.setattr(explain, "_load_root_cause_cached",
                        lambda db, hid, month, cache: _sample_report())
    trail = _build_issue_trail(
        db_session, 1, "2026-04", "rule", None, "R001", None, None,
        {"kind": "rule", "what": "R001 failed", "failed_rules": [{"rule_code": "R001"}]},
        {},
    )
    assert [s["key"] for s in trail] == [
        "raw_data", "validation", "issue", "evidence",
        "root_cause", "impact", "recommendation", "action",
    ]
    assert [s["order"] for s in trail] == [1, 2, 3, 4, 5, 6, 7, 8]
