import os
import re
import shutil
import io
import json
import hashlib
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.utils.excel_parser import process_excel_upload, parse_excel, normalize_data
from app.engine.pipeline import (
    run_full_analysis,
    recompute_hospital_months,
    get_enabled_values_for_hospital_month,
)
from app.eligibility import disabled_pairs
from app.schemas import UploadResponse, AutoReportResponse
from app.indicators import INDICATOR_FLAT_LIST, SYNTHETIC_INDICATOR_CODES
from app.models import IndicatorValue, Indicator, Hospital
from app.cache import cache
from app.engine.comparative.report_cache import invalidate_report_cache
from app.core.deps import get_user_hospital_ids, require_permission
from app.config import MAX_UPLOAD_SIZE
from app.utils.files import safe_upload_name
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])


def invalidate_data_caches(db=None):
    """Drop every cache derived from indicator values and stored analyses.

    An import changes the month list, the reports, the dashboard and every
    smart section at once. Clearing only the ``smart_*`` prefixes left
    /analysis/months, /reports/ and the dashboard serving the pre-upload
    payload for up to 24h whenever the set of months did not change (a
    corrected re-upload of months that already existed), so the screens looked
    "not updated" right after an upload.
    """
    cache.invalidate()
    if db is not None:
        try:
            invalidate_report_cache(db)
        except Exception:
            logger.warning("Report cache invalidation failed", exc_info=True)


def _process_upload(file_path, file, db):
    """Process an uploaded Excel file with cleanup on error and cache invalidation."""
    try:
        result = process_excel_upload(file_path, db)
    except ValueError as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        logger.error(f"Unexpected error processing {file.filename}: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Error processing file: {str(e)}")
    invalidate_data_caches(db)
    return result

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


@router.get("/analysis-status")
def analysis_status(
    months: str = Query(
        "",
        description="Comma-separated YYYY-MM months; empty = the months of a running analysis",
    ),
    db: Session = Depends(get_db),
    user=Depends(require_permission("analysis.read")),
):
    """Per-month analysis state for the upload screen.

    ``POST /upload/`` keeps its published response: it imports values and
    queues the analysis, so the browser never receives a task id. This reader
    answers the question that screen actually has — for each month, is the
    background analysis still running, finished, or failed — keyed by month
    instead of by task.

    The counters use the pipeline's own analysis eligibility, not merely "has
    any value": a disabled hospital-month pair and a pair whose indicators are
    all disabled are never analysed, so they are outside both the denominator
    and the finished count. Otherwise such a month could never read complete.
    """
    from app.engine.pipeline import is_fallback_quality_row
    from app.models import QualityScore
    from app.tasks import list_tasks

    tasks = list_tasks()
    requested = [m.strip() for m in (months or "").split(",") if m.strip()]
    if not requested:
        # Nothing named: report whatever a running analysis is working on, so
        # the screen can show the months it would otherwise render empty.
        requested = sorted({
            m
            for t in tasks
            if t.get("status") in ("pending", "running")
            for m in ((t.get("meta") or {}).get("months") or [])
        })
    requested = [m for m in dict.fromkeys(requested) if _MONTH_RE.match(m)]
    if not requested:
        return {"months": []}

    scope = get_user_hospital_ids(user, db)
    disabled = disabled_pairs(db)

    def _in_scope(query, column):
        return query.filter(column.in_(scope)) if scope is not None else query

    out = []
    for month in requested:
        month_tasks = [
            t for t in tasks
            if month in ((t.get("meta") or {}).get("months") or [])
        ]
        month_tasks.sort(
            key=lambda t: (t.get("created_at") or "", t.get("id") or ""),
            reverse=True,
        )
        task = month_tasks[0] if month_tasks else None
        task_status = (task or {}).get("status")
        task_result = (task or {}).get("result") or {}

        # The analysis gate itself (see app.engine.pipeline): a hospital-month
        # is analysed only when the pair is not disabled and it still has
        # enabled values (non-null, indicator not manually disabled). Counting
        # every active hospital that merely has some non-null value included
        # pairs the pipeline deliberately never analyses, so a month with one
        # such pair could never reach "complete".
        candidate_ids = _in_scope(
            db.query(Hospital.id)
            .join(IndicatorValue, IndicatorValue.hospital_id == Hospital.id)
            .filter(
                IndicatorValue.month == month,
                IndicatorValue.value.isnot(None),
                Hospital.is_active.is_(True),
            )
            .distinct(),
            Hospital.id,
        ).all()
        eligible = sorted({
            hospital_id
            for (hospital_id,) in candidate_ids
            if (hospital_id, month) not in disabled
            and get_enabled_values_for_hospital_month(db, hospital_id, month)
        })
        hospitals = len(eligible)

        # Same eligibility on the finished side. Stored rows of pairs outside
        # it (a "no data" or failure row for a month that was since disabled)
        # are not part of this month's analysis result.
        stored = (
            db.query(QualityScore).filter(
                QualityScore.month == month,
                QualityScore.hospital_id.in_(eligible),
            ).all()
            if eligible else []
        )
        rows_by_hospital = {row.hospital_id: row for row in stored}
        # A pair whose analysis raised before storing anything leaves no row, so
        # the stored rows alone can never report it — the task's own failure
        # report is the only evidence. Counting it as "could not be analysed"
        # makes the month fail visibly instead of waiting in the queue forever.
        task_failed_ids = {
            f.get("hospital_id")
            for f in (task_result.get("failed") or [])
            if f.get("month") == month and f.get("hospital_id") in eligible
        }
        stored_failed = sum(
            1 for row in rows_by_hospital.values() if is_fallback_quality_row(row)
        )
        failed = stored_failed + len(
            {hid for hid in task_failed_ids if hid not in rows_by_hospital}
        )
        analyzed = len(rows_by_hospital) - stored_failed
        covered = analyzed + failed

        if task_status in ("pending", "running"):
            # The task is the authority while it runs: its own progress counts
            # the hospital-months it has finished, including the older
            # baselines the month itself does not need.
            status = "analyzing"
            progress = int((task or {}).get("progress") or 0)
            error = None
        elif task_status == "error" and covered < hospitals:
            status = "failed"
            progress = 100
            error = (task or {}).get("error") or "Analysis failed"
        elif covered >= hospitals and failed:
            status = "failed"
            progress = 100
            error = f"{failed} hospital(s) could not be analysed"
        elif covered >= hospitals:
            # Also the empty month: with no eligible pair there is nothing the
            # analysis can produce for it, so it is finished rather than left
            # "queued" forever.
            status = "complete"
            progress = 100
            error = None
        elif task_status == "done" and task_result.get("skipped"):
            skipped = int(task_result.get("skipped") or 0)
            status = "failed"
            progress = int(covered / max(hospitals, 1) * 100)
            error = (
                "Analysis stopped before this month finished "
                f"({skipped} hospital-month(s) left)"
            )
        else:
            status = "pending"
            progress = int(covered / max(hospitals, 1) * 100) if hospitals else 0
            error = None

        out.append({
            "month": month,
            "status": status,
            "progress": progress,
            "hospitals": hospitals,
            "analyzed": analyzed,
            "failed": failed,
            "error": error,
        })
    return {"months": out}


ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".xlsm", ".xlsb"}


def _check_upload_size_sync(file: UploadFile):
    """Reject files larger than MAX_UPLOAD_SIZE (sync version for sync endpoints)."""
    data = file.file.read()
    size = len(data)
    file.file.seek(0)
    if size > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {size // 1024 // 1024}MB exceeds {MAX_UPLOAD_SIZE // 1024 // 1024}MB limit",
        )

async def _check_upload_size(file: UploadFile):
    """Reject files larger than MAX_UPLOAD_SIZE (async version)."""
    data = await file.read()
    size = len(data)
    await file.seek(0)
    if size > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {size // 1024 // 1024}MB exceeds {MAX_UPLOAD_SIZE // 1024 // 1024}MB limit",
        )


def _recompute_after_upload(result: dict):
    """Queue the shared background recompute for an import's hospitals/months.

    ``POST /upload/`` only imports values. Without this step an API upload
    created months with indicator values but no QualityScore/validation rows,
    so every screen showed those months as empty until someone re-analysed by
    hand. The work itself is the same helper "update saved file" and
    "upload multiple & analyze" use (new months first, budgeted, caches and
    smart analytics refreshed at the end). The HTTP response is unchanged.
    """
    hospital_ids = [
        h.get("id") for h in (result.get("hospitals") or []) if h.get("id")
    ]
    if not hospital_ids:
        return None
    try:
        from app.api.file_ops import _recompute_hospital_months_bg
        return _recompute_hospital_months_bg(
            hospital_ids, result.get("months") or [], "upload")
    except Exception:
        # The import already succeeded and the response must not change; the
        # month simply stays unanalysed and a later analysis run picks it up.
        logger.warning("Could not queue background analysis after upload", exc_info=True)
        return None


def _precompute_smart_bg(months: list):
    """Pre-compute smart analytics for all months in a background thread.

    After upload, the smart analytics pipeline (9 engines) is heavy.
    Running it in background and caching the result means the dashboard
    loads instantly on first visit.
    """
    import threading
    from app.api.smart_analytics import _get_smart_data, SMART_CACHE_VERSION
    from app.database import SessionLocal

    def _run():
        import time
        db = SessionLocal()
        try:
            for month in months:
                for attempt in range(3):
                    try:
                        cache_key = f"smart_overview_{month}_{SMART_CACHE_VERSION}"
                        if cache.get(cache_key) is not None:
                            break  # already cached
                        logger.info(f"[precompute] Running smart analytics for {month}...")
                        _get_smart_data(db, month)
                        logger.info(f"[precompute] Cached smart analytics for {month}")
                        break
                    except Exception as e:
                        if "locked" in str(e).lower() and attempt < 2:
                            logger.info(f"[precompute] DB locked for {month}, retrying in 5s...")
                            time.sleep(5)
                            # Re-create session on locked DB
                            try:
                                db.close()
                            except Exception:
                                pass
                            db = SessionLocal()
                        else:
                            logger.warning(f"[precompute] Failed for {month}: {e}")
                            break
        finally:
            try:
                db.close()
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()


@router.get("/template")
def download_template(user=Depends(require_permission("data.upload"))):
    import openpyxl
    top_inds = [ind for ind in INDICATOR_FLAT_LIST if ind["level"] == 0 and ind["code"] not in SYNTHETIC_INDICATOR_CODES]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SRMNH Data Template"
    ws.append(["organisationunitname", "month"] + [ind["name"] for ind in top_inds])
    ws.append(["Al-Shifa Hospital", "2026-01"] + ["" for _ in top_inds])
    ws.append(["European Gaza Hospital", "2026-01"] + ["" for _ in top_inds])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 12
    for col_letter in ["C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X"]:
        ws.column_dimensions[col_letter].width = 22
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=srmnh_template_{datetime.now().strftime('%Y%m%d')}.xlsx"}
    )


class DuplicateCheckResponse(BaseModel):
    is_duplicate: bool
    existing_file: str = ""
    existing_records: int = 0
    existing_months: list = []
    existing_hospitals: list = []
    file_hash: str = ""


@router.post("/check-duplicate")
def check_duplicate(file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(require_permission("data.upload"))):
    """Check if uploaded file is a duplicate of previously uploaded data.
    Returns duplicate info so frontend can show confirmation dialog."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File extension '{ext}' not supported")

    _check_upload_size_sync(file)

    # Read file content and compute hash
    content = file.file.read()
    file.file.seek(0)  # Reset for later reading
    file_hash = hashlib.sha256(content).hexdigest()

    # Check if any IndicatorValues exist with this source filename
    filename = os.path.basename(file.filename or "")
    existing = (
        db.query(IndicatorValue)
        .filter(IndicatorValue.source_file == filename)
        .all()
    )

    if existing:
        months = sorted(set(iv.month for iv in existing))
        hosp_ids = sorted(set(iv.hospital_id for iv in existing))
        hosp_names = []
        if hosp_ids:
            hosp_names = [h.name for h in db.query(Hospital).filter(Hospital.id.in_(hosp_ids)).all()]
        return DuplicateCheckResponse(
            is_duplicate=True,
            existing_file=filename,
            existing_records=len(existing),
            existing_months=months,
            existing_hospitals=hosp_names[:10],  # Limit to 10
            file_hash=file_hash,
        )

    return DuplicateCheckResponse(is_duplicate=False, file_hash=file_hash)


@router.post("/preview")
def preview_excel(file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(require_permission("data.upload"))):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported extension: {ext}")
    from app.config import UPLOAD_DIR
    _check_upload_size_sync(file)
    upload_dir = UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = safe_upload_name(file.filename)
    file_path = os.path.join(upload_dir, safe_name)
    file.file.seek(0)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        df = parse_excel(file_path)
        records = normalize_data(df)
        if not records:
            raise HTTPException(status_code=422, detail="No recognizable data found in file")
        hospital_names = sorted(set(r["hospital_name"] for r in records))
        months = sorted(set(r["month"] for r in records))
        indicator_codes = sorted(set(r["indicator_code"] for r in records))
        code_to_name = {ind["code"]: ind["name"] for ind in INDICATOR_FLAT_LIST}
        sample_rows = records[:20]
        return {
            "filename": file.filename,
            "total_rows": len(records),
            "hospitals": hospital_names,
            "months": months,
            "indicators_found": [{"code": c, "name": code_to_name.get(c, c)} for c in indicator_codes],
            "sample_rows": [{"hospital": r["hospital_name"], "month": r["month"], "indicator": code_to_name.get(r["indicator_code"], r["indicator_code"]), "value": r["value"]} for r in sample_rows],
            "file_path": file_path,
        }
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/data-entry/options")
def data_entry_options(db: Session = Depends(get_db), user=Depends(require_permission("data.upload"))):
    hospitals = db.query(Hospital).order_by(Hospital.name).all()
    top_indicators = [ind for ind in INDICATOR_FLAT_LIST if ind["level"] == 0 and ind["code"] not in SYNTHETIC_INDICATOR_CODES]
    return {
        "hospitals": [{"id": h.id, "name": h.name} for h in hospitals],
        "indicators": [{"code": ind["code"], "name": ind["name"]} for ind in top_indicators],
    }


@router.post("/data-entry/save")
def save_manual_entry(
    hospital_id: int = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    data: str = Query(..., description='JSON dict of indicator_code: value, e.g. {"2":450,"3":300}'),
    db: Session = Depends(get_db),
    user=Depends(require_permission("data.upload")),
):
    try:
        values = json.loads(data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in data parameter")
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    saved = 0
    for code, val in values.items():
        indicator = db.query(Indicator).filter(Indicator.code == code).first()
        if not indicator:
            continue
        existing = db.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hospital_id,
            IndicatorValue.indicator_id == indicator.id,
            IndicatorValue.month == month,
        ).first()
        if existing:
            existing.value = float(val) if val is not None else None
        else:
            iv = IndicatorValue(
                hospital_id=hospital_id,
                indicator_id=indicator.id,
                month=month,
                value=float(val) if val is not None else None,
            )
            db.add(iv)
        saved += 1
    db.commit()
    invalidate_data_caches(db)
    return {"message": f"Saved {saved} values for {hospital.name} / {month}", "hospital": hospital.name, "month": month, "values_saved": saved}


@router.post("/", response_model=UploadResponse)
async def upload_excel(file: UploadFile = File(...), override: bool = Query(False, description="Allow overwriting existing data"), db: Session = Depends(get_db), user=Depends(require_permission("data.upload"))):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' not supported. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    from app.config import UPLOAD_DIR
    upload_dir = UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    await _check_upload_size(file)
    safe_name = safe_upload_name(file.filename)
    file_path = os.path.join(upload_dir, safe_name)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        os.remove(file_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes)")
    logger.info(f"Uploaded file: {file.filename} ({file_size} bytes)")

    # Check for duplicate file before processing
    filename = safe_name
    existing_records = (
        db.query(IndicatorValue)
        .filter(IndicatorValue.source_file == filename)
        .count()
    )
    if existing_records > 0 and not override:
        os.remove(file_path)
        raise HTTPException(
            status_code=409,
            detail=json.dumps({
                "error": "duplicate_file",
                "message": f"File '{filename}' was already uploaded with {existing_records} records.",
                "existing_records": existing_records,
                "hint": "Use override=true to replace existing data."
            })
        )

    result = _process_upload(file_path, file, db)
    # Importing values is not analysing them: recompute the affected months in
    # the background before the screens can be asked for them.
    _recompute_after_upload(result)
    # Pre-compute smart analytics in background so the dashboard loads instantly
    _precompute_smart_bg(result.get("months", []))
    return UploadResponse(**result)


@router.post("/analyze", response_model=AutoReportResponse)
async def upload_and_analyze(file: UploadFile = File(...), override: bool = Query(False), db: Session = Depends(get_db), user=Depends(require_permission("data.upload"))):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' not supported. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    from app.config import UPLOAD_DIR
    upload_dir = UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    await _check_upload_size(file)
    safe_name = safe_upload_name(file.filename)
    file_path = os.path.join(upload_dir, safe_name)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        os.remove(file_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes)")

    # Check for duplicate file before processing
    filename = safe_name
    existing_count = (
        db.query(IndicatorValue)
        .filter(IndicatorValue.source_file == filename)
        .count()
    )
    if existing_count > 0 and not override:
        os.remove(file_path)
        raise HTTPException(
            status_code=409,
            detail=json.dumps({
                "error": "duplicate_file",
                "message": f"File '{filename}' was already uploaded with {existing_count} records.",
                "existing_records": existing_count,
                "hint": "Use override=true to replace existing data."
            })
        )

    result = _process_upload(file_path, file, db)

    hospitals = result["hospitals"]
    months = result["months"]
    reports = []
    # A3.3: one snapshot for this upload's whole re-analysis batch.
    from app.engine.config_resolver import load_policy_snapshot
    policy = load_policy_snapshot(db)
    for hosp in hospitals:
        # Recompute every month of the affected hospital: the new values change
        # this hospital's historical/trend baselines, not just the uploaded month.
        try:
            recompute_hospital_months(db, hosp["id"], policy=policy)
        except Exception as e:
            logger.warning(f"Could not recompute months for {hosp['name']}: {e}")
        for month in months:
            try:
                # Already freshly computed above; this returns the cached summary.
                report = run_full_analysis(db, hosp["id"], month, policy=policy)
                reports.append(report)
            except Exception as e:
                logger.warning(f"Could not analyze {hosp['name']} / {month}: {e}")

    # The analyses above rewrote the stored scores; drop anything cached while
    # the batch was running so no screen keeps a mid-run payload.
    invalidate_data_caches(db)

    # Pre-compute smart analytics in background
    _precompute_smart_bg(months)
    return AutoReportResponse(
        filename=result["filename"],
        hospitals=hospitals,
        months=months,
        reports=reports,
        new_indicators=result.get("new_indicators", []),
        renamed_indicators=result.get("renamed_indicators", []),
    )