# -*- coding: utf-8 -*-
"""Doctrine guard: the covered-by-total / disabled-indicator rules must stay
documented AND implemented in exactly one place.

docs/COVERAGE-DISABLE-DOCTRINE.md is the mandatory developer reference (any
code touching completeness, missing-indicator lists, the Why popup or the
audit screen must apply it). These tests fail if:

  * the doctrine doc disappears or loses its key sections, or
  * the implementation drifts from what the doc promises:
      - compute_covered_codes must accept (values, disabled_codes, db)
      - _iter_sum_rules must include gt/ge_factor (containment sums)
      - find_data_problems must accept db and gate missing_value flags
      - _recalc_completeness must exist as the reference disabled-reading impl

Incidents that produced this doctrine: hospital 5 (مستشفى الخير) month
2026-02 — first 2.n, then 6.g/6.d were flagged "missing" by the Why popup
while completeness forgave them.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "COVERAGE-DISABLE-DOCTRINE.md"
RULES = ROOT / "app" / "engine" / "quality" / "rules.py"
EXPLAIN = ROOT / "app" / "engine" / "audit" / "explain.py"
DASHBOARD = ROOT / "app" / "api" / "dashboard.py"


def test_doctrine_doc_exists_with_key_sections():
    text = DOC.read_text(encoding="utf-8")
    for section in (
        "القاعدة الإلزامية",
        "compute_covered_codes",
        "عقيدتا التغطية",           # eq vs gt/ge_factor doctrines
        "التعطيل من شجرة المؤشرات",  # disabled-from-tree reading rules
        "سجل الحوادث",
        "قائمة تحقق للمطوّر",
    ):
        assert section in text, f"doctrine doc lost section: {section}"


def test_doc_links_from_main_documentation():
    readme = (ROOT / "docs" / "PROJECT_DOCUMENTATION.md").read_text(encoding="utf-8")
    assert "COVERAGE-DISABLE-DOCTRINE.md" in readme, (
        "the main project documentation must point developers at the doctrine"
    )


def test_compute_covered_codes_signature_supports_db():
    src = RULES.read_text(encoding="utf-8")
    assert "def compute_covered_codes(values: Dict[str, float], disabled_codes: set, session: Session = None)" in src


def test_iter_sum_rules_includes_containment_types():
    """gt/ge_factor are containment sums (R080: 6 > 6.d+6.f+6.g) and MUST be
    iterated — skipping them caused the 6.g incident."""
    src = RULES.read_text(encoding="utf-8")
    assert '"gt", "ge_factor"' in src
    assert 'not in ("ge", "eq", "le_sum", "gt", "ge_factor")' in src


def test_containment_doctrine_implemented():
    src = RULES.read_text(encoding="utf-8")
    fn = src[src.index("def compute_covered_codes"):]
    fn = fn[:fn.index("\ndef ", 10)]
    # containment branch + overflow guard
    assert 'op in ("gt", "ge", "ge_factor")' in fn
    assert "cs <= pv + tolerance" in fn


def test_find_data_problems_applies_coverage_gate():
    src = EXPLAIN.read_text(encoding="utf-8")
    assert "def find_data_problems(values: list, db: Session = None)" in src
    fn = src[src.index("def find_data_problems"):]
    fn = fn[:fn.index("\ndef ", 10)]
    assert "compute_covered_codes" in fn
    # the missing_value branch must skip covered codes
    assert "if v[\"code\"] in covered_codes:" in fn


def test_explain_callers_pass_db():
    src = EXPLAIN.read_text(encoding="utf-8")
    assert "find_data_problems(values, db)" in src, (
        "all explain call sites must pass db so rules come from the database"
    )


def test_recalc_completeness_reference_impl_exists():
    """dashboard._recalc_completeness is the reference for reading disabled
    indicators (manual + per-month default + overrides + auto-disable)."""
    src = DASHBOARD.read_text(encoding="utf-8")
    assert "def _recalc_completeness(db, scores)" in src
    for marker in (
        "HospitalIndicatorConfig",
        "IndicatorDefaultConfig",
        "auto_disable_null_indicators",
        "compute_covered_codes",
    ):
        assert marker in src, f"reference impl lost: {marker}"


def test_doctrine_referenced_in_glossary():
    glossary = (ROOT / "docs" / "ARABIC-TERMINOLOGY.md").read_text(encoding="utf-8")
    assert "COVERAGE-DISABLE-DOCTRINE.md" in glossary
