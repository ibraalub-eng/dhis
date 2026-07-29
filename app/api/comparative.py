from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.engine.comparative import generate_comprehensive_report, perform_advanced_comparison

router = APIRouter(prefix="/comparative", tags=["Comparative Analysis"])


@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(
    month: str,
    lang: str = Query("ar", description="لغة التقرير (ar/en)"),
    db: Session = Depends(get_db)
):
    """توليد تقرير ذكي شامل"""
    try:
        result = generate_comprehensive_report(db, month, lang)
        return result
    except Exception as e:
        error_msg = f"Error generating report: {str(e)}" if lang == "en" else f"خطأ في توليد التقرير: {str(e)}"
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/advanced-comparison/{month}")
def get_advanced_comparison(
    month: str,
    hospital_id: str = Query(None, description="معرف المستشفى (اختياري)"),
    comparison_type: str = Query("all", description="نوع المقارنة (all/governorate/type)"),
    db: Session = Depends(get_db)
):
    """مقارنة متقدمة للمستشفيات"""
    try:
        result = perform_advanced_comparison(db, month, hospital_id, comparison_type)
        return {
            "month": result.month,
            "comparison_data": {
                "trends": [{"hospital_id": t.hospital_id, "hospital_name": t.hospital_name, "months": t.months, "values": t.values} for t in result.trends],
                "peer_comparison": [{"hospital_id": p.hospital_id, "hospital_name": p.hospital_name, "percentile": p.percentile, "rank": p.rank, "total_hospitals": p.total_hospitals, "comparison_label": p.comparison_label} for p in result.peer_comparisons],
                "predictions": result.predictions
            },
            "chart_config": result.chart_config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في المقارنة: {str(e)}")
