from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.engine.comparative import generate_comprehensive_report

router = APIRouter(prefix="/comparative", tags=["Comparative Analysis"])


@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(month: str, db: Session = Depends(get_db)):
    """توليد تقرير ذكي شامل"""
    try:
        result = generate_comprehensive_report(db, month)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في توليد التقرير: {str(e)}")
