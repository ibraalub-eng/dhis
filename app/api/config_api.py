import logging
import re
from collections import Counter
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from app.database import get_db

logger = logging.getLogger(__name__)
from app.models import AppConfig, SystemSetting
from app.config_utils import AI_CONFIG_KEYS, get_ai_config
from app.core.deps import require_permission
from app.core.error_handler import safe_endpoint

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(require_permission("settings.read"))])

# Database introspection/export is deliberately NOT governed by settings.read.
# It exposes whole-table contents, so it has its own high-privilege gate: only a
# superuser or a user explicitly granted system.export_data can reach it.
db_router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(require_permission("system.export_data"))])

# Columns whose names contain any of these markers are never serialized by the
# database preview/export endpoints (case-insensitive substring match), so
# password hashes, tokens, secrets, credentials etc. cannot leak.
SENSITIVE_COLUMN_MARKERS = (
    "password", "passwd", "pwd", "token", "secret", "credential",
    "api_key", "apikey", "access_key", "private_key", "hash", "salt",
)


def _is_sensitive_column(name: str) -> bool:
    low = name.lower()
    return any(marker in low for marker in SENSITIVE_COLUMN_MARKERS)


# Dynamic SQL below interpolates table identifiers, which cannot be passed as
# bound parameters. Table names are therefore treated as untrusted input:
#   * the ONLY source of names is live DB introspection (never request input);
#   * every name must match this strict pattern (allowlist);
#   * the name is quoted with the dialect's identifier preparer, not manually.
# A name failing the pattern is skipped and logged, never executed.
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_safe_identifier(name: str) -> bool:
    """True only for plain identifiers that cannot carry SQL metacharacters."""
    return isinstance(name, str) and bool(_SAFE_IDENTIFIER_RE.match(name))


def iter_safe_tables(db: Session):
    """Yield ``(table_name, quoted_name)`` for every introspected table whose
    name is safe. The introspection result IS the allowlist: a table that does
    not exist in the database can never be named, and a miscased/malicious name
    (quotes, semicolons, spaces, ...) is dropped before any SQL is built."""
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(db.get_bind())
    preparer = db.get_bind().dialect.identifier_preparer
    for name in sorted(inspector.get_table_names()):
        if not _is_safe_identifier(name):
            logger.warning("Skipping table with unsafe identifier: %r", name)
            continue
        yield name, preparer.quote(name)


CONTROL_KEY = "auto_disable_null_indicators"
LOGGING_KEY = "structured_logging_enabled"
SLOW_QUERY_KEY = "slow_query_logging_enabled"
HIDE_EXPLANATIONS_KEY = "hide_explanatory_text"
INCREMENTAL_UPLOAD_KEY = "upload_incremental_months"
MONTH_SETTINGS_PREFIX = "month_enabled_"
# Public API field name, kept for existing clients. Its STORAGE is the single
# authoritative AppConfig thresholds.zscore_threshold (saved default 2.5).
ANOMALY_ZSCORE_KEY = "anomaly_zscore_threshold"
# Deprecated duplicate SystemSetting written by older releases under the SAME
# name as the public field; removed on startup and on the next save so only ONE
# Z-score threshold remains.
LEGACY_ANOMALY_ZSCORE_KEY = ANOMALY_ZSCORE_KEY
ANOMALY_DRIFT_KEY = "anomaly_drift_months"


def _num_setting(db: Session, key: str, default: float, lo: float, hi: float) -> float:
    """Read a numeric SystemSetting with a safe fallback and clamping."""
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    try:
        v = float(row.value) if row else default
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _set_app_config(db: Session, key: str, category: str, label: str,
                    value: float) -> None:
    """Upsert one numeric AppConfig row (the analysis-config storage)."""
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if row is None:
        db.add(AppConfig(key=key, value=float(value), category=category,
                         label=label))
        return
    row.value = float(value)
    if not row.label:
        row.label = label


def _set_system_setting(db: Session, key: str, value) -> None:
    """Upsert one SystemSetting (text) row — System Control's storage."""
    if isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row is None:
        db.add(SystemSetting(key=key, value=text))
        return
    row.value = text


def reconcile_legacy_settings(db: Session) -> list:
    """Remove the deprecated duplicate Z-score SystemSetting.

    ``thresholds.zscore_threshold`` (saved default 2.5) is the only Z-score
    threshold in the system. Older releases also wrote
    ``SystemSetting('anomaly_zscore_threshold')`` with a different default
    (2.0); leaving it behind is a competing threshold, so it is removed and the
    removal is logged. Idempotent.
    """
    removed = []
    row = db.query(SystemSetting).filter(
        SystemSetting.key == LEGACY_ANOMALY_ZSCORE_KEY).first()
    if row is not None:
        removed.append({"key": row.key, "value": row.value})
        logger.warning(
            "Removing legacy duplicate SystemSetting %r (value=%r); "
            "AppConfig thresholds.zscore_threshold is the authoritative "
            "Z-score threshold.", row.key, row.value)
        db.delete(row)
        db.commit()
    return removed


def get_anomaly_settings(db: Session) -> dict:
    """Statistical anomaly detector knobs (dashboard 'Needs attention').

    The Z-score threshold is read from the authoritative analysis
    configuration (``thresholds.zscore_threshold``, saved default 2.5) through
    the shared severity loader — never from a second, competing setting. The
    slow-decline length remains its own SystemSetting because nothing else
    defines it.
    """
    from app.engine import severity as severity_policy

    cfg = severity_policy.load_analysis_config(db)
    return {
        ANOMALY_ZSCORE_KEY: cfg.zscore_threshold,
        "zscore_threshold_source": cfg.zscore_threshold_source,
        ANOMALY_DRIFT_KEY: int(_num_setting(db, ANOMALY_DRIFT_KEY, 3, 2, 6)),
    }


def get_severity_trend_settings(db: Session) -> dict:
    """Effective severity/temporal-trend configuration for System Control.

    Reports each saved value, its default, and WHERE it came from
    (``database`` / ``default`` / ``invalid``) so the UI can show what is
    effectively running. A database read failure is reported, never hidden
    behind defaults.
    """
    from app.engine import severity as severity_policy

    try:
        cfg = severity_policy.load_analysis_config(db)
    except severity_policy.AnalysisConfigError as exc:
        logger.error("Severity/trend configuration unreadable: %s", exc)
        return {
            "loaded": False,
            "config_source": "unavailable",
            "settings": {},
            "effective": {},
            "errors": [str(exc)],
            "zscore_threshold": None,
            "zscore_threshold_source": "unavailable",
            # Bounds are compile-time constants, so they stay available even
            # when the saved configuration cannot be read.
            "zscore_bounds": severity_policy.zscore_bounds(),
            "severity_levels": list(severity_policy.LEVELS),
            "severity_sources": list(severity_policy.SOURCES),
        }
    return {
        "loaded": True,
        "config_source": cfg.source,
        "settings": cfg.settings,
        "effective": cfg.trend.as_dict(),
        "trend_bands": dict(cfg.trend_bands),
        "errors": list(cfg.errors),
        "zscore_threshold": cfg.zscore_threshold,
        "zscore_threshold_source": cfg.zscore_threshold_source,
        "zscore_bounds": severity_policy.zscore_bounds(),
        "severity_levels": list(severity_policy.LEVELS),
        "severity_sources": list(severity_policy.SOURCES),
    }


@router.get("/database-status")
def get_database_status(db: Session = Depends(get_db)):
    """Check database connection and return stats."""
    from sqlalchemy import inspect as sa_inspect, func
    from app.models import Hospital, IndicatorValue, QualityScore, Indicator, Rule, AppConfig, SystemSetting
    try:
        db.execute(func.now())
        total_hospitals = db.query(func.count(Hospital.id)).scalar() or 0
        active_hospitals = db.query(func.count(Hospital.id)).filter(Hospital.is_active.is_(True)).scalar() or 0
        total_indicator_values = db.query(func.count(IndicatorValue.id)).scalar() or 0
        total_quality_scores = db.query(func.count(QualityScore.id)).scalar() or 0
        total_indicators = db.query(func.count(Indicator.id)).scalar() or 0
        total_rules = db.query(func.count(Rule.id)).scalar() or 0
        # Check key tables exist (portable: works on any database)
        tables = sa_inspect(db.get_bind()).get_table_names()
        return {
            "connected": True,
            "engine": "PostgreSQL",
            "total_hospitals": total_hospitals,
            "active_hospitals": active_hospitals,
            "total_indicator_values": total_indicator_values,
            "total_quality_scores": total_quality_scores,
            "total_indicators": total_indicators,
            "total_rules": total_rules,
            "tables": tables,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.get("/control/settings")
def get_control_settings(db: Session = Depends(get_db)):
    row = db.query(SystemSetting).filter(SystemSetting.key == CONTROL_KEY).first()
    log_row = db.query(SystemSetting).filter(SystemSetting.key == LOGGING_KEY).first()
    slow_row = db.query(SystemSetting).filter(SystemSetting.key == SLOW_QUERY_KEY).first()
    hide_row = db.query(SystemSetting).filter(SystemSetting.key == HIDE_EXPLANATIONS_KEY).first()
    incremental_row = db.query(SystemSetting).filter(SystemSetting.key == INCREMENTAL_UPLOAD_KEY).first()
    result = {
        "auto_disable_null_indicators": (row.value == "true") if row else False,
        "structured_logging_enabled": (log_row.value == "true") if log_row else True,
        "slow_query_logging_enabled": (slow_row.value == "true") if slow_row else True,
        "hide_explanatory_text": (hide_row.value == "true") if hide_row else False,
        "upload_incremental_months": (incremental_row.value == "true") if incremental_row else False,
    }
    # Effective saved configuration + explicit errors. A configuration read
    # failure is reported here (null + error text), never replaced by hidden
    # defaults.
    result["severity_trend"] = get_severity_trend_settings(db)
    try:
        result.update(get_anomaly_settings(db))
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        logger.error("Anomaly settings could not be loaded: %s", exc)
        try:
            drift = int(_num_setting(db, ANOMALY_DRIFT_KEY, 3, 2, 6))
        except Exception:
            drift = None
        result.update({
            "anomaly_zscore_threshold": None,
            "zscore_threshold_source": "unavailable",
            "anomaly_drift_months": drift,
            "configuration_errors": [str(exc)],
        })
    return result


@router.put("/control/settings", dependencies=[Depends(require_permission("settings.write"))])
def update_control_settings(updates: dict = Body(...), db: Session = Depends(get_db)):
    """Save Analysis Control settings (System Control is the authority).

    Validation happens for EVERY submitted value before anything is written,
    so a rejected value cannot leave a half-saved configuration behind.
    """
    from app.engine import severity as severity_policy

    errors = []
    trend_values = {}
    for key, spec in severity_policy.TREND_SETTING_SPECS.items():
        if key not in updates:
            continue
        try:
            trend_values[key] = severity_policy.coerce_setting(spec, updates[key])
        except ValueError as exc:
            errors.append(f"{key}: {exc}")

    z_value = None
    if ANOMALY_ZSCORE_KEY in updates:
        try:
            z_value = float(updates[ANOMALY_ZSCORE_KEY])
        except (TypeError, ValueError):
            errors.append(f"{ANOMALY_ZSCORE_KEY}: expected a number")
        else:
            z_value = round(max(severity_policy.ZSCORE_MIN,
                                min(severity_policy.ZSCORE_MAX, z_value)), 2)

    drift_value = None
    if ANOMALY_DRIFT_KEY in updates:
        try:
            drift_value = int(round(max(2.0, min(6.0, float(updates[ANOMALY_DRIFT_KEY])))))
        except (TypeError, ValueError):
            drift_value = None  # preserve legacy behaviour: ignore bad input

    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    updated = {}
    for key in (CONTROL_KEY, LOGGING_KEY, SLOW_QUERY_KEY, HIDE_EXPLANATIONS_KEY, INCREMENTAL_UPLOAD_KEY):
        if key in updates:
            val = str(updates[key]).lower()
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row:
                row.value = val
            else:
                db.add(SystemSetting(key=key, value=val))
            updated[key] = val == "true"
    if z_value is not None:
        # Single authoritative Z-score storage (thresholds category).
        _set_app_config(db, severity_policy.ZSCORE_KEY,
                        severity_policy.THRESHOLDS_CATEGORY,
                        "Z-Score Threshold", z_value)
        updated[ANOMALY_ZSCORE_KEY] = z_value
    for key, value in trend_values.items():
        spec = severity_policy.TREND_SETTING_SPECS[key]
        if key in severity_policy.EXISTING_TREND_KEYS:
            # Reused existing AppConfig key — never duplicated in SystemSetting.
            _set_app_config(db, key, severity_policy.TREND_CATEGORY,
                            spec.label, float(value))
        else:
            _set_system_setting(db, key, value)
        updated[key] = value
    if drift_value is not None:
        row = db.query(SystemSetting).filter(SystemSetting.key == ANOMALY_DRIFT_KEY).first()
        if row:
            row.value = str(drift_value)
        else:
            db.add(SystemSetting(key=ANOMALY_DRIFT_KEY, value=str(drift_value)))
        updated[ANOMALY_DRIFT_KEY] = drift_value
    # Drop the deprecated duplicate Z-score SystemSetting in the same
    # transaction: no second Z-score threshold may survive a save.
    legacy = db.query(SystemSetting).filter(
        SystemSetting.key == LEGACY_ANOMALY_ZSCORE_KEY).first()
    if legacy is not None:
        logger.warning(
            "Removing legacy duplicate SystemSetting %r (value=%r) on save; "
            "thresholds.zscore_threshold is authoritative.", legacy.key, legacy.value)
        db.delete(legacy)
    db.commit()
    # Update runtime flags immediately
    if LOGGING_KEY in updated:
        from app.monitoring import set_logging_enabled
        set_logging_enabled(updated[LOGGING_KEY])
    if SLOW_QUERY_KEY in updated:
        from app.monitoring import set_slow_query_logging
        set_slow_query_logging(updated[SLOW_QUERY_KEY])
    return {"status": "ok", **updated}


@router.post("/control/severity-preview")
def preview_severity_policy(updates: dict = Body(default={}),
                            db: Session = Depends(get_db)):
    """Show the impact of a severity/trend policy BEFORE recalculating.

    Reads the stored base severity + trend assessment of every persisted
    Quality Alert and reports how many rows would change severity under the
    proposed settings. Nothing is written and no analysis is recomputed: the
    actual recalculation stays an explicit Quality Alerts scan.
    """
    from app.engine import severity as severity_policy
    from app.models import QualityAlert

    try:
        current = severity_policy.load_analysis_config(db)
    except severity_policy.AnalysisConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    proposed_raw = dict(current.raw_trends)
    errors = []
    submit = updates.get("settings") if isinstance(updates.get("settings"), dict) else updates
    for key, spec in severity_policy.TREND_SETTING_SPECS.items():
        if key not in submit:
            continue
        try:
            proposed_raw[key] = severity_policy.coerce_setting(spec, submit[key])
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    proposed = severity_policy.resolve_trend_settings(proposed_raw)
    transitions = Counter()
    examined = with_trend = changed = 0
    for alert in db.query(QualityAlert).all():
        evidence = alert.evidence or {}
        base = evidence.get("base_severity")
        base = base if isinstance(base, dict) else {}
        stored_trend = evidence.get("trend_assessment")
        trend = severity_policy.trend_from_dict(stored_trend, proposed)
        quality = evidence.get("data_quality")
        completeness = (quality or {}).get("completeness") if isinstance(quality, dict) else None
        resolution = severity_policy.resolve_severity(
            base.get("level") or alert.severity,
            base.get("source") or severity_policy.SOURCE_LEGACY,
            trend=trend, config=proposed, data_quality=completeness,
        )
        examined += 1
        if trend is not None and trend.evaluated:
            with_trend += 1
        if resolution.final.level != alert.severity:
            changed += 1
            transitions[(alert.severity, resolution.final.level)] += 1

    return {
        "preview": True,
        "rows_examined": examined,
        "rows_with_trend": with_trend,
        "rows_changing": changed,
        "transitions": [
            {"from": source, "to": target, "count": count}
            for (source, target), count in sorted(
                transitions.items(), key=lambda item: (-item[1], item[0]))
        ],
        "policy": proposed.policy,
        "settings": proposed.as_dict(),
        "note": ("Preview only — stored results are unchanged. Re-run the "
                 "Quality Alerts scan to persist a new policy."),
    }


@router.get("/")
def get_all_config(db: Session = Depends(get_db)):
    rows = db.query(AppConfig).all()
    result = {}
    for r in rows:
        if r.category not in result:
            result[r.category] = {}
        result[r.category][r.key] = {
            "value": r.value,
            "label": r.label,
        }
    return result


@router.get("/month-settings")
def get_month_settings(
    hospital_id: int = Query(..., description="Hospital ID"),
    db: Session = Depends(get_db),
):
    """Get list of enabled months for a specific hospital."""
    from app.api.analysis import _list_months_with_data
    all_months = _list_months_with_data(db, None)
    prefix = MONTH_SETTINGS_PREFIX + str(hospital_id) + "_"
    rows = db.query(SystemSetting).filter(
        SystemSetting.key.like(prefix + "%")
    ).all()
    disabled = {
        row.key[len(prefix):]
        for row in rows
        if row.value == "false"
    }
    enabled_months = [m for m in all_months if m not in disabled]
    return {"enabled_months": enabled_months}


@router.put("/month-settings", dependencies=[Depends(require_permission("settings.write"))])
def update_month_setting(updates: dict = Body(...), db: Session = Depends(get_db)):
    """Enable or disable a specific month for a specific hospital."""
    month = updates.get("month")
    hospital_id = updates.get("hospital_id")
    enabled = updates.get("enabled", True)
    if not month or hospital_id is None:
        raise HTTPException(status_code=400, detail="month and hospital_id are required")
    key = MONTH_SETTINGS_PREFIX + str(hospital_id) + "_" + month
    val = "true" if enabled else "false"
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key=key, value=val))
    db.commit()
    # is_enabled on /reports (and everything derived from enabled_months)
    # is computed per request but served from a 24h file cache — without this
    # invalidation the toggle took up to a day to show up in Quality Reports.
    try:
        from app.cache import cache as _cache
        # cache.make_key() prefixes keys with 'v2|' — the invalidation prefix
        # must include it or the file cache entries never match.
        _cache.invalidate("v2|reports:")
        _cache.invalidate("v2|analysis:")
    except Exception:
        logger.exception("Failed to invalidate caches after month toggle")
    return {"status": "ok", "month": month, "hospital_id": hospital_id, "enabled": enabled}


@router.get("/{category}")
def get_config_by_category(category: str, db: Session = Depends(get_db)):
    rows = db.query(AppConfig).filter(AppConfig.category == category).all()
    return {r.key: {"value": r.value, "label": r.label} for r in rows}


@router.put("/", dependencies=[Depends(require_permission("settings.write"))])
def update_config(updates: dict, db: Session = Depends(get_db)):
    updated = 0
    for key, val in updates.items():
        row = db.query(AppConfig).filter(AppConfig.key == key).first()
        if row:
            try:
                row.value = float(val)
                updated += 1
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"Invalid numeric value for '{key}': {val}")
    db.commit()
    return {"status": "ok", "updated": updated}


@router.get("/ai/settings")
def get_ai_settings(db: Session = Depends(get_db)):
    try:
        return get_ai_config(db)
    except Exception:
        # Table may not exist yet (first deploy before migrations)
        return {k: v for k, v in AI_CONFIG_KEYS.items()}


@router.put("/ai/settings", dependencies=[Depends(require_permission("settings.write"))])
@safe_endpoint("Error saving AI settings")
def update_ai_settings(updates: dict, db: Session = Depends(get_db)):
    for key, val in updates.items():
        if key not in AI_CONFIG_KEYS:
            continue
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row:
            row.value = str(val)
        else:
            db.add(SystemSetting(key=key, value=str(val)))
    db.commit()
    from app.plugins.ai import reload_ai_config
    reload_ai_config()
    return {"status": "ok", "updated": len(updates)}


@db_router.get("/database/preview")
@safe_endpoint("Error previewing database")
def preview_database_tables(db: Session = Depends(get_db)):
    """List all tables with column info, row counts, and first 5 rows of preview data."""
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(db.get_bind())
    tables = []
    # iter_safe_tables yields only allowlisted (introspected) + validated
    # identifiers, already quoted for this dialect — no raw name reaches SQL.
    for table_name, quoted in iter_safe_tables(db):
        # Handle both dict-style and string-style column metadata
        raw_cols = inspector.get_columns(table_name)
        columns = [c["name"] if isinstance(c, dict) else str(c) for c in raw_cols]
        pk_info = inspector.get_pk_constraint(table_name)
        raw_pk = pk_info.get("constrained_columns", []) if isinstance(pk_info, dict) else []
        pk_cols = [p if isinstance(p, str) else str(p) for p in raw_pk]
        # Count rows
        try:
            count = db.execute(text(f'SELECT COUNT(*) FROM {quoted}')).scalar() or 0
        except Exception:
            count = -1  # unknown
        # Preview first 5 rows
        preview = []
        if count > 0:
            try:
                rows = db.execute(text(f'SELECT * FROM {quoted} LIMIT 5')).fetchall()
                for row in rows:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        if _is_sensitive_column(col):
                            continue
                        val = row[i] if i < len(row) else None
                        # Convert non-serializable types to string
                        if val is not None and not isinstance(val, (int, float, str, bool, type(None))):
                            val = str(val)
                        row_dict[col] = val
                    preview.append(row_dict)
            except Exception as e:
                logger.warning("Failed to preview table %s: %s", table_name, e)
        tables.append({
            "name": table_name,
            "columns": [c for c in columns if not _is_sensitive_column(c)],
            "primary_keys": pk_cols,
            "row_count": count,
            "preview": preview,
        })
    return {"tables": tables, "total_tables": len(tables)}


@db_router.get("/database/export")
@safe_endpoint("Error exporting database")
def export_database(db: Session = Depends(get_db)):
    """Export all tables and all data as JSON."""
    from sqlalchemy import inspect as sa_inspect, text
    from fastapi.responses import StreamingResponse
    import io, json, datetime
    inspector = sa_inspect(db.get_bind())
    export = {
        "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
        "engine": str(db.get_bind().url).split("@")[-1] if "@" in str(db.get_bind().url) else str(db.get_bind().url),
        "tables": {},
    }
    total_rows = 0
    for table_name, quoted in iter_safe_tables(db):
        raw_cols = inspector.get_columns(table_name)
        columns = [c["name"] if isinstance(c, dict) else str(c) for c in raw_cols]
        try:
            rows = db.execute(text(f'SELECT * FROM {quoted} LIMIT 5000')).fetchall()
        except Exception:
            rows = []
        data = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                if _is_sensitive_column(col):
                    continue
                val = row[i] if i < len(row) else None
                if val is not None and not isinstance(val, (int, float, str, bool, type(None))):
                    val = str(val)
                row_dict[col] = val
            data.append(row_dict)
        export["tables"][table_name] = {
            "columns": [c for c in columns if not _is_sensitive_column(c)],
            "row_count": len(data),
            "rows": data,
        }
        total_rows += len(data)
    export["total_tables"] = len(export["tables"])
    export["total_rows"] = total_rows
    # Return as downloadable JSON
    content_str = json.dumps(export, ensure_ascii=False, indent=2, default=str)
    filename = "database_export_{}.json".format(datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S"))
    return StreamingResponse(
        io.BytesIO(content_str.encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
