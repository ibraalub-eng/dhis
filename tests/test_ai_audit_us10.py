"""US-10 AI/ML audit — regression tests for confirmed issues.

Locks the audited behaviors so they cannot silently regress:
- BUG 5: an anomaly explanation must state which component its SHAP attributions
  describe, and that component's score must match the detector's component score
  (not the ensemble score it is attached to).
- BUG 6: AI caches must invalidate when the provider/model changes.
- BUG 7: AI output must be marked as coming from the model or a local fallback.
"""
import json

# ── BUG 5: anomaly explanation must describe the score it is attached to ──


def _sample_hospital_data():
    data = {}
    for i in range(8):
        data[f"Hospital {i}"] = {
            "hospital_id": i,
            "governorate": "Gaza",
            "hospital_type": "general",
            "values": {
                "cs_rate": 25.0 + i * 2,
                "smm_total": 5.0,
                "mat_deaths": 1.0,
                "nd": 2.0,
                "sb": 1.0,
                "preterm": 10.0,
                "lbw": 8.0,
                "total_births": 200.0,
                "high_risk": 15.0,
                "adolescent": 3.0,
            },
        }
    return data


def _anomalies_with_method_scores():
    from app.engine.smart.schemas import SmartAnomalyResult

    return [
        SmartAnomalyResult(
            hospital_name="Hospital 0",
            hospital_id=0,
            governorate="Gaza",
            hospital_type="general",
            anomaly_score=0.8,
            severity="critical",
            is_outlier=True,
            method_scores={
                "isolation_forest": 0.9,
                "lof": 0.7,
                "mahalanobis": 0.6,
                "residual": 0.5,
            },
        ),
    ]


def test_explanation_names_the_explained_component():
    from app.engine.smart.explainability import explain_anomalies

    results = explain_anomalies(
        _anomalies_with_method_scores(), _sample_hospital_data(), {"shap_enabled": True}
    )
    assert len(results) == 1
    assert results[0].explained_component == "isolation_forest"


def test_explained_score_matches_detector_component_not_ensemble():
    from app.engine.smart.explainability import explain_anomalies

    anomalies = _anomalies_with_method_scores()
    exp = explain_anomalies(
        anomalies, _sample_hospital_data(), {"shap_enabled": True}
    )[0]
    assert exp.explained_score == anomalies[0].method_scores["isolation_forest"]
    assert exp.anomaly_score == anomalies[0].anomaly_score


# ── BUG 6: cache keys must invalidate when provider/model changes ──


def test_ai_cache_key_changes_with_model(monkeypatch):
    import app.plugins.ai.cache as cache
    import app.plugins.ai.providers as providers

    monkeypatch.setattr(providers, "AI_MODEL", "model-a")
    key_a = cache._make_cache_key("same prompt")
    monkeypatch.setattr(providers, "AI_MODEL", "model-b")
    key_b = cache._make_cache_key("same prompt")
    assert key_a != key_b


def test_ai_cache_key_changes_with_provider(monkeypatch):
    import app.plugins.ai.cache as cache
    import app.plugins.ai.providers as providers

    monkeypatch.setattr(providers, "AI_PROVIDER", "gemini")
    key_a = cache._make_cache_key("p")
    monkeypatch.setattr(providers, "AI_PROVIDER", "openai")
    key_b = cache._make_cache_key("p")
    assert key_a != key_b


def test_report_cache_key_changes_with_model(monkeypatch):
    import app.engine.comparative.report_cache as report_cache
    import app.plugins.ai.providers as providers

    monkeypatch.setattr(providers, "AI_MODEL", "model-a")
    key_a = report_cache._cache_key("2026-01", "ar")
    monkeypatch.setattr(providers, "AI_MODEL", "model-b")
    key_b = report_cache._cache_key("2026-01", "ar")
    assert key_a != key_b


# ── BUG 7: AI output must be marked ai vs local fallback ──


def test_ai_rule_def_defaults_to_ai_source():
    from app.plugins.ai.providers import AIRuleDef

    rec = AIRuleDef(
        category="c", priority="low", title="t", description="d", rationale="r"
    )
    assert rec.source == "ai"


def test_local_fallbacks_are_marked_local():
    from app.plugins.ai.providers import (
        _local_clinical_fallback,
        _local_root_cause_fallback,
    )

    clinical = _local_clinical_fallback({}, [], None, None, None)
    assert clinical and all(r.source == "local" for r in clinical)

    root_cause = _local_root_cause_fallback({})
    assert root_cause and all(r.source == "local" for r in root_cause)


def test_parse_response_marks_ai_source():
    from app.plugins.ai.providers import _parse_response

    recs = _parse_response(
        json.dumps(
            [
                {
                    "category": "c",
                    "priority": "low",
                    "title": "t",
                    "description": "d",
                    "rationale": "r",
                }
            ]
        )
    )
    assert recs and all(r.source == "ai" for r in recs)


def test_generate_marks_local_when_ai_disabled(monkeypatch):
    import app.plugins.ai as ai_module

    monkeypatch.setattr(ai_module, "AI_ENABLED", False)
    recs = ai_module.generate({}, [], None, None, None)
    assert recs and all(r.source == "local" for r in recs)


def test_executive_summary_exposes_source(monkeypatch):
    import app.plugins.ai as ai_module

    monkeypatch.setattr(ai_module, "AI_ENABLED", False)
    text, source = ai_module.generate_executive_summary_ex(
        "H", "2026-01", {}, 80.0
    )
    assert isinstance(text, str) and text
    assert source == "local"
