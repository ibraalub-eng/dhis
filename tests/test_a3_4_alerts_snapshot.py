"""A3.4 — ``alerts.auto_scan`` is consumed from the run's PolicySnapshot.

The flag travels as a resolved Boolean through
``run_full_analysis -> _maybe_auto_scan_quality_alerts``; the consumer never
reads AppConfig, so the analysis and the scan it triggers cannot disagree.
"""
from __future__ import annotations

import dataclasses
import inspect
import pathlib
import threading
from types import MappingProxyType

import pytest

from app.engine import config_resolver as cr
from app.engine import pipeline, quality_alerts
from app.models import AppConfig, Hospital, Indicator, IndicatorValue

MONTH = "2031-01"
MONTH_B = "2031-02"
ROOT = pathlib.Path(__file__).resolve().parents[1]

OFF_SPELLINGS = ("0", "0.0", "false", "False", "off")
ON_SPELLINGS = ("1", "1.0", "on", "true", "yes", 2)


def _seed_month(db, month=MONTH, hospital=None):
    """One analysable hospital/month, so the run reaches the auto-scan."""
    hospital = hospital or db.query(Hospital).first()
    for code, value in (("2", 320.0), ("3", 210.0)):
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if indicator is None:
            continue
        db.add(IndicatorValue(hospital_id=hospital.id,
                              indicator_id=indicator.id,
                              month=month, value=value))
    db.commit()
    return hospital


def _set_auto_scan(db, value):
    row = db.query(AppConfig).filter(AppConfig.key == "alerts_auto_scan").first()
    if row is None:
        db.add(AppConfig(key="alerts_auto_scan", value=value,
                         category="alerts", label="auto-scan"))
    else:
        row.value = value
    db.commit()


def _recorder(calls):
    def fake_scan(db, month, hospital_id=None, indicator_codes=None,
                  policy=None):
        calls.append((month, policy))
        return {"created": 0, "updated": 0, "deactivated": 0}
    return fake_scan


# ── 1. the established default is preserved ────────────────────────────────
def test_missing_setting_defaults_to_on_and_scans(db_session, monkeypatch):
    assert db_session.query(AppConfig).filter(
        AppConfig.key == "alerts_auto_scan").count() == 0

    snapshot = cr.load_policy_snapshot(db_session)
    assert snapshot.alerts_auto_scan is True
    assert snapshot.entries["alerts.auto_scan"].source == "default"

    calls = []
    monkeypatch.setattr(quality_alerts, "scan", _recorder(calls))
    hospital = _seed_month(db_session)
    pipeline.run_full_analysis(db_session, hospital.id, MONTH)
    assert [month for month, _ in calls] == [MONTH]


# ── 2. stored true / false are consumed consistently ───────────────────────
@pytest.mark.parametrize("raw", OFF_SPELLINGS)
def test_off_spellings_resolve_to_off(raw):
    assert cr.resolve_policy({"alerts_auto_scan": raw}, {}).alerts_auto_scan is False


@pytest.mark.parametrize("raw", ON_SPELLINGS)
def test_every_other_spelling_resolves_to_on(raw):
    assert cr.resolve_policy({"alerts_auto_scan": raw}, {}).alerts_auto_scan is True


@pytest.mark.parametrize("stored,expected", [(0.0, False), (1.0, True)])
def test_stored_row_is_consumed_as_resolved(db_session, monkeypatch,
                                            stored, expected):
    _set_auto_scan(db_session, stored)
    snapshot = cr.load_policy_snapshot(db_session)
    assert snapshot.alerts_auto_scan is expected
    assert snapshot.entries["alerts.auto_scan"].source == "database"
    # The value System Control stores is the value the consumer receives.
    assert snapshot.entries["alerts.auto_scan"].value is expected

    calls = []
    monkeypatch.setattr(quality_alerts, "scan", _recorder(calls))
    hospital = _seed_month(db_session)
    pipeline.run_full_analysis(db_session, hospital.id, MONTH)
    assert bool(calls) is expected


# ── 3. the snapshot wins over a differing live value ───────────────────────
def test_snapshot_overrides_a_different_live_configuration(db_session, monkeypatch):
    _set_auto_scan(db_session, 1.0)                 # live: ON
    stale_off = cr.resolve_policy({"alerts_auto_scan": 0}, {})
    calls = []
    monkeypatch.setattr(quality_alerts, "scan", _recorder(calls))
    hospital = _seed_month(db_session, MONTH)

    pipeline.run_full_analysis(db_session, hospital.id, MONTH, policy=stale_off)
    assert calls == [], "the run used the live value instead of its snapshot"

    _set_auto_scan(db_session, 0.0)                 # live: OFF
    snap_on = cr.resolve_policy({"alerts_auto_scan": 1}, {})
    _seed_month(db_session, MONTH_B, hospital)
    pipeline.run_full_analysis(db_session, hospital.id, MONTH_B,
                               force=True, policy=snap_on)
    assert [month for month, _ in calls] == [MONTH_B]


# ── 4. one snapshot for a whole batch ──────────────────────────────────────
def test_batch_months_share_one_snapshot(db_session, monkeypatch):
    hospital = _seed_month(db_session, MONTH)
    _seed_month(db_session, MONTH_B, hospital)
    snapshot = cr.resolve_policy({"alerts_auto_scan": 1}, {})

    reads = []
    real_load = pipeline.load_policy_snapshot

    def counting(db, **kwargs):
        reads.append(1)
        return real_load(db, **kwargs)

    monkeypatch.setattr(pipeline, "load_policy_snapshot", counting)
    calls = []
    monkeypatch.setattr(quality_alerts, "scan", _recorder(calls))

    for month in (MONTH, MONTH_B):
        pipeline.run_full_analysis(db_session, hospital.id, month,
                                   force=True, policy=snapshot)

    assert reads == [], "a batch re-resolved configuration"
    assert [policy for _, policy in calls] == [snapshot, snapshot]


# ── 5. concurrent operations cannot leak the flag ──────────────────────────
def test_concurrent_snapshots_cannot_leak_the_flag():
    assert cr.PolicySnapshot.__dataclass_params__.frozen is True
    failures = []

    def worker(raw, expected):
        try:
            for _ in range(200):
                value = cr.resolve_policy({"alerts_auto_scan": raw},
                                          {}).alerts_auto_scan
                if value is not expected:
                    failures.append((raw, value))
        except Exception as exc:  # noqa: BLE001 - surfaced by the assert
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(0, False)),
               threading.Thread(target=worker, args=(1, True))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    # No default and no module-level copy: the flag can only arrive as an
    # argument resolved from that operation's own snapshot.
    parameter = inspect.signature(
        pipeline._maybe_auto_scan_quality_alerts).parameters["auto_scan"]
    assert parameter.default is inspect.Parameter.empty


# ── 6. no hidden configuration reads in the consumer chain ────────────────
def test_consumer_chain_never_reads_the_alerts_category(db_session, monkeypatch):
    """The helper reads no configuration and has no default to fall back on;
    the run hands it the resolved value and the run's snapshot."""
    source = inspect.getsource(pipeline._maybe_auto_scan_quality_alerts)
    assert "get_config_dict" not in source
    assert "alerts_auto_scan" not in source
    parameter = inspect.signature(
        pipeline._maybe_auto_scan_quality_alerts).parameters["auto_scan"]
    assert parameter.default is inspect.Parameter.empty

    calls = []
    monkeypatch.setattr(quality_alerts, "scan", _recorder(calls))
    hospital = _seed_month(db_session)
    snapshot = cr.load_policy_snapshot(db_session)
    pipeline.run_full_analysis(db_session, hospital.id, MONTH, policy=snapshot)

    assert calls and calls[0][1] is snapshot


def test_pipeline_names_neither_the_raw_key_nor_the_row_reader():
    source = (ROOT / "app" / "engine" / "pipeline.py").read_text(encoding="utf-8")
    assert '"alerts_auto_scan"' not in source
    assert 'get_config_dict(session, "alerts")' not in source
    assert "auto_scan=policy.alerts_auto_scan" in source


def test_snapshot_without_the_entry_refuses_to_guess():
    snapshot = cr.resolve_policy({}, {})
    entries = MappingProxyType({
        key: entry for key, entry in snapshot.entries.items()
        if key != "alerts.auto_scan"})
    stripped = dataclasses.replace(snapshot, entries=entries)

    with pytest.raises(cr.PolicyUnavailable):
        stripped.alerts_auto_scan
