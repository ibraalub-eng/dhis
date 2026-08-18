import os
import shutil
import io
import json
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.utils.excel_parser import process_excel_upload, parse_excel, normalize_data
from app.engine.pipeline import run_full_analysis
from app.schemas import UploadResponse, AutoReportResponse
from app.indicators import INDICATOR_FLAT_LIST
from app.models import IndicatorValue, Indicator, Hospital
from app.cache import cache
from app.engine.comparative.report_cache import invalidate_report_cache
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".xlsm", ".xlsb"}


@router.get("/template")
def download_template():
    import openpyxl
    top_inds = [ind for ind in INDICATOR_FLAT_LIST if ind["level"] == 0]
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


@router.post("/preview")
def preview_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported extension: {ext}")
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
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
def data_entry_options(db: Session = Depends(get_db)):
    hospitals = db.query(Hospital).order_by(Hospital.name).all()
    top_indicators = [ind for ind in INDICATOR_FLAT_LIST if ind["level"] == 0]
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
    cache.invalidate("smart_overview_")
    cache.invalidate("smart_anomalies_")
    cache.invalidate("smart_clusters_")
    cache.invalidate("smart_correlations_")
    cache.invalidate("smart_residuals_")
    cache.invalidate("smart_stratified_")
    cache.invalidate("smart_geo_")
    cache.invalidate("smart_timeline")
    invalidate_report_cache(db, month)
    return {"message": f"Saved {saved} values for {hospital.name} / {month}", "hospital": hospital.name, "month": month, "values_saved": saved}


@router.post("/", response_model=UploadResponse)
async def upload_excel(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' not supported. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    upload_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "uploads"
    )
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        os.remove(file_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes)")
    logger.info(f"Uploaded file: {file.filename} ({file_size} bytes)")
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
    cache.invalidate("smart_overview_")
    cache.invalidate("smart_anomalies_")
    cache.invalidate("smart_clusters_")
    cache.invalidate("smart_correlations_")
    cache.invalidate("smart_residuals_")
    cache.invalidate("smart_stratified_")
    cache.invalidate("smart_geo_")
    cache.invalidate("smart_timeline")
    invalidate_report_cache(db)
    return UploadResponse(**result)


@router.post("/analyze", response_model=AutoReportResponse)
async def upload_and_analyze(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' not supported. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    upload_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "uploads"
    )
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        os.remove(file_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes)")

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

    cache.invalidate("smart_overview_")
    cache.invalidate("smart_anomalies_")
    cache.invalidate("smart_clusters_")
    cache.invalidate("smart_correlations_")
    cache.invalidate("smart_residuals_")
    cache.invalidate("smart_stratified_")
    cache.invalidate("smart_geo_")
    cache.invalidate("smart_timeline")
    invalidate_report_cache(db)

    hospitals = result["hospitals"]
    months = result["months"]
    reports = []
    for hosp in hospitals:
        for month in months:
            try:
                report = run_full_analysis(db, hosp["id"], month)
                reports.append(report)
            except Exception as e:
                logger.warning(f"Could not analyze {hosp['name']} / {month}: {e}")

    return AutoReportResponse(
        filename=result["filename"],
        hospitals=hospitals,
        months=months,
        reports=reports,
    )