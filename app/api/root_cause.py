from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Hospital, QualityScore, ConfidenceScore
from app.engine.root_cause import generate_root_cause_analysis, get_historical_data, get_peer_historical_data
from app.engine.pipeline import run_full_analysis
from app.core.deps import require_permission
from app.core.error_handler import safe_endpoint
import json

router = APIRouter(prefix="/root-cause", tags=["root-cause"], dependencies=[Depends(require_permission("root_cause.read"))])

# المؤشرات المصدرية الأساسية للمقارنة الزمنية (أكواد مخزنة) مع أسمائها العربية
_TIMELINE_INDICATORS = [
    ("2", "إجمالي الولادات"),
    ("6", "المواليد الأحياء"),
    ("5", "الولادات القيصرية"),
    ("10", "المضاعفات الخطيرة (SMM)"),
    ("11", "الوفيات الأمومية"),
    ("17", "وفيات المواليد"),
    ("7", "الوفيات الجنينية"),
    ("6.f", "الولادات المبكرة"),
    ("6.g", "نقص وزن الولادة"),
]


@router.get("/{hospital_id}/timeline")
def get_root_cause_timeline(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    months_back: int = Query(6, ge=2, le=12, description="Months of history to compare"),
    db: Session = Depends(get_db),
):
    """المقارنة الزمنية لكل مؤشر: قيمة المستشفى شهراً بشهر مقابل متوسط النظير.

    يبني سلسلة {month, hospital_value, peer_mean, peer_lower, peer_upper} لكل مؤشر
    مصدري مخزن — باستخدام get_historical_data (خط المستشفى) و get_peer_historical_data
    (متوسط النظير) مع فاصل ثقة 95% حول متوسط النظير.
    """
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise HTTPException(status_code=404, detail="Hospital not found")

    try:
        indicators = []
        for code, ar_name in _TIMELINE_INDICATORS:
            hist = get_historical_data(db, hospital_id, code, months_back, month=month)
            if len(hist) < 2:
                continue
            peers = get_peer_historical_data(db, hospital_id, code, months_back, month=month)

            month_peers = {}
            for pts in peers.values():
                for p in pts:
                    month_peers.setdefault(p.month, []).append(p.value)

            series = []
            for p in hist:
                pvals = month_peers.get(p.month)
                if pvals:
                    n = len(pvals)
                    mean = sum(pvals) / n
                    std = (sum((v - mean) ** 2 for v in pvals) / (n - 1)) ** 0.5 if n > 1 else 0.0
                    margin = 1.96 * std / (n ** 0.5) if n > 1 else 0.0
                    series.append({
                        "month": p.month,
                        "hospital_value": round(p.value, 2),
                        "peer_mean": round(mean, 2),
                        "peer_lower": round(max(0.0, mean - margin), 2),
                        "peer_upper": round(mean + margin, 2),
                        "peer_count": n,
                    })
                else:
                    series.append({
                        "month": p.month,
                        "hospital_value": round(p.value, 2),
                        "peer_mean": None, "peer_lower": None, "peer_upper": None, "peer_count": 0,
                    })
            indicators.append({
                "indicator_code": code,
                "indicator_name": ar_name,
                "series": series,
            })
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Timeline analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الزمني: {str(e)}")

    return {
        "hospital": hospital.name,
        "hospital_id": hospital_id,
        "month": month,
        "indicators": indicators,
    }


@router.get("/{hospital_id}")
def get_root_cause_analysis(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    include_history: bool = Query(False, description="Include historical trend analysis"),
    compare_peers: bool = Query(False, description="Include peer comparison analysis"),
    months_back: int = Query(6, description="Months of history to analyze"),
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or not hospital.is_active:
        raise HTTPException(status_code=404, detail="Hospital not found")

    quality_data = None
    confidence_data = None

    qs = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()
    if qs:
        quality_data = {
            "score": qs.score,
            "rule_compliance": qs.rule_compliance,
            "completeness": qs.completeness,
            "consistency": qs.consistency,
            "outlier_penalty": qs.outlier_penalty,
            "issues": json.loads(qs.issues) if qs.issues else [],
        }

    cs = db.query(ConfidenceScore).filter(
        ConfidenceScore.hospital_id == hospital_id,
        ConfidenceScore.month == month,
    ).first()
    if cs:
        confidence_data = {
            "overall_confidence": cs.overall_confidence,
            "level": cs.level,
            "indicators": json.loads(cs.indicators_data) if cs.indicators_data else [],
            "by_level": {
                "HIGH": cs.high_count,
                "MEDIUM": cs.medium_count,
                "LOW": cs.low_count,
                "CRITICAL": cs.critical_count,
            },
        }

    if not quality_data or not confidence_data:
        try:
            report = run_full_analysis(db, hospital_id, month)
            quality_data = {
                "score": report["data_quality_score"],
                "rule_compliance": report.get("rule_compliance", 0),
                "completeness": report.get("completeness", 0),
                "consistency": report.get("consistency", 0),
                "outlier_penalty": report.get("outlier_penalty", 0),
                "issues": report.get("issues", []),
            }
            confidence_data = report.get("confidence", {})
        except Exception:
            pass

    try:
        report = generate_root_cause_analysis(
            db, hospital_id, month,
            quality_data=quality_data,
            confidence_data=confidence_data,
            include_history=include_history,
            compare_peers=compare_peers,
            months_back=months_back,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Root cause analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"خطأ في التحليل الجذري: {str(e)}")

    response = {
        "hospital": report.hospital,
        "hospital_id": report.hospital_id,
        "month": report.month,
        "overall_quality_score": report.overall_quality_score,
        "overall_confidence": report.overall_confidence,
        "critical_issues_count": report.critical_issues_count,
        "summary": report.summary,
        "priority_actions": report.priority_actions,
        "priority_action_details": [
            {
                "action": p.action,
                "source": p.source,
                "severity": p.severity,
                "impact": p.impact,
                "effort": p.effort,
                "roi": p.roi,
            }
            for p in report.priority_action_details
        ],
        "top_rule_failures": [
            {
                "rule_code": f.rule_code,
                "description": f.rule_description,
                "severity": f.severity,
                "failure_rate": f.failure_rate,
                "primary_cause": f.primary_cause,
                "recommendation": f.recommendation,
                "primary_cause_ar": f.primary_cause_ar,
            }
            for f in report.top_rule_failures
        ],
        "quality_drivers": [
            {
                "component": d.component,
                "value": d.value,
                "impact": d.impact,
                "status": d.status,
                "recommendation": d.recommendation,
            }
            for d in report.quality_drivers
        ],
        "confidence_gaps": [
            {
                "indicator_code": g.indicator_code,
                "indicator_name": g.indicator_name,
                "confidence": g.confidence,
                "level": g.level,
                "weakest_signal": g.weakest_signal,
                "root_cause": g.root_cause,
                "recommendation": g.recommendation,
            }
            for g in report.confidence_gaps
        ],
        "anomaly_patterns": [
            {
                "rate_name": a.rate_name,
                "avg_z_score": a.avg_z_score,
                "recurrence_count": a.recurrence_count,
                "pattern_type": a.pattern_type,
                "description": a.description,
            }
            for a in report.anomaly_patterns
        ],
        "ai_recommendations": report.ai_recommendations,
    }

    if include_history or compare_peers:
        response["causal_tree"] = [
            {
                "factor": n.factor,
                "factor_type": n.factor_type,
                "current_value": n.current_value,
                "trend": n.trend,
                "trend_slope": n.trend_slope,
                "severity": n.severity,
                "history": [
                    {"month": h.month, "value": h.value}
                    for h in n.history
                ],
            }
            for n in report.causal_tree
        ]
        response["causal_chains"] = [
            {
                "root_cause": c.root_cause,
                "root_cause_arabic": c.root_cause_arabic,
                "confidence": c.confidence,
                "evidence": c.evidence,
                "affected_factors": c.affected_factors,
                "recommended_action": c.recommended_action,
                "impact_if_fixed": c.impact_if_fixed,
                "implementation_priority": c.implementation_priority,
                "chain_path": c.chain_path,
                "chain_path_arabic": c.chain_path_arabic,
            }
            for c in report.causal_chains
        ]
        response["historical_trends"] = report.historical_trends
        response["peer_comparisons"] = {
            k: {
                "indicator_code": v.indicator_code,
                "indicator_name": v.indicator_name,
                "hospital_value": v.hospital_value,
                "peer_group": v.peer_group,
                "peer_count": v.peer_count,
                "peer_mean": v.peer_mean,
                "peer_std": v.peer_std,
                "hospital_percentile": v.hospital_percentile,
                "hospital_z_score": v.hospital_z_score,
                "gap_pct": v.gap_pct,
                "peer_governorates": v.peer_governorates,
                "peer_governorate_counts": v.peer_governorate_counts,
                "peer_types": v.peer_types,
            }
            for k, v in report.peer_comparisons.items()
        }
        response["summary_arabic"] = report.summary_arabic

    return response
