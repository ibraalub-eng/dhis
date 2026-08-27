"""Regional Health Intelligence API — /regional endpoints.

كل نقطة نهاية تمر عبر _get_regional_data المُذكِّرة لكل شهر (month + months_back)
حتى لا يُعاد تشغيل التجميع الإقليمي مع كل طلب/حلقة — نفس نمط _get_smart_data.
"""

import math
from datetime import datetime

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.cache import cache
from app.database import get_db
from app.engine.smart.regional import run_regional_analysis
from app.core.deps import require_permission
from app.core.error_handler import safe_endpoint

router = APIRouter(prefix="/regional", tags=["Regional Intelligence"], dependencies=[Depends(require_permission("smart_analytics.read"))])


def _sanitize(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        return 0.0 if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _get_regional_data(db: Session, month: str, months_back: int = 6) -> dict:
    cache_key = f"regional_{month}_{months_back}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    result = run_regional_analysis(db, month, months_back=months_back)
    result["generated_at"] = datetime.now().isoformat()
    result = _sanitize(result)
    cache.set(cache_key, result, ttl=300)
    return result


@router.get("/overview/{month}")
@safe_endpoint("خطأ في التحليل الإقليمي", cache_keys=["regional_{month}_{months_back}"])
def get_regional_overview(month: str, months_back: int = 6, db: Session = Depends(get_db)):
    return _get_regional_data(db, month, months_back=months_back)


@router.get("/governorates/{month}")
@safe_endpoint("خطأ في مقارنة المحافظات", cache_keys=["regional_{month}_6"])
def get_regional_governorates(month: str, db: Session = Depends(get_db)):
    data = _get_regional_data(db, month)
    return {"month": month, "governorates": data.get("governorates", []),
            "benchmarks": data.get("benchmarks", {}),
            "mortality": data.get("mortality", [])}


@router.get("/trends/{month}")
@safe_endpoint("خطأ في الاتجاهات الإقليمية", cache_keys=["regional_{month}_{months_back}"])
def get_regional_trends(month: str, months_back: int = 6, db: Session = Depends(get_db)):
    data = _get_regional_data(db, month, months_back=months_back)
    return {"month": month, "trends": data.get("trends", []),
            "months_back": months_back}
