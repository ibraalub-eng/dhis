from sqlalchemy.orm import Session
from .calculation_steps import get_calculation_steps
from .benchmark import get_benchmark
from .data_auditor import get_data_audit


def generate_audit_report(db: Session, hospital_id: int, month: str) -> dict:
    steps = get_calculation_steps(db, hospital_id, month)
    if "error" in steps:
        return steps
    bench = get_benchmark(db, hospital_id, month)
    audit = get_data_audit(db, hospital_id, month)

    return {
        "hospital": steps.get("hospital"),
        "month": steps.get("month"),
        "calculation_steps": steps,
        "benchmark_comparison": bench,
        "data_auditor": audit,
        "verification": _verify_calculations(steps, audit),
    }


def _verify_calculations(steps, audit):
    checks = []
    qs_steps = steps.get("quality_score", {})
    qs_audit = audit.get("quality_score", {})
    if qs_steps and qs_audit:
        s_score = qs_steps.get("final_score")
        a_score = qs_audit.get("score")
        if s_score is not None and a_score is not None:
            match = abs(s_score - a_score) < 0.01
            checks.append({
                "check": "Quality Score Consistency",
                "expected": s_score,
                "found": a_score,
                "status": "verified" if match else "mismatch",
            })
    return {"checks": checks, "all_passed": all(c["status"] == "verified" for c in checks)}
