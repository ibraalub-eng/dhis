"""Indicator code "0" ("Main elements complete ratio") is a synthetic tree
label, not a data indicator. Disabling it in the tree config — and even its
mere existence — must never affect rule validation details, audit
(deduction) listings, upload templates, or manual data-entry options.

Regression for the garbled rule details like:
    "Antepartum hemorrhage=12.Main elements complete ratio > Hemorrhage=2.Main ele"
which happened because the details resolver treated the decimal fraction of
"12.0" as indicator code "0" and replaced it with the label's name.
"""

from pathlib import Path

import pytest

from app.engine.pipeline import _build_code_resolver
from app.indicators import SYNTHETIC_INDICATOR_CODES
from app.models import Hospital, Indicator, IndicatorDefaultConfig, IndicatorValue


# ── Rule-detail code resolver ────────────────────────────────────────

def _resolver():
    return _build_code_resolver({
        "10.a.2": "Antepartum hemorrhage",
        "10.a": "Hemorrhage",
        "2": "Total Deliveries",
    })


def test_resolver_leaves_decimal_values_alone():
    """"12.0" and "2.0" are numbers, not codes — the fraction must never be
    resolved into "Main elements complete ratio" (or any other name)."""
    resolve = _resolver()
    out = resolve("10.a.2=12.0 > 10.a=2.0")
    assert out == "Antepartum hemorrhage=12.0 > Hemorrhage=2.0"


def test_resolver_never_produces_synthetic_label():
    resolve = _resolver()
    out = resolve("child code 2 reported 0 cases; value=2.0")
    assert "Main elements complete ratio" not in out
    assert out == "child code Total Deliveries reported 0 cases; value=2.0"


def test_resolver_still_prettifies_real_codes():
    resolve = _resolver()
    assert resolve("10.a.2 exceeds 10.a") == "Antepartum hemorrhage exceeds Hemorrhage"
    assert resolve("2 vs 10.a") == "Total Deliveries vs Hemorrhage"


def test_resolver_returns_none_without_codes():
    assert _build_code_resolver({}) is None


def test_synthetic_codes_constant():
    assert SYNTHETIC_INDICATOR_CODES == {"0"}


# ── Audit (deductions) listing ───────────────────────────────────────

def _add_value(db_session, hospital, code, month, value):
    ind = db_session.query(Indicator).filter(Indicator.code == code).first()
    db_session.add(IndicatorValue(
        hospital_id=hospital.id, indicator_id=ind.id, month=month, value=value,
    ))
    return ind


def _audit_codes(db_session, hospital_id, month):
    from app.engine.audit.data_auditor import get_data_audit
    audit = get_data_audit(db_session, hospital_id, month)
    comp = audit["completeness"]
    return comp, [row["indicator_code"] for row in comp["indicators"]]


def test_audit_excludes_synthetic_ratio_even_when_present(db_session):
    """A stored value for "0" must not turn it into an audit row."""
    h = db_session.query(Hospital).first()
    _add_value(db_session, h, "0", "2026-08", 88.5)
    _add_value(db_session, h, "2", "2026-08", 120)
    db_session.commit()

    comp, codes = _audit_codes(db_session, h.id, "2026-08")
    assert "0" not in codes
    assert "2" in codes
    assert comp["total"] == comp["present"] + comp["covered"] + comp["missing"]


def test_audit_excludes_indicators_disabled_in_tree_config(db_session):
    """Disabling an indicator (here "0" and "3") via the All-Hospitals tree
    config removes it from the audit list and the counts entirely."""
    h = db_session.query(Hospital).first()
    zero = db_session.query(Indicator).filter(Indicator.code == "0").first()
    ind3 = db_session.query(Indicator).filter(Indicator.code == "3").first()
    db_session.add(IndicatorDefaultConfig(
        indicator_id=zero.id, month="2026-08", is_enabled=False,
    ))
    db_session.add(IndicatorDefaultConfig(
        indicator_id=ind3.id, month="2026-08", is_enabled=False,
    ))
    _add_value(db_session, h, "0", "2026-08", 88.5)
    _add_value(db_session, h, "2", "2026-08", 120)
    db_session.commit()

    comp, codes = _audit_codes(db_session, h.id, "2026-08")
    assert "0" not in codes
    assert "3" not in codes
    assert "2" in codes
    assert comp["total"] == comp["present"] + comp["covered"] + comp["missing"]


# ── Upload template + manual data-entry options ─────────────────────

def test_upload_template_and_data_entry_exclude_synthetic():
    """Both top-level indicator lists in upload.py (Excel template columns and
    data-entry options) must filter out synthetic entries like "0"."""
    src = (Path(__file__).resolve().parent.parent / "app" / "api" / "upload.py").read_text(encoding="utf-8")
    assert src.count('not in SYNTHETIC_INDICATOR_CODES') == 2, (
        "download_template and data_entry_options must both exclude synthetic indicator codes"
    )
