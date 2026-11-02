"""Cross-module severity contract.

The audit in ``docs/SEVERITY-AUDIT.md`` found no double counting inside any one
surface: every severity distribution sums to its own total. What made counts look
wrong was **five different vocabularies** and counts quoted in different units
beside each other. These tests pin the parts that must never drift again without a
deliberate, reviewed change:

* one band scale, one set of cutoffs (``layered.BAND_CUTOFFS``) — moving a
  threshold is a policy decision, not a refactor;
* Quality Alerts speaks the canonical scale (minus ``NONE``);
* every other engine vocabulary normalizes through ``engine.severity``;
* the vocabularies that are NOT severity (confidence, action severity) stay
  visibly separate.
"""
import re
from pathlib import Path

from app.engine import severity as severity_policy
from app.engine.anomaly import layered
from app.engine.quality.rules import Severity as RuleSeverity
from app.models import QUALITY_ALERT_SEVERITIES

ROOT = Path(__file__).resolve().parent.parent


def test_canonical_scale_is_the_only_band_scale():
    """One scale, one cutoff table — the audit's central requirement.

    ``layered.BAND_CUTOFFS`` is the authority for detection. If a second module
    ever defines its own cutoffs, two screens can grade the same score into
    different bands, which is how the original mismatch started.
    """
    assert layered.LEVELS == severity_policy.LEVELS
    assert layered.LEVEL_RANK == severity_policy.LEVEL_RANK
    assert [(bound, name) for bound, name in layered.BAND_CUTOFFS] == [
        (0.25, "NONE"), (0.50, "LOW"), (0.75, "MODERATE"),
        (0.90, "HIGH"), (layered.math.inf, "VERY_HIGH"),
    ], "band cutoffs changed: this is a policy decision and needs approval"

    definitions = []
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # `BAND_CUTOFFS: Tuple[...] = (` is the annotated form; match both.
        if re.search(r"BAND_CUTOFFS\s*(?::[^=]+)?=\s*\(", text):
            definitions.append(path.name)
    assert definitions == ["layered.py"], (
        f"a second band-cutoff table appeared: {definitions}")


def test_quality_alert_bands_are_canonical_minus_none():
    """Quality Alerts stores findings only, so it has no NORMAL/NONE band."""
    assert QUALITY_ALERT_SEVERITIES == tuple(
        level for level in severity_policy.LEVELS if level != "NONE")


def test_engine_vocabularies_normalize_to_canonical():
    """The rule engine's four words mean four bands, and never more."""
    expected = {
        "CRITICAL": "VERY_HIGH",   # top band, different name
        "HIGH": "HIGH",
        "MEDIUM": "MODERATE",      # MEDIUM is the middle band, not a 5th level
        "LOW": "LOW",
    }
    for engine_level in RuleSeverity:
        normalized = severity_policy.normalize_severity(
            engine_level.value, source=severity_policy.SOURCE_CLINICAL_RULE)
        assert normalized.level == expected[engine_level.value]
        assert normalized.engine_level == engine_level.value, \
            "normalization must preserve what the engine actually said"


def test_action_vocabulary_is_not_yet_normalizable():
    """Known gap, pinned so it cannot be mistaken for a mapped vocabulary.

    Smart Analytics uses ``critical / warning / normal / info`` for recommended
    actions. ``critical`` and ``info`` normalize today; ``warning`` has no band,
    so a screen that summed it into a severity count would have to invent one.
    The audit proposes mapping it in P1 — until then this stays explicit.
    """
    assert severity_policy.try_normalize_severity(
        "critical", source=severity_policy.SOURCE_TEMPORAL_TREND).level == "VERY_HIGH"
    assert severity_policy.try_normalize_severity(
        "info", source=severity_policy.SOURCE_TEMPORAL_TREND).level == "NONE"
    assert severity_policy.try_normalize_severity(
        "warning", source=severity_policy.SOURCE_TEMPORAL_TREND) is None


def test_confidence_levels_are_a_separate_dimension():
    """Confidence reuses CRITICAL/HIGH/MEDIUM/LOW with a different meaning.

    The dashboard's confidence donut and the Alerts severity bar therefore use
    the same four words and the same colours for different things. Nothing may
    sum one into the other; this test records the collision as intentional.
    """
    from app.engine.confidence import _build_summary  # noqa: F401  (import check)
    from app.models import ConfidenceScore

    assert ConfidenceScore.__table__.c.level.type.length == 20
    text = (ROOT / "app" / "api" / "dashboard.py").read_text(encoding="utf-8")
    assert '"confidence_distribution": dist_map' in text, \
        "confidence must stay published under its own name, never as severity"


def test_units_are_named_in_the_quality_alert_payload():
    """Row counts and issue counts must never share one ambiguous name.

    ``by_severity`` counts perspective ROWS while ``total_issues`` counts grouped
    issues: on the live store 5,043 rows sit beside 2,658 issues. The API keeps
    both, so every consumer has to be able to tell them apart by name.
    """
    src = (ROOT / "app" / "api" / "quality_alerts.py").read_text(encoding="utf-8")
    for key in ('"total_active"', '"very_high_rows"', '"total_issues"',
                '"very_high_issues"', '"very_high_only_issues"',
                '"mixed_severity_issues"'):
        assert f"{key}:" in src, f"missing unit-named count {key}"
    # The ambiguous `red_*` aliases must not come back: one band, one name.
    for legacy in ('"red_alerts"', '"red_issues"', '"red_only_issues"'):
        assert legacy not in src
