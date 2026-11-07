"""A3.2b - policy boundaries pinned before any consumer is switched.

Design-phase contract tests. They lock the facts ``A3.2b-INTEGRATION-DESIGN.md``
relies on, so a later integration phase cannot move a boundary silently:

  * the complete call-site inventory of the two auto-disable entry points;
  * ``run_full_analysis``'s snapshot parameter and the absence of any caller
    that passes one (so bulk hoisting is a deliberate change);
  * the five categories ``_compute_full_analysis`` still reads per hospital;
  * the two silent ``False`` fallbacks and the raising paths;
  * the confidence double decision (disabled set passed in *and* flag re-read);
  * ``alerts.auto_scan`` resolved but dropped by the view and re-read by the
    consumer;
  * the digest contract: ``rules.hash`` participates, ``rules.updated_at``
    does not.

Nothing here changes production behaviour: every test reads source text, an
existing function signature, or a pure resolver call. No consumer is modified
and no production database is touched.

When A3.3 moves a boundary, the corresponding assertion must be updated
deliberately - that is the point of pinning it.
"""
from pathlib import Path

from app.engine import config_resolver as cr

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _sources():
    return {path.relative_to(APP).as_posix(): path.read_text(encoding="utf-8")
            for path in APP.rglob("*.py")}


def _count(sources, needle):
    return {name: text.count(needle) for name, text in sources.items()
            if needle in text}


# ---- auto_disable: reader inventory --------------------------------------
def test_the_old_helper_is_gone_and_the_parser_is_single():
    """A3.3 removed the database-reading helper; one pure parser remains."""
    sources = _sources()
    assert not [n for n, t in sources.items() if "_is_auto_disable_null" in t]
    resolver = sources["engine/config_resolver.py"]
    assert resolver.count("def parse_auto_disable_null") == 1
    assert 'return raw == "true"' in resolver


def test_get_disabled_indicator_ids_call_sites_are_exactly_pinned():
    """Nine call sites across four modules inherit the setting through
    ``get_disabled_indicator_ids``. A new caller must be a conscious edit."""
    counts = _count(_sources(), "get_disabled_indicator_ids(")
    # A3.3 widened the caller set: every request-level reader resolves the
    # gate at its own boundary and passes it in.
    assert set(counts) == {
        "engine/pipeline.py",       # definition + 5 internal call sites
        "api/clinical.py",
        "api/confidence.py",
        "api/rules.py",
    }
    # The drilldown and root-cause paths import it under an alias (_gdi).
    # A3.4: analytical paths resolve strictly, not through the display loader.
    for name in ("api/root_cause.py", "api/smart_analytics.py"):
        assert "auto_disable_null=load_policy_snapshot(db).require_auto_disable_null()" in (
            _sources()[name])


def test_only_the_writer_and_the_resolver_read_the_setting():
    """A3.3: System Control owns the text, the resolver parses it, and no
    consumer queries it any more (names may still appear in documentation)."""
    sources = _sources()
    for name, text in sources.items():
        assert 'SystemSetting.key == "auto_disable_null_indicators"' not in text, name
        assert "_SS.key == 'auto_disable_null_indicators'" not in text, name
    assert 'CONTROL_KEY = "auto_disable_null_indicators"' in sources["api/config_api.py"]
    assert 'FLAG_AUTO_DISABLE_KEY = "auto_disable_null_indicators"' in sources[
        "engine/config_resolver.py"]


def test_no_consumer_substitutes_false_on_a_read_failure():
    """The A3.3 failure policy: an unresolved gate is never silently False."""
    sources = _sources()
    assert "auto_disable = False" not in sources["api/dashboard.py"]
    assert "_auto_disable = False" not in sources["engine/confidence.py"]
    assert "def _is_auto_disable_null" not in sources["engine/pipeline.py"]


def test_confidence_receives_the_decision_instead_of_making_it_again():
    """One decision per run: the API resolves the gate and hands it over; the
    engine no longer queries System Control."""
    sources = _sources()
    api_conf = sources["api/confidence.py"]
    engine_conf = sources["engine/confidence.py"]
    assert "require_auto_disable_null()" in api_conf
    assert "auto_disable_null=_auto_disable_null" in api_conf
    assert "SystemSetting" not in engine_conf
    assert "if auto_disable_null and code not in values:" in engine_conf


# ---- analysis boundary ---------------------------------------------------
def test_run_full_analysis_takes_a_snapshot_but_no_caller_passes_one():
    """One snapshot per call today; batch hoisting is an A3.3 change."""
    from app.engine.pipeline import run_full_analysis

    params = list(run_full_analysis.__code__.co_varnames[
        :run_full_analysis.__code__.co_argcount])
    assert params == ["session", "hospital_id", "month", "force", "policy"]

    # A3.3: the bulk loops resolve once and pass the same snapshot through.
    sources = _sources()
    for name in ("api/upload.py", "api/analysis.py", "api/reports.py",
                 "api/file_ops.py", "api/tree_config.py"):
        assert "load_policy_snapshot(" in sources[name], name
        assert ("policy=policy" in sources[name]
                or "policy=_policy" in sources[name]), name


def test_compute_full_analysis_reads_only_the_unmigrated_categories():
    """A3.5 P1/P2 moved ``rules``, ``trends`` and ``rates`` onto resolved
    policies; ``ml`` and ``quality`` are still re-read per hospital until P3."""
    pipeline = _sources()["engine/pipeline.py"]
    body = pipeline.split("def _compute_full_analysis", 1)[1]
    body = body.split("\ndef ", 1)[0]
    assert "rules_policy_from_snapshot(policy)" in body
    for category in ("rules", "trends", "rates"):
        assert f'get_config_dict(session, "{category}")' not in body, category
    for category in ("ml", "quality"):
        assert f'get_config_dict(session, "{category}")' in body, category


# ---- alerts auto_scan ----------------------------------------------------
def test_auto_scan_is_consumed_from_the_snapshot_only():
    """A3.4: the pipeline takes the resolved flag, never the AppConfig row."""
    snapshot = cr.resolve_policy({}, {})
    assert snapshot.values["alerts.auto_scan"] is True
    assert snapshot.alerts_auto_scan is True
    assert cr.resolve_policy({"alerts_auto_scan": 0}, {}).alerts_auto_scan is False

    from app.engine.policy_view import alerts_config_from_snapshot
    assert "auto_scan" not in alerts_config_from_snapshot(snapshot)

    pipeline = _sources()["engine/pipeline.py"]
    assert 'get_config_dict(session, "alerts")' not in pipeline
    assert "auto_scan=policy.alerts_auto_scan" in pipeline


# ---- digest contract -----------------------------------------------------
def test_rules_hash_participates_and_the_timestamp_does_not():
    """A3.1b contract, restated where A3.2b depends on it: the content hash is
    identity, the write timestamp is provenance."""
    base = {"rules.hash": "a" * 64, "rules.updated_at": "2026-01-01T00:00:00"}
    other_time = {**base, "rules.updated_at": "2026-06-01T00:00:00"}
    other_hash = {**base, "rules.hash": "b" * 64}

    d_base = cr.resolve_policy({}, {}, metadata=base).digest
    assert cr.resolve_policy({}, {}, metadata=other_time).digest == d_base
    assert cr.resolve_policy({}, {}, metadata=other_hash).digest != d_base


def test_snapshot_exposes_the_digest_a_run_could_record():
    from app.engine.policy_view import snapshot_provenance

    snapshot = cr.resolve_policy({}, {})
    provenance = snapshot_provenance(snapshot)
    assert provenance["digest"] == snapshot.digest
    assert provenance["resolver_version"] == cr.RESOLVER_VERSION
    assert "unavailable_keys" in provenance
