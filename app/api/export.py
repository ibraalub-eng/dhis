import io
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.engine.export import build_full_export, NoDataError

router = APIRouter(prefix="/export", tags=["Export"])


@router.get("/full-data")
def export_full_data(
    month: str = Query(..., description="الشهر (YYYY-MM) أو all"),
    lang: str = Query("ar", description="لغة التقرير (ar/en)", pattern="^(ar|en)$"),
    db: Session = Depends(get_db),
):
    """تصدير البيانات الكاملة كملف JSON"""
    try:
        payload = build_full_export(db, month, lang)
    except NoDataError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في التصدير: {str(e)}")

    filename = f"health_export_{datetime.now().strftime('%Y-%m-%d')}.json"
    content = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
