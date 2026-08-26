from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
import threading
from app.database import get_db, SessionLocal
from app.tasks import create_task, run_task
from app.models import Hospital, IndicatorValue, QualityScore, ValidationResult
from app.engine.pipeline import run_full_analysis, get_enabled_values_for_hospital_month
from app.engine.anomaly import analyze_historical_trends, compare_hospitals
from app.engine.clinical import run_clinical_analysis
from app.utils.excel_parser import process_excel_upload
from datetime import datetime
from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE
from app.schemas import MultiFileUploadResponse
from app.core.deps import require_permission
import os
import shutil
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"], dependencies=[Depends(require_permission("data.upload"))])

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".xlsm", ".xlsb"}


@router.get("/saved-files")
def list_saved_files(db: Session = Depends(get_db)):
    """List uploaded files from database (not filesystem).

    On Render, UPLOAD_DIR is ephemeral /tmp — files vanish on restart.
    The data itself persists in IndicatorValue.source_file, so we
    query distinct source_file values from PostgreSQL instead.
    """
    from sqlalchemy import func

    rows = (
        db.query(
            IndicatorValue.source_file,
            func.count(IndicatorValue.id).label("records_in_db"),
            func.min(IndicatorValue.month).label("earliest_month"),
            func.max(IndicatorValue.month).label("latest_month"),
            func.count(func.distinct(IndicatorValue.hospital_id)).label("hospitals_count"),
            func.min(IndicatorValue.created_at).label("uploaded_at"),
        )
        .filter(IndicatorValue.source_file.isnot(None), IndicatorValue.source_file != "")
        .group_by(IndicatorValue.source_file)
        .order_by(func.min(IndicatorValue.created_at).desc())
        .all()
    )

    files = []
    for row in rows:
        fname = row.source_file
        # Check if file still exists on disk (may or may not)
        fpath = os.path.join(UPLOAD_DIR, fname) if UPLOAD_DIR else None
        on_disk = fpath and os.path.exists(fpath)
        size_kb = 0.0
        if on_disk:
            try:
                size_kb = round(os.path.getsize(fpath) / 1024, 1)
            except OSError:
                pass
        uploaded_at = None
        if row.uploaded_at:
            uploaded_at = row.uploaded_at.isoformat()

        # Estimate file size: ~50 bytes per record (hospital + indicator + month + value)
        est_size_kb = round(row.records_in_db * 0.05, 1) if not on_disk else size_kb

        files.append({
            "filename": fname,
            "size_kb": est_size_kb,
            "on_disk": on_disk,
            "records_in_db": row.records_in_db,
            "hospitals_count": row.hospitals_count,
            "months": f"{row.earliest_month} – {row.latest_month}" if row.earliest_month else "",
            "uploaded_at": uploaded_at,
        })
    return files


@router.post("/analyze-saved")
async def analyze_saved_files(
    filenames: List[str] = Query(..., description="List of filenames to analyze"),
    db: Session = Depends(get_db),
):
    """Re-analyze previously uploaded data.

    If the file exists on disk, re-import it. Otherwise, use the data
    already in the database (IndicatorValue rows with matching source_file).
    """
    total_rows = 0
    all_months = set()
    all_hospital_ids = set()
    processed_files = 0

    for fname in filenames:
        # Try re-importing from disk first
        fpath = os.path.join(UPLOAD_DIR, fname) if UPLOAD_DIR else None
        if fpath and os.path.exists(fpath):
            try:
                result = process_excel_upload(fpath, db)
                total_rows += result.get("rows_imported", 0)
                if result.get("months"):
                    all_months.update(result["months"])
                if result.get("hospitals"):
                    for h in result["hospitals"]:
                        all_hospital_ids.add(h["id"])
                processed_files += 1
                continue
            except Exception as e:
                logger.error(f"Error processing saved file {fname}: {e}")

        # File not on disk — gather data already in DB
        iv_rows = (
            db.query(IndicatorValue)
            .filter(IndicatorValue.source_file == fname)
            .all()
        )
        if iv_rows:
            processed_files += 1
            for iv in iv_rows:
                all_hospital_ids.add(iv.hospital_id)
                all_months.add(iv.month)
            total_rows += len(iv_rows)

    hospitals_list = _get_hospitals_from_ids(db, all_hospital_ids)
    hospital_months = _get_hospital_months_map(db, hospitals_list)

    quality_reports = _run_quality_reports(db, hospitals_list, hospital_months)
    trend_analyses = _run_trend_analyses(db, hospitals_list, hospital_months)
    hospital_comparisons = _run_hospital_comparisons(db, hospitals_list, all_months)
    clinical_analyses = _run_clinical_analyses(db, hospitals_list, hospital_months)

    return {
        "files_processed": processed_files,
        "hospitals_processed": len(hospitals_list),
        "rows_imported": total_rows,
        "months": sorted(all_months),
        "hospitals": [{"id": h.id, "name": h.name} for h in hospitals_list],
        "quality_reports": quality_reports,
        "trend_analyses": trend_analyses,
        "hospital_comparisons": hospital_comparisons,
        "clinical_analyses": clinical_analyses,
        "message": f"Analyzed {processed_files} saved files: {len(quality_reports)} quality reports for {len(hospitals_list)} hospitals",
    }


@router.delete("/saved-files")
def delete_saved_files(body: dict, db: Session = Depends(get_db)):
    """Delete uploaded data from database by source file name.

    Removes IndicatorValue rows (and their cascade-linked validation/
    quality / anomaly results) so the data no longer appears in the
    "Previously Uploaded Files" list or in any analysis.
    """
    from app.models import AnomalyResult
    filenames = body.get("filenames", [])
    deleted = 0
    for fname in filenames:
        # Delete IndicatorValues (cascade will remove ValidationResults etc.)
        count = db.query(IndicatorValue).filter(IndicatorValue.source_file == fname).delete()
        # Also delete any anomaly results tied to those hospitals+months
        # (AnomalyResult doesn't have source_file, so skip for safety)
        deleted += count
        # Remove file from disk if it still exists (best-effort)
        if UPLOAD_DIR:
            fpath = os.path.join(UPLOAD_DIR, fname)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except OSError:
                    pass
    db.commit()
    return {"message": f"Deleted {deleted} record(s) from {len(filenames)} file(s).", "deleted": deleted}


@router.post("/upload-multiple", response_model=MultiFileUploadResponse)
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    upload_dir = UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)

    total_rows = 0
    all_months = set()
    all_hospital_ids = set()
    processed_files = 0

    for file in files:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            logger.warning(f"Skipping file with unsupported extension: {file.filename}")
            continue

        data = await file.read()
        if len(data) > MAX_UPLOAD_SIZE:
            logger.warning(f"Skipping oversized file: {file.filename} ({len(data) // 1024 // 1024}MB)")
            continue
        await file.seek(0)

        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        if os.path.getsize(file_path) == 0:
            os.remove(file_path)
            continue

        try:
            result = process_excel_upload(file_path, db)
            total_rows += result.get("rows_imported", 0)
            if result.get("months"):
                all_months.update(result["months"])
            if result.get("hospitals"):
                for h in result["hospitals"]:
                    all_hospital_ids.add(h["id"])
            processed_files += 1
        except Exception as e:
            logger.error(f"Error processing {file.filename}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)

    hospitals_list = (
        db.query(Hospital)
        .filter(Hospital.id.in_(all_hospital_ids))
        .all()
        if all_hospital_ids else []
    )

    return MultiFileUploadResponse(
        files_processed=processed_files,
        hospitals_processed=len(hospitals_list),
        rows_imported=total_rows,
        months=sorted(all_months),
        hospitals=[{"id": h.id, "name": h.name} for h in hospitals_list],
        message=f"Processed {processed_files} files: {total_rows} indicator values for {len(hospitals_list)} hospitals across {len(all_months)} months",
    )


@router.post("/upload-multiple-analyze")
async def upload_multiple_and_analyze(
    files: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    upload_dir = UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)

    total_rows = 0
    all_months = set()
    all_hospital_ids = set()
    processed_files = 0

    for file in files:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue

        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        if os.path.getsize(file_path) == 0:
            os.remove(file_path)
            continue

        try:
            result = process_excel_upload(file_path, db)
            total_rows += result.get("rows_imported", 0)
            if result.get("months"):
                all_months.update(result["months"])
            if result.get("hospitals"):
                for h in result["hospitals"]:
                    all_hospital_ids.add(h["id"])
            processed_files += 1
        except Exception as e:
            logger.error(f"Error processing {file.filename}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)

    hospitals_list = _get_hospitals_from_ids(db, all_hospital_ids)
    hospital_months = _get_hospital_months_map(db, hospitals_list)

    task_id = create_task("Upload & Analyze", lambda: None)

    def _run_analyses_in_bg(h_months, tid):
        from app.engine.pipeline import run_full_analysis
        bg_db = SessionLocal()
        try:
            total = sum(len(ms) for ms in h_months.values())
            done = 0
            for h_id, months in h_months.items():
                for m in months:
                    try:
                        run_full_analysis(bg_db, h_id, m)
                    except Exception as e:
                        logger.error(f"Background analysis failed H{h_id}/{m}: {e}")
                    done += 1
                    from app.tasks import set_progress
                    set_progress(tid, int(done / total * 100))
        finally:
            bg_db.close()

    if background_tasks is not None:
        background_tasks.add_task(run_task, task_id, _run_analyses_in_bg, hospital_months, task_id)
    else:
        threading.Thread(target=run_task, args=(task_id, _run_analyses_in_bg, hospital_months, task_id), daemon=True).start()

    return {
        "task_id": task_id,
        "files_processed": processed_files,
        "hospitals": [{"id": h.id, "name": h.name} for h in hospitals_list],
        "months": sorted(all_months),
        "rows_imported": total_rows,
        "message": f"Processing {processed_files} files in background. Use /tasks/{task_id} to check status.",
    }


@router.post("/process-preview")
def process_preview_file(
    filename: str = Query(...),
    override: bool = Query(False, description="Allow overwriting existing data"),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Start processing in background — returns task_id immediately.

    Frontend polls GET /tasks/{task_id} until status is "done".

    Accepts an optional file re-upload: on Render the ephemeral disk may lose
    the file between the preview and confirm steps, so the frontend re-sends
    the file to guarantee availability.
    """
    upload_dir = UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)

    # Always save from the request body if provided (more reliable on ephemeral disks)
    if file is not None:
        file.file.seek(0)
        with open(file_path, "wb") as fobj:
            shutil.copyfileobj(file.file, fobj)
    elif not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}. Please re-upload the file.")

    # If override, delete existing records for this file before reprocessing
    if override:
        try:
            from app.models import IndicatorValue
            deleted = db.query(IndicatorValue).filter(IndicatorValue.source_file == filename).delete()
            db.commit()
            logger.info(f"Override: deleted {deleted} existing records for {filename}")
        except Exception as e:
            logger.warning(f"Override delete failed for {filename}: {e}")
            db.rollback()

    task_id = create_task(f"process-preview:{filename}")
    t = threading.Thread(target=run_task, args=(task_id, _process_preview_worker, file_path), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "pending"}


def _process_preview_worker(file_path: str) -> dict:
    """Heavy analysis work — runs inside run_task() which handles
    status/result/error automatically."""
    db = SessionLocal()
    try:
        total_rows = 0
        all_months = set()
        all_hospital_ids = set()

        result = process_excel_upload(file_path, db)
        total_rows += result.get("rows_imported", 0)
        if result.get("months"):
            all_months.update(result["months"])
        if result.get("hospitals"):
            for h in result["hospitals"]:
                all_hospital_ids.add(h["id"])

        hospitals_list = _get_hospitals_from_ids(db, all_hospital_ids)
        hospital_months = _get_hospital_months_map(db, hospitals_list)

        quality_reports = _run_quality_reports(db, hospitals_list, hospital_months)
        trend_analyses = _run_trend_analyses(db, hospitals_list, hospital_months)
        comparisons_dict = _run_hospital_comparisons(db, hospitals_list, all_months)
        clinical_analyses = _run_clinical_analyses(db, hospitals_list, hospital_months)

        # Pre-compute smart analytics in background so the dashboard loads instantly
        try:
            from app.api.upload import _precompute_smart_bg
            _precompute_smart_bg(db, sorted(all_months))
        except Exception:
            pass

        return {
            "files_processed": 1,
            "hospitals": [{"id": h.id, "name": h.name} for h in hospitals_list],
            "months": sorted(all_months),
            "rows_imported": total_rows,
            "quality_reports": quality_reports,
            "trend_analyses": trend_analyses,
            "hospital_comparisons": comparisons_dict,
            "clinical_analyses": clinical_analyses,
            "message": f"Processed file: {total_rows} indicator values for {len(hospitals_list)} hospitals across {len(all_months)} months",
        }
    finally:
        db.close()


# ?? Shared helpers ?????????????????????????

def _get_hospitals_from_ids(db: Session, ids: set) -> list:
    if not ids:
        return []
    return db.query(Hospital).filter(Hospital.id.in_(ids)).all()


def _get_hospital_months_map(db: Session, hospitals_list: list) -> dict:
    result = {}
    for h in hospitals_list:
        rows = (
            db.query(IndicatorValue.month)
            .filter(IndicatorValue.hospital_id == h.id)
            .distinct()
            .all()
        )
        result[h.id] = sorted([r[0] for r in rows])
    return result


def _run_quality_reports(db: Session, hospitals_list: list, hospital_months: dict) -> list:
    reports = []
    for h in hospitals_list:
        for m in hospital_months.get(h.id, []):
            try:
                report = run_full_analysis(db, h.id, m)
                if report:
                    reports.append(report)
            except Exception as e:
                logger.error(f"Quality report failed: {h.name}/{m}: {e}")
    return reports


def _run_trend_analyses(db: Session, hospitals_list: list, hospital_months: dict) -> dict:
    result = {}
    for h in hospitals_list:
        h_monthly = {}
        for m in hospital_months.get(h.id, []):
            vals = get_enabled_values_for_hospital_month(db, h.id, m)
            if vals:
                h_monthly[m] = vals
        if len(h_monthly) >= 2:
            try:
                trends = analyze_historical_trends(h.name, h_monthly)
                if trends:
                    result[str(h.id)] = [
                        {
                            "rate_name": t.rate_name,
                            "trend_direction": t.trend_direction,
                            "trend_severity": t.trend_severity,
                            "slope_pct": float(t.slope_pct) if t.slope_pct is not None else 0.0,
                            "is_significant": bool(t.is_significant),
                            "findings": t.findings,
                            "months": t.months,
                            "values": [float(v) for v in t.values],
                            "mean": float(t.mean),
                            "std": float(t.std),
                            "cv": float(t.cv),
                            "last_vs_mean_pct_change": float(t.last_vs_mean_pct_change),
                            "consecutive_direction": t.consecutive_direction,
                            "consecutive_count": int(t.consecutive_count),
                        }
                        for t in trends
                    ]
            except Exception as e:
                logger.error(f"Trend analysis failed: {h.name}: {e}")
    return result


def _run_hospital_comparisons(db: Session, hospitals_list: list, all_months: set) -> dict:
    result = {}
    for m in all_months:
        all_monthly = {}
        for h in hospitals_list:
            hv = get_enabled_values_for_hospital_month(db, h.id, m)
            if hv:
                all_monthly[h.name] = {m: hv}
        if len(all_monthly) >= 2:
            try:
                comparisons = compare_hospitals(all_monthly, m)
                result[m] = [
                    {
                        "hospital_name": c.hospital,
                        "indicator": c.indicator_code,
                        "value": float(c.value) if c.value is not None else None,
                        "benchmark": float(c.benchmark) if c.benchmark is not None else None,
                        "deviation_pct": float(c.deviation_pct) if c.deviation_pct is not None else None,
                        "percentile": float(c.percentile_rank) if c.percentile_rank is not None else None,
                        "assessment": c.comparison_label,
                    }
                    for c in comparisons
                ]
            except Exception as e:
                logger.error(f"Comparison failed for month {m}: {e}")
    return result


def _run_clinical_analyses(db: Session, hospitals_list: list, hospital_months: dict) -> list:
    results = []
    for h in hospitals_list:
        for m in hospital_months.get(h.id, []):
            vals = get_enabled_values_for_hospital_month(db, h.id, m)
            if not vals:
                continue
            qs = db.query(QualityScore).filter(
                QualityScore.hospital_id == h.id,
                QualityScore.month == m,
            ).first()
            try:
                rule_failures_ = [
                    {"rule_code": vr.rule_code, "details": vr.details or "", "severity": vr.severity}
                    for vr in db.query(ValidationResult).filter(
                        ValidationResult.hospital_id == h.id,
                        ValidationResult.month == m,
                        ValidationResult.status == "FAIL",
                    ).all()
                ]
                ca = run_clinical_analysis(
                    hospital=h.name,
                    month=m,
                    values=vals,
                    quality_score=qs.score if qs else None,
                    issues=json.loads(qs.issues) if qs and qs.issues else [],
                    rule_failures=rule_failures_,
                    completeness=qs.completeness if qs else 0,
                    consistency=qs.consistency if qs else 0,
                    rule_compliance=qs.rule_compliance if qs else 0,
                    outlier_penalty=qs.outlier_penalty if qs else 0,
                )
                results.append(ca.to_dict())
            except Exception as e:
                logger.error(f"Clinical analysis failed: {h.name}/{m}: {e}")
    return results
