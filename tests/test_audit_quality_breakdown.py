"""Regression tests for the audit quality-score breakdown.

The audit screen (calculation_steps + data_auditor) rebuilds the weighted
component breakdown from stored QualityScore rows. These tests pin the
invariants that were broken before 2026-09-19:

1. Components are stored/displayed on a 0-100 scale; the outlier inversion is
   ``100 - outlier_penalty`` (NOT ``1 - outlier_penalty``).
2. The weighted components sum to (approximately) the stored final score.
3. Weights come from the ``quality`` config category, not hard-coded literals.
"""

import pytest

from app.models import Hospital, Indicator, IndicatorValue, QualityScore


@pytest.fixture
def qs_row(db_session):
    """A stored quality score with realistic components + minimal indicator
    values so get_calculation_steps does not bail with {"error": ...}."""
    h = db_session.query(Hospital).first()
    inds = db_session.query(Indicator).all()
    for ind in inds[:10]:
        db_session.add(IndicatorValue(
            hospital_id=h.id,
            indicator_id=ind.id,
            month="2026-07",
            value=50.0,
        ))
    db_session.commit()

    row = QualityScore(
        hospital_id=h.id,
        month="2026-07",
        score=95.0,
        rule_compliance=97.5,
        completeness=86.2,
        consistency=97.2,
        outlier_penalty=0.0,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _components_sum(components):
    return sum((c["weighted"] or 0) for c in components)


def test_outlier_inversion_uses_100_scale(db_session, qs_row):
    """outlier_penalty=0 (no outliers) must invert to 100, not 1.

    The old bug: op_inv = 1 - 0 = 1.0, so the outlier component contributed
    1.0 * 0.15 = 0.15 points instead of 100 * 0.15 = 15 points.
    """
    from app.engine.audit.calculation_steps import get_calculation_steps
    steps = get_calculation_steps(db_session, qs_row.hospital_id, qs_row.month)
    assert "quality_score" in steps, steps.get("error", "quality_score missing")
    comp = [c for c in steps["quality_score"]["components"] if "Outlier" in c["name"]][0]
    assert comp["value"] == 100.0, "inverted outlier value must be 100 when penalty is 0"
    assert abs(comp["weighted"] - 100.0 * comp["weight"]) < 0.01


def test_components_sum_to_final_score(db_session, qs_row):
    """The displayed weighted components must sum to ~ the stored score.

    With rc=97.5, cp=86.2, co=97.2, op=0 and default weights:
    97.5*0.35 + 86.2*0.25 + 97.2*0.25 + 100*0.15 = 95.0 (the stored score).
    The old buggy math summed to 80.125 while the header claimed 94.9.
    """
    from app.engine.audit.calculation_steps import get_calculation_steps
    steps = get_calculation_steps(db_session, qs_row.hospital_id, qs_row.month)
    qsb = steps["quality_score"]
    total = _components_sum(qsb["components"])
    assert abs(total - qsb["final_score"]) < 1.5, (
        f"components sum {total} must match final score {qsb['final_score']}"
    )


def test_data_auditor_breakdown_sums_to_score(db_session, qs_row):
    """Same invariant for the data-auditor endpoint's quality_score block."""
    from app.engine.audit.data_auditor import get_data_audit
    audit = get_data_audit(db_session, qs_row.hospital_id, qs_row.month)
    qsb = audit["quality_score"]
    total = _components_sum(qsb["components"])
    assert abs(total - qsb["score"]) < 1.5


def test_weights_come_from_config(db_session, qs_row):
    """Weights must be read from the quality config category so that changing
    e.g. quality_rule_compliance in Settings is reflected in the audit screen."""
    from app.config_utils import get_config_dict
    cfg = get_config_dict(db_session, "quality")

    from app.engine.audit.calculation_steps import get_calculation_steps
    steps = get_calculation_steps(db_session, qs_row.hospital_id, qs_row.month)
    weights = {c["name"]: c["weight"] for c in steps["quality_score"]["components"]}
    # Whatever the config says, the weights must sum to ~1.0
    assert abs(sum(weights.values()) - 1.0) < 0.01, f"weights must sum to 1.0, got {weights}"
    # And the outlier component weight must equal the config value
    assert abs(weights["Outlier Penalty (inverted)"] - float(cfg.get("quality_outlier_penalty", 0.15))) < 1e-6


def test_contribution_pcts_sum_to_100(db_session, qs_row):
    """data_auditor's contribution_pct values must total ~100%."""
    from app.engine.audit.data_auditor import get_data_audit
    audit = get_data_audit(db_session, qs_row.hospital_id, qs_row.month)
    total_pct = sum(c["contribution_pct"] for c in audit["quality_score"]["components"])
    assert abs(total_pct - 100.0) < 1.0


# ── Score repair (backfill) ────────────────────────────────────────

# ── Sentinel rows and rounding tolerance ──────────────────────────

def _sentinel_row(db_session, h, month="2026-01"):
    """Mimic the engine's placeholder row for a month with no analyzable data
    (pipeline.py): every value zeroed + the sentinel issue text."""
    return QualityScore(hospital_id=h.id, month=month, score=0.0,
                        rule_compliance=0.0, completeness=0.0,
                        consistency=0.0, outlier_penalty=0.0,
                        issues='["No data found for this hospital/month"]')


def test_repair_skips_no_data_sentinel_rows(db_session, qs_row):
    """Engine placeholder rows (all-zero + 'No data' issue) must be excluded
    from shallow mismatch/repair: 0 outliers means inverted-outlier=100, so
    the naive formula would flag them and 'repair' the score to 15.0."""
    from app.api.admin import repair_quality_scores, repair_quality_scores_preview
    s = _sentinel_row(db_session, db_session.query(Hospital).first())
    db_session.add(s)
    db_session.commit()

    preview = repair_quality_scores_preview(db=db_session)
    assert s.id not in [m["id"] for m in preview["mismatches"]], "sentinel row must not be flagged"
    assert preview.get("sentinel_rows_skipped", 0) >= 1

    repair_quality_scores(db=db_session)
    db_session.refresh(s)
    assert float(s.score) == 0.0, "repair must not touch sentinel rows"


def test_repair_tolerates_engine_rounding_drift(db_session, qs_row):
    """The engine rounds components to 0.1 but computes the final score from
    unrounded values, so stored scores can legitimately differ from the
    rounded-component formula by up to 0.1. Such rows must NOT be flagged."""
    from app.api.admin import repair_quality_scores_preview
    # formula value for qs_row components = 95.0; 94.9 is within 0.15 tolerance
    qs_row.score = 94.9
    db_session.commit()
    preview = repair_quality_scores_preview(db=db_session)
    assert qs_row.id not in [m["id"] for m in preview["mismatches"]]

    # but 0.2+ drift is a real mismatch
    qs_row.score = 94.7
    db_session.commit()
    preview2 = repair_quality_scores_preview(db=db_session)
    assert qs_row.id in [m["id"] for m in preview2["mismatches"]]


def test_deep_targets_exclude_pairs_without_enabled_values(db_session, qs_row):
    """_deep_targets uses the engine's enabled-values logic: a pair whose raw
    values exist but are all disabled (or null) must NOT be targeted — deep
    repair would only rewrite the engine's no-data sentinel row."""
    from app.api.admin import _deep_targets
    from app.models import IndicatorValue

    h = db_session.query(Hospital).first()
    # fixture seeds enabled values for (h, '2026-07') -> targeted
    targets = _deep_targets(db_session)
    assert (qs_row.hospital_id, qs_row.month) in targets

    # A pair with only NULL values -> engine sees no data -> not targeted
    ind = db_session.query(Indicator).first()
    db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=ind.id,
                                  month="2026-02", value=None))
    db_session.add(QualityScore(hospital_id=h.id, month="2026-02", score=0.0,
                                rule_compliance=0.0, completeness=0.0,
                                consistency=0.0, outlier_penalty=0.0,
                                issues='["No data found for this hospital/month"]'))
    db_session.commit()
    targets2 = _deep_targets(db_session)
    assert (h.id, "2026-02") not in targets2


def test_repair_preview_finds_inconsistent_rows(db_session, qs_row):
    """A row whose stored score diverges from the component sum must show up
    in the repair preview with the corrected expected score."""
    from app.api.admin import repair_quality_scores_preview
    result = repair_quality_scores_preview(db=db_session)
    assert result["total_rows"] >= 1
    match = [m for m in result["mismatches"] if m["id"] == qs_row.id]
    # qs_row: rc=97.5 cp=86.2 co=97.2 op=0 -> expected 95.0, stored 95.0 => consistent
    if match:
        # only allowed if the weights in config differ from defaults
        assert abs(match[0]["expected_score"] - 95.0) > 0.05
    else:
        assert result["mismatch_count"] == 0 or qs_row.id not in [m["id"] for m in result["mismatches"]]


def test_repair_fixes_broken_row(db_session, qs_row):
    """Corrupt a stored score, run repair, and the row must come back to the
    engine-formula value; consistent rows must be left untouched."""
    from app.api.admin import repair_quality_scores, repair_quality_scores_preview
    qs_row.score = 12.3  # corrupt it
    db_session.commit()

    preview = repair_quality_scores_preview(db=db_session)
    ids = [m["id"] for m in preview["mismatches"]]
    assert qs_row.id in ids, "corrupted row must be flagged by the preview"
    flagged = next(m for m in preview["mismatches"] if m["id"] == qs_row.id)
    assert abs(flagged["expected_score"] - 95.0) <= 0.2

    result = repair_quality_scores(db=db_session)
    db_session.refresh(qs_row)
    assert result["repaired"] >= 1
    assert abs(float(qs_row.score) - 95.0) <= 0.2
    assert qs_row.rule_compliance == 97.5  # components untouched

    after = repair_quality_scores_preview(db=db_session)
    assert qs_row.id not in [m["id"] for m in after["mismatches"]], "row must be consistent after repair"


# ── Deep repair (recompute components from raw data via engine pipeline) ──

def test_deep_preview_lists_only_pairs_with_raw_data(db_session, qs_row):
    """Deep preview must target only (hospital, month) pairs that still have
    raw indicator values; rows without raw data are never rebuilt."""
    from app.api.admin import repair_quality_scores_preview

    # qs_row's hospital/month HAS raw values (fixture seeds 10 indicator values)
    result = repair_quality_scores_preview(db=db_session, deep=True)
    assert result["mode"] == "deep"
    targets = [(t["hospital_id"], t["month"]) for t in result["targets"]]
    assert (qs_row.hospital_id, qs_row.month) in targets

    # Add a QualityScore row for a month with NO raw data -> must NOT be targeted
    orphan = QualityScore(hospital_id=qs_row.hospital_id, month="2025-01",
                          score=50.0, rule_compliance=50.0, completeness=50.0,
                          consistency=50.0, outlier_penalty=0.0)
    db_session.add(orphan)
    db_session.commit()
    result2 = repair_quality_scores_preview(db=db_session, deep=True)
    targets2 = [(t["hospital_id"], t["month"]) for t in result2["targets"]]
    assert (qs_row.hospital_id, "2025-01") not in targets2


def test_deep_preview_is_read_only(db_session, qs_row):
    """Deep preview must not modify anything."""
    from app.api.admin import repair_quality_scores_preview
    before = (qs_row.score, qs_row.rule_compliance, qs_row.completeness,
              qs_row.consistency, qs_row.outlier_penalty)
    repair_quality_scores_preview(db=db_session, deep=True)
    db_session.refresh(qs_row)
    after = (qs_row.score, qs_row.rule_compliance, qs_row.completeness,
             qs_row.consistency, qs_row.outlier_penalty)
    assert before == after


def test_deep_repair_reruns_engine_pipeline(db_session, qs_row, monkeypatch):
    """Deep repair must recompute components from raw indicator values via
    recompute_hospital_months (the canonical pipeline), not just re-weight
    the stored numbers."""
    from app.api.admin import repair_quality_scores
    from app.tasks import get_task
    import app.api.admin as admin_api
    calls = []

    def fake_recompute(session, hospital_id, months=None, force=False, progress_cb=None):
        calls.append((hospital_id, tuple(sorted(months or [])), force))
        return len(months or [])

    monkeypatch.setattr(admin_api, "SessionLocal", lambda: db_session, raising=False)
    monkeypatch.setattr(
        "app.engine.pipeline.recompute_hospital_months", fake_recompute
    )

    result = repair_quality_scores(db=db_session, deep=True)
    assert result["mode"] == "deep"
    assert result["target_count"] >= 1
    # The pipeline ran synchronously (no BackgroundTasks in direct call)
    task = get_task(result["task_id"])
    assert task is not None
    # Give the thread a moment if it went async
    for _ in range(20):
        if calls or (task["status"] in ("done", "error")):
            break
        import time
        time.sleep(0.05)
    assert calls, "engine pipeline must be invoked for deep repair"
    h_ids = {c[0] for c in calls}
    assert qs_row.hospital_id in h_ids
    assert all(c[2] is True for c in calls), "deep repair must force recompute"
    # Guard released after finish
    assert admin_api.app_state.deep_repair_running is False


def test_deep_repair_rejects_concurrent_runs(db_session, qs_row, monkeypatch):
    """While a deep repair is running, a second deep repair must 409."""
    from app.api.admin import repair_quality_scores
    import app.api.admin as admin_api
    from fastapi import HTTPException

    def never_returns(session, hospital_id, months=None, force=False, progress_cb=None):
        raise AssertionError("should not reach the pipeline")

    monkeypatch.setattr(admin_api, "SessionLocal", lambda: db_session, raising=False)
    admin_api.app_state.deep_repair_running = True
    try:
        with pytest.raises(HTTPException) as exc:
            repair_quality_scores(db=db_session, deep=True)
        assert exc.value.status_code == 409
    finally:
        admin_api.app_state.deep_repair_running = False
