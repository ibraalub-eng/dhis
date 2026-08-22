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
from app.config import UPLOAD_DIR
from app.schemas import MultiFileUploadResponse
import os
import shutil
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".xlsm", ".xlsb"}


@router.get("/saved-files")
def list_saved_files(db: Session = Depends(get_db)):
    upload_dir = UPLOAD_DIR
    if not os.path.exists(upload_dir):
        return []
    files = []
    for fname in os.listdir(upload_dir):
        fpath = os.path.join(upload_dir, fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue
        stat = os.stat(fpath)
        existing_count = db.query(IndicatorValue).filter(
            IndicatorValue.source_file == fname
        ).count()
        files.append({
            "filename": fname,
            "size_kb": round(stat.st_size / 1024, 1),
            "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "records_in_db": existing_count,
        })
    files.sort(key=lambda f: f["last_modified"], reverse=True)
    return files


@router.post("/analyze-saved")
async def analyze_saved_files(
    filenames: List[str] = Query(..., description="List of filenames to analyze"),
    db: Session = Depends(get_db),
):
    upload_dir = UPLOAD_DIR
    total_rows = 0
    all_months = set()
    all_hospital_ids = set()
    processed_files = 0

    for fname in filenames:
        fpath = os.path.join(upload_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            result = process_excel_upload(fpath, db)
            total_rows += result.get("rows_imported", 0)
            if result.get("months"):
                all_months.update(result["months"])
            if result.get("hospitals"):
                for h in result["hospitals"]:
                    all_hospital_ids.add(h["id"])
            processed_files += 1
        except Exception as e:
            logger.error(f"Error processing saved file {fname}: {e}")
            continue

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
    filenames = body.get("filenames", [])
    upload_dir = UPLOAD_DIR
    deleted = 0
    for fname in filenames:
        fpath = os.path.join(upload_dir, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
            deleted += 1
    return {"message": f"Deleted {deleted} file(s).", "deleted": deleted}


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
def process_preview_file(filename: str = Query(...)):
    """Start processing in background — returns task_id immediately.

    Frontend polls GET /tasks/{task_id} until status is "done".
    """
    upload_dir = UPLOAD_DIR
    file_path = os.path.join(upload_dir, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

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
