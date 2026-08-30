from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.engine.comparative import generate_comprehensive_report, perform_advanced_comparison
from app.core.deps import require_permission, get_current_user
from app.models import SystemSetting

router = APIRouter(prefix="/comparative", tags=["Comparative Analysis"], dependencies=[Depends(require_permission("smart_analytics.read"))])


@router.get("/comprehensive-report/{month}")
def get_comprehensive_report(
    month: str,
    lang: str = Query("en", description="Report language (ar/en)"),
    force: bool = Query(False, description="Force regenerate report"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """توليد تقرير ذكي شامل"""
    hide_row = db.query(SystemSetting).filter(SystemSetting.key == "hide_explanatory_text").first()
    hide_explanations = (hide_row.value == "true") if hide_row else False
    can_view = bool(user.is_superuser) or not hide_explanations
    try:
        result = generate_comprehensive_report(db, month, lang, use_cache=not force, include_explanations=can_view)
        result["can_view_explanations"] = can_view
        return result
    except Exception as e:
        error_msg = f"Error generating report: {str(e)}" if lang == "en" else f"خطأ في توليد التقرير: {str(e)}"
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/advanced-comparison/{month}")
def get_advanced_comparison(
    month: str,
    hospital_id: str = Query(None, description="معرف المستشفى (اختياري)"),
    comparison_type: str = Query("all", description="نوع المقارنة (all/governorate/type)"),
    lang: str = Query("en", description="Results language (ar/en)"),
    db: Session = Depends(get_db)
):
    """مقارنة متقدمة للمستشفيات"""
    try:
        result = perform_advanced_comparison(db, month, hospital_id, comparison_type, lang=lang)
        return {
            "month": result.month,
            "comparison_data": {
                "trends": [{"hospital_id": t.hospital_id, "hospital_name": t.hospital_name, "months": t.months, "values": t.values} for t in result.trends],
                "peer_comparison": [{"hospital_id": p.hospital_id, "hospital_name": p.hospital_name, "percentile": p.percentile, "rank": p.rank, "total_hospitals": p.total_hospitals, "comparison_label": p.comparison_label, "anomaly_score": p.anomaly_score} for p in result.peer_comparisons],
                "predictions": result.predictions
            },
            "chart_config": result.chart_config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ في المقارنة: {str(e)}")
