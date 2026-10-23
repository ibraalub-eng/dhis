import io
import json
import statistics
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import threading
from app.database import get_db, SessionLocal
from app.tasks import create_task, run_task
from app.cache import cache
from app.models import (
    AnomalyResult,
    Hospital,
    Indicator,
    IndicatorValue,
    LayeredOutlierResult,
    QualityScore,
    ValidationResult,
)
from app.schemas import (
    DataElementOutlierOut,
    LayerScoreOut,
    PeerHospitalOut,
    PeerStatsOut,
    ReportOut,
    ReportSummaryOut,
)
from app.engine.anomaly.layered import (
    LEVELS,
    build_analysis_specs,
    is_detection_outlier,
    layer_breakdown,
)
from app.engine.pipeline import get_all_hospital_data_for_month, run_full_analysis
from app.indicators import SYNTHETIC_INDICATOR_CODES
from app.core.deps import get_current_user, get_user_hospital_ids, require_permission

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_permission("analysis.read"))])


_LAYERED_LEVEL_ORDER = {"VERY_HIGH": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3, "NONE": 4}

# The detection floor — one rule for the whole app (layered.is_detection_outlier).
OUTLIER_LEVELS = tuple(level for level in LEVELS if is_detection_outlier(level))


def _peer_statistics(values) -> dict:
    """Descriptive statistics of a peer group — the peer layer's basis.

    Same population (the group the engine scored against) and the same
    ddof=1 standard deviation as ``layered.compute_peer_layer``, so the numbers
    shown beside a peer score explain it instead of quoting a different
    baseline.
    """
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"count": 0, "mean": None, "std": None,
                "min": None, "max": None, "median": None}
    return {
        "count": len(vals),
        "mean": round(statistics.fmean(vals), 4),
        "std": round(statistics.stdev(vals), 4) if len(vals) > 1 else None,
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "median": round(statistics.median(vals), 4),
    }


def _element_peer_ids(hospital: Hospital, code: str, all_data: dict,
                      hospitals: list):
    """The comparison group the layered engine used for this element.

    `LayeredOutlierResult` stores peer_count/peer_mean but not the names, so
    they have to be rebuilt — using the SAME rule the engine applies: every
    active hospital reporting the indicator this month, minus the hospital
    itself. That is `layered.canonical_peer_tiers`, so the tooltip explains the
    stored score instead of inventing a different peer group.
    """
    id_by_name = {h.name: h.id for h in hospitals if h.name}
    unit_values = {hid: all_data.get(name, {}).get(code)
                   for name, hid in id_by_name.items()}
    members = [hid for hid, value in unit_values.items()
               if hid != hospital.id and value is not None]
    return members, unit_values


def _data_element_outliers(db: Session, hospital: Hospital, month: str):
    """Layered rows for the raw catalog elements, with their peers.

    Data elements have no entry in the AnomalyResult projection (that table
    carries the derived rates), so listing it alone made every element-level
    outlier invisible in the Quality report. These rows come from the same
    stored results the Outlier Diagnostics screen reads, so the two screens
    cannot disagree.
    """
    rows = (db.query(LayeredOutlierResult)
            .filter(LayeredOutlierResult.hospital_id == hospital.id,
                    LayeredOutlierResult.month == month)
            .all())
    if not rows:
        return []

    indicators = {ind.id: ind for ind in db.query(Indicator).all()}
    # Rate rows (rate_cs, rate_mmr, ...) have no catalog Indicator; they are
    # already covered by the AnomalyResult projection, so only data elements
    # are added here.
    elements = [r for r in rows
                if r.indicator_id in indicators
                and indicators[r.indicator_id].code not in SYNTHETIC_INDICATOR_CODES]
    if not elements:
        return []

    all_data = get_all_hospital_data_for_month(db, month)
    hospitals = (db.query(Hospital).filter(Hospital.is_active.is_(True)).all())
    names = {h.id: h.name for h in hospitals}

    items = []
    for row in elements:
        indicator = indicators[row.indicator_id]
        peer_ids, peer_values = _element_peer_ids(
            hospital, row.analysis_code, all_data, hospitals)
        items.append(DataElementOutlierOut(
            analysis_code=row.analysis_code,
            indicator_id=row.indicator_id,
            name=indicator.name,
            value=row.raw_value,
            baseline=row.historical_mean,
            z_score=row.historical_z_score,
            peer_count=row.peer_count if row.peer_count is not None else len(peer_ids),
            peer_mean=row.peer_mean,
            peer_stats=_peer_statistics(peer_values[pid] for pid in peer_ids),
            peers=[PeerHospitalOut(
                id=pid, name=names.get(pid, f"#{pid}"),
                value=(round(float(peer_values[pid]), 4)
                       if peer_values.get(pid) is not None else None))
                for pid in peer_ids],
            outlier_level=row.outlier_level,
            outlier_type=row.outlier_type,
            method=row.outlier_method,
            interpretation=row.interpretation,
            layers=layer_breakdown(row),
            is_outlier=is_detection_outlier(row.outlier_level),
            kind="element",
        ))
    items.sort(key=lambda i: (_LAYERED_LEVEL_ORDER.get(i.outlier_level or "NONE", 9),
                              i.name or ""))
    return items


def _rate_layer_context(db: Session, hospital_id: int, month: str) -> dict:
    """Lookup tables for joining an AnomalyResult row to its layered row.

    The legacy projection keeps one row per registry code while the layered
    table is keyed by analysis code, so the join needs the analysis specs:
    name first (unique for every rate but one), then the stored rate value to
    split that tie, then the registry code when the two systems agree on it.
    A row that still cannot be placed keeps `layers=[]` — an empty strip is
    honest, a guessed breakdown is not.
    """
    specs = build_analysis_specs(db)
    by_name: dict = {}
    for spec in specs:
        by_name.setdefault(spec.name, []).append(spec)
    stored = {
        r.analysis_code: r for r in
        db.query(LayeredOutlierResult).filter(
            LayeredOutlierResult.hospital_id == hospital_id,
            LayeredOutlierResult.month == month,
        ).all()
    }
    return {"by_name": by_name,
            "by_code": {spec.analysis_code: spec for spec in specs},
            "stored": stored}


def _rate_analysis_code(row, context: dict):
    """The analysis code whose layered row produced this AnomalyResult row."""
    by_name = context["by_name"]
    stored = context["stored"]
    candidates = by_name.get(row.rate_name) or []
    if len(candidates) == 1:
        return candidates[0].analysis_code
    if len(candidates) > 1:
        # Several rates share this name: the stored rate decides (the
        # projection copied it, rounded to 2 decimals).
        exact = [
            spec.analysis_code for spec in candidates
            if stored.get(spec.analysis_code) is not None
            and stored[spec.analysis_code].rate is not None
            and row.value is not None
            and round(float(stored[spec.analysis_code].rate), 2)
            == round(float(row.value), 2)
        ]
        if len(exact) == 1:
            return exact[0]
        return None
    # No spec carries this name (an older or renamed row): fall back to the
    # stored registry code, which equals the analysis code for most rates.
    spec = context["by_code"].get(row.indicator_code)
    return spec.analysis_code if spec else None


def _rate_peer_stats(row) -> dict:
    """Peer statistics for a projected rate row.

    Prefers the stored peer list (the same hospitals the score compared
    against); falls back to the peer columns written with the row, so a row
    without `peers_detail` still shows its group's spread.
    """
    values = [p.get("rate") for p in (row.peers_detail or [])
              if isinstance(p, dict) and p.get("rate") is not None]
    if values:
        return _peer_statistics(values)
    if not row.peer_count:
        return _peer_statistics([])
    return {"count": row.peer_count,
            # For a peer row the benchmark IS the peer mean.
            "mean": row.benchmark,
            "std": row.peer_std, "min": row.peer_min,
            "max": row.peer_max, "median": row.peer_median}


def _check_hospital_access(user, db: Session, hospital_id: int) -> None:
    """Raise 403 if the user is restricted and this hospital is not assigned."""
    allowed = get_user_hospital_ids(user, db)
    if allowed is not None and hospital_id not in allowed:
        raise HTTPException(status_code=403, detail="No access to this hospital")


@router.get("/", response_model=List[ReportOut])
def list_reports(
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    hospital_id: Optional[int] = Query(None, description="Filter by hospital ID"),
    source_file: Optional[str] = Query(None, description="Filter by source file name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = db.query(QualityScore)
    user_hosp_ids = get_user_hospital_ids(user, db)
    if user_hosp_ids is not None:
        query = query.filter(QualityScore.hospital_id.in_(user_hosp_ids))
    if hospital_id:
        query = query.filter(QualityScore.hospital_id == hospital_id)
    if month:
        query = query.filter(QualityScore.month == month)
    if source_file:
        file_subs = (
            db.query(IndicatorValue.hospital_id, IndicatorValue.month)
            .filter(IndicatorValue.source_file == source_file)
            .distinct()
            .subquery()
        )
        query = query.join(
            file_subs,
            (QualityScore.hospital_id == file_subs.c.hospital_id) & (QualityScore.month == file_subs.c.month),
        )
    cache_key = cache.make_key(
        # v4: card outliers are counted from the layered rows only (rates and
        # data elements), so the count matches Outlier Diagnostics.
        "reports:list_v4",
        uid=getattr(user, "id", 0),
        month=month,
        source_file=source_file,
        skip=skip,
        limit=limit,
        hospital_id=hospital_id,
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    scores = query.order_by(QualityScore.month.desc()).offset(skip).limit(limit).all()
    if not scores:
        return []

    hospital_ids = list(set(s.hospital_id for s in scores))
    hospitals = {h.id: h for h in db.query(Hospital).filter(Hospital.id.in_(hospital_ids)).all()}

    # Filter out inactive hospitals
    scores = [s for s in scores if hospitals.get(s.hospital_id) and hospitals[s.hospital_id].is_active]
    if not scores:
        return []
    hospital_ids = list(set(s.hospital_id for s in scores))

    months = list(set(s.month for s in scores))
    # Outliers come from ONE place: the layered rows (derived rates AND data
    # elements), read at the engine's own detection floor. The AnomalyResult
    # table is a projection of these rows, so counting it as well would
    # double-count the same finding.
    outlier_rows = (
        db.query(LayeredOutlierResult)
        .filter(
            LayeredOutlierResult.hospital_id.in_(hospital_ids),
            LayeredOutlierResult.month.in_(months),
            LayeredOutlierResult.outlier_level.in_(OUTLIER_LEVELS),
        )
        .all()
    )
    indicator_names = {ind.id: ind.name for ind in db.query(Indicator).all()}
    spec_names = {spec.analysis_code: spec.name
                  for spec in build_analysis_specs(db)}
    outliers_by_key: dict = {}
    for row in outlier_rows:
        is_element = row.indicator_id is not None
        name = (indicator_names.get(row.indicator_id) if is_element
                else spec_names.get(row.analysis_code))
        if not name:
            continue   # unknown code (stale row) — never show a blank card entry
        outliers_by_key.setdefault((row.hospital_id, row.month), []).append({
            "indicator": name,
            "indicator_id": f"element:{row.analysis_code}" if is_element else None,
            "formula": None,
            "formula_version": "raw" if is_element else None,
            "value": row.rate if row.rate is not None else row.raw_value,
            "benchmark": (row.peer_mean if row.peer_mean is not None
                          else row.historical_mean),
            "level": row.outlier_level,
            "kind": "element" if is_element else "rate",
        })

    # Determine enabled months per hospital
    from app.api.analysis import get_enabled_months
    enabled_by_hospital: dict = {}
    for hid in hospital_ids:
        enabled_by_hospital[hid] = set(get_enabled_months(db, hospital_id=hid))

    results = []
    for s in scores:
        hosp = hospitals.get(s.hospital_id)
        issues = json.loads(s.issues) if s.issues else []
        outliers = sorted(
            outliers_by_key.get((s.hospital_id, s.month), []),
            key=lambda o: (_LAYERED_LEVEL_ORDER.get(o["level"] or "NONE", 9),
                           o["indicator"] or ""),
        )
        is_enabled = s.month in enabled_by_hospital.get(s.hospital_id, set())
        results.append(ReportOut(
            hospital=hosp.name if hosp else "Unknown",
            month=s.month,
            data_quality_score=s.score,
            rule_compliance=s.rule_compliance,
            completeness=s.completeness,
            consistency=s.consistency,
            outlier_penalty=s.outlier_penalty,
            issues=issues,
            outliers=outliers,
            is_enabled=is_enabled,
        ))
    cache.set(cache_key, results)
    return results


@router.get("/generate/{hospital_id}", response_model=ReportOut)
def generate_report(hospital_id: int, month: str = Query(..., description="Month YYYY-MM"), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _check_hospital_access(user, db, hospital_id)
    try:
        report = run_full_analysis(db, hospital_id, month)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ReportOut(**report)


@router.post("/generate/{hospital_id}", dependencies=[Depends(require_permission("reports.export"))])
def generate_report_background(
    hospital_id: int,
    month: str = Query(..., description="Month YYYY-MM"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _check_hospital_access(user, db, hospital_id)
    task_id = create_task("Generate Report", lambda: None)

    def _run(tid, hid, m):
        bg_db = SessionLocal()
        try:
            from app.engine.pipeline import run_full_analysis
            from app.tasks import set_progress, set_status
            set_progress(tid, 50)
            run_full_analysis(bg_db, hid, m)
            set_progress(tid, 100)
            set_status(tid, "done")
        except Exception as e:
            from app.tasks import set_status
            set_status(tid, "error")
            raise e
        finally:
            bg_db.close()

    if background_tasks is not None:
        background_tasks.add_task(run_task, task_id, _run, task_id, hospital_id, month)
    else:
        threading.Thread(target=run_task, args=(task_id, _run, task_id, hospital_id, month), daemon=True).start()

    return {"task_id": task_id, "message": f"Report generation started. Use /tasks/{task_id} to check status."}


@router.get("/detail/{hospital_id}", response_model=ReportSummaryOut)
def detailed_report(hospital_id: int, month: str = Query(..., description="Month YYYY-MM"), db: Session = Depends(get_db), user=Depends(get_current_user)):
    _check_hospital_access(user, db, hospital_id)
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Read stored score from database (consistent with list endpoint)
    qs = db.query(QualityScore).filter(
        QualityScore.hospital_id == hospital_id,
        QualityScore.month == month,
    ).first()
    if not qs:
        # Run analysis if no stored score exists
        try:
            report = run_full_analysis(db, hospital_id, month, force=True)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        data_quality_score = report["data_quality_score"]
        rule_compliance = report.get("rule_compliance")
        completeness = report.get("completeness")
        consistency = report.get("consistency")
        outlier_penalty = report.get("outlier_penalty")
        issues = report["issues"]
        confidence = report.get("confidence")
    else:
        data_quality_score = qs.score
        rule_compliance = qs.rule_compliance
        completeness = qs.completeness
        consistency = qs.consistency
        outlier_penalty = qs.outlier_penalty
        issues = json.loads(qs.issues) if qs.issues else []
        confidence = None

    validation_rows = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.month == month,
    ).all()
    anomaly_rows = db.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == hospital_id,
        AnomalyResult.month == month,
    ).all()

    # Every anomaly row is a stored result: attach the live registry unit and
    # verify the formula version it was computed with. The Quality tab must
    # never present an outdated value as if it were current, and it must not
    # guess a unit from the number.
    from app.engine import indicator_service
    from app.schemas import AnomalyOut

    # Every row carries the layer scores that produced it. Rates read them from
    # the layered row the projection copied; the join is resolved once above.
    layer_context = _rate_layer_context(db, hospital_id, month)

    anomaly_items = []
    for row in anomaly_rows:
        item = AnomalyOut.model_validate(row)
        provenance = indicator_service.registry_provenance(
            db, row.indicator_id, row.formula_version, row.formula)
        item.unit = provenance["unit"]
        item.formula_status = provenance["formula_status"]
        item.current_formula_version = provenance["current_formula_version"]
        if not item.formula:
            item.formula = provenance["formula"]
        analysis_code = _rate_analysis_code(row, layer_context)
        if analysis_code is not None:
            item.layers = [
                LayerScoreOut(**layer) for layer in
                layer_breakdown(layer_context["stored"].get(analysis_code))]
        item.peer_stats = PeerStatsOut(**_rate_peer_stats(row))
        anomaly_items.append(item)

    return ReportSummaryOut(
        hospital=hosp.name,
        month=month,
        data_quality_score=data_quality_score,
        rule_compliance=rule_compliance,
        completeness=completeness,
        consistency=consistency,
        outlier_penalty=outlier_penalty,
        issues=issues,
        validation_results=validation_rows,
        anomaly_results=anomaly_items,
        layered_results=_data_element_outliers(db, hosp, month),
        confidence=confidence,
    )


@router.get("/from-file/{source_file}", response_model=List[ReportOut])
def reports_from_file(source_file: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    user_hosp_ids = get_user_hospital_ids(user, db)
    values = (
        db.query(IndicatorValue)
        .filter(IndicatorValue.source_file == source_file)
        .all()
    )
    if user_hosp_ids is not None:
        values = [v for v in values if v.hospital_id in user_hosp_ids]
    if not values:
        raise HTTPException(status_code=404, detail=f"No data found for file: {source_file}")

    hospital_months = set()
    for v in values:
        hospital_months.add((v.hospital_id, v.month))

    reports = []
    for hospital_id, month in sorted(hospital_months):
        try:
            report = run_full_analysis(db, hospital_id, month)
            reports.append(report)
        except Exception:
            pass
    return reports


def _get_export_data(db: Session, hospital_id: int, month: str, user=None) -> dict:
    if user is not None:
        _check_hospital_access(user, db, hospital_id)
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    try:
        report = run_full_analysis(db, hospital_id, month)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    vrows = db.query(ValidationResult).filter(
        ValidationResult.hospital_id == hospital_id,
        ValidationResult.month == month,
    ).all()
    arows = db.query(AnomalyResult).filter(
        AnomalyResult.hospital_id == hospital_id,
        AnomalyResult.month == month,
    ).all()
    from app.engine import indicator_service

    anomaly_provenance = {
        a.id: indicator_service.registry_provenance(
            db, a.indicator_id, a.formula_version, a.formula)
        for a in arows
    }
    return {
        "hospital": hosp.name,
        "month": month,
        "report": report,
        "validations": vrows,
        "anomalies": arows,
        "anomaly_provenance": anomaly_provenance,
    }


def _esc(text: str) -> str:
    s = str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return "".join(ch if ord(ch) < 128 else f"&#{ord(ch)};" for ch in s)


def _register_unicode_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os as _os
    candidates = [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for p in candidates:
        if _os.path.exists(p):
            try:
                pdfmetrics.registerFont(TTFont("UniFont", p))
                return "UniFont"
            except Exception:
                continue
    return None


@router.get("/export/{hospital_id}/pdf")
def export_report_pdf(hospital_id: int, month: str = Query(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    try:
        d = _get_export_data(db, hospital_id, month, user=user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load report data: {e}")
    try:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=20*mm)
        styles = getSampleStyleSheet()
        story = []

        uni_name = _register_unicode_font()
        if uni_name:
            for s in styles.byName.values():
                s.fontName = uni_name

        story.append(Paragraph(f"<b>{_esc(d['hospital'])}</b>", styles["Title"]))
        story.append(Paragraph(f"Monthly Quality Report &mdash; {_esc(d['month'])}", styles["Normal"]))
        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a237e")))
        story.append(Spacer(1, 4*mm))

        r = d["report"]
        score = r.get("data_quality_score")
        if score is None:
            # A missing score is not zero — report it as unavailable.
            score_display = "--/100"
            score_color = colors.HexColor("#777777")
        else:
            score_display = f"{score:.0f}/100"
            score_color = colors.HexColor("#2e7d32") if score >= 80 else colors.HexColor("#e65100") if score >= 50 else colors.HexColor("#c62828")

        sc_style = ParagraphStyle("Score", parent=styles["Normal"], fontSize=28, textColor=score_color, alignment=1)
        if uni_name:
            sc_style.fontName = uni_name
        story.append(Paragraph(score_display, sc_style))
        story.append(Spacer(1, 3*mm))

        sub_data = [
            ["Metric", "Value"],
            ["Validation rule", f"{r.get('rule_compliance', 0):.1f}%" if r.get('rule_compliance') is not None else "--"],
            ["Completeness", f"{r.get('completeness', 0):.1f}%" if r.get('completeness') is not None else "--"],
            ["Consistency", f"{r.get('consistency', 0):.1f}%" if r.get('consistency') is not None else "--"],
            ["Outlier Penalty", f"{r.get('outlier_penalty', 0):.2f}" if r.get('outlier_penalty') is not None else "--"],
        ]
        t = Table(sub_data, colWidths=[120, 80])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (1, 1), (1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ]))
        story.append(t)
        story.append(Spacer(1, 4*mm))

        issues = r.get("issues", [])
        if issues:
            story.append(Paragraph("<b>Issues Found</b>", styles["Heading2"]))
            for iss in issues:
                story.append(Paragraph(f"&bull; {_esc(iss)}", styles["Normal"]))
            story.append(Spacer(1, 3*mm))

        vrows = d["validations"]
        story.append(Paragraph(f"<b>Validation Results ({len(vrows)})</b>", styles["Heading2"]))
        vdata = [["Code", "Description", "Status", "Severity", "Details"]]
        fails = 0
        for v in vrows:
            vdata.append([
                _esc(v.rule_code),
                _esc(v.rule_description)[:40],
                v.status,
                v.severity,
                _esc(v.details or "")[:50],
            ])
            if v.status == "FAIL":
                fails += 1
        vt = Table(vdata, colWidths=[40, 100, 40, 40, 100], repeatRows=1)
        vt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ALIGN", (2, 1), (3, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(vt)
        story.append(Spacer(1, 2*mm))

        arows = d["anomalies"]
        provenance = d.get("anomaly_provenance", {})
        story.append(Paragraph(f"<b>Anomaly Detection ({len(arows)})</b>", styles["Heading2"]))
        adata = [["Rate", "Value", "Benchmark", "Z-Score", "Unit", "Formula", "Outlier"]]
        outlier_count = 0
        for a in arows:
            prov = provenance.get(a.id, {})
            adata.append([
                _esc(a.rate_name),
                f"{a.value:.2f}" if a.value is not None else "--",
                f"{a.benchmark:.2f}" if a.benchmark is not None else "--",
                f"{a.z_score:.2f}" if a.z_score is not None else "--",
                _esc(prov.get("unit") or "--"),
                _esc(prov.get("formula_status") or "--"),
                "Yes" if a.is_outlier else "No",
            ])
            if a.is_outlier:
                outlier_count += 1
        at = Table(adata, colWidths=[120, 50, 55, 45, 70, 80, 40], repeatRows=1)
        at.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(at)
        story.append(Spacer(1, 4*mm))

        style_footer = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
        if uni_name:
            style_footer.fontName = uni_name
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Paragraph(f"Generated by HEALTH-ai | {datetime.now().strftime('%Y-%m-%d %H:%M')} | {fails} failures, {outlier_count} outliers", style_footer))

        doc.build(story)
        buf.seek(0)
        filename = f"report_{d['hospital']}_{d['month']}.pdf".replace(" ", "_")
        return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


@router.get("/export/{hospital_id}/excel")
def export_report_excel(hospital_id: int, month: str = Query(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    d = _get_export_data(db, hospital_id, month, user=user)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Quality Report"

    hdr_font = Font(bold=True, color="FFFFFF", size=11)
    hdr_fill = PatternFill(start_color="1A237E", end_color="1A237E", fill_type="solid")
    thin = Side(style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    r = d["report"]
    hospital_name = d["hospital"]
    report_month = d["month"]
    issues = r.get("issues", [])
    vrows = d["validations"]
    arows = d["anomalies"]
    anomaly_provenance = d.get("anomaly_provenance", {})

    row = 1
    ws.cell(row, 1, f"Quality Report - {hospital_name}").font = Font(bold=True, size=14, color="1A237E")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    row += 1
    ws.cell(row, 1, report_month).font = Font(size=11, color="888888")
    row += 2

    ws.cell(row, 1, "Metric").font = hdr_font
    ws.cell(row, 1).fill = hdr_fill
    ws.cell(row, 2, "Value").font = hdr_font
    ws.cell(row, 2).fill = hdr_fill
    for c in [ws.cell(row, 1), ws.cell(row, 2)]:
        c.border = border
        c.alignment = Alignment(horizontal="center")
    row += 1
    for label, key in [("Data Quality Score", "data_quality_score"), ("Validation rule", "rule_compliance"),
                        ("Completeness", "completeness"), ("Consistency", "consistency"),
                        ("Outlier Penalty", "outlier_penalty")]:
        val = r.get(key)
        if val is not None:
            disp = f"{val:.1f}%" if key != "data_quality_score" else f"{val:.2f}"
            if key == "data_quality_score":
                disp = f"{val:.0f}/100"
        else:
            disp = "--"
        ws.cell(row, 1, label).border = border
        ws.cell(row, 2, disp).border = border
        ws.cell(row, 2).alignment = Alignment(horizontal="center")
        row += 1

    row += 1
    # Issues
    ws.cell(row, 1, "Issues Found").font = hdr_font
    ws.cell(row, 1).fill = hdr_fill
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    ws.cell(row, 1).border = border
    row += 1
    if issues:
        for iss in issues:
            ws.cell(row, 1, iss).border = border
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
            row += 1
    else:
        ws.cell(row, 1, "No issues found").border = border
        row += 1

    row += 1
    # Validation Results
    ws.cell(row, 1, "Validation Results").font = hdr_font
    ws.cell(row, 1).fill = hdr_fill
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    ws.cell(row, 1).border = border
    row += 1
    for col, h in enumerate(["Code", "Description", "Status", "Severity", "Details"], 1):
        c = ws.cell(row, col, h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = border
        c.alignment = Alignment(horizontal="center")
    row += 1
    for v in vrows:
        ws.cell(row, 1, v.rule_code).border = border
        ws.cell(row, 2, v.rule_description).border = border
        sc = ws.cell(row, 3, v.status)
        sc.border = border
        sc.alignment = Alignment(horizontal="center")
        if v.status == "FAIL":
            sc.font = Font(color="C62828", bold=True)
        else:
            sc.font = Font(color="2E7D32")
        ws.cell(row, 4, v.severity).border = border
        ws.cell(row, 4).alignment = Alignment(horizontal="center")
        ws.cell(row, 5, v.details or "").border = border
        row += 1

    row += 1
    # Anomalies
    ws.cell(row, 1, "Anomaly Detection").font = hdr_font
    ws.cell(row, 1).fill = hdr_fill
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
    ws.cell(row, 1).border = border
    row += 1
    anomaly_headers = ["Rate Name", "Value", "Benchmark", "Z-Score", "Unit", "Formula", "Outlier"]
    for col, h in enumerate(anomaly_headers, 1):
        c = ws.cell(row, col, h)
        c.font = hdr_font
        c.fill = hdr_fill
        c.border = border
        c.alignment = Alignment(horizontal="center")
    row += 1
    for a in arows:
        prov = anomaly_provenance.get(a.id, {})
        ws.cell(row, 1, a.rate_name).border = border
        ws.cell(row, 2, f"{a.value:.2f}" if a.value is not None else "--").border = border
        ws.cell(row, 2).alignment = Alignment(horizontal="center")
        ws.cell(row, 3, f"{a.benchmark:.2f}" if a.benchmark is not None else "--").border = border
        ws.cell(row, 3).alignment = Alignment(horizontal="center")
        ws.cell(row, 4, f"{a.z_score:.2f}" if a.z_score is not None else "--").border = border
        ws.cell(row, 4).alignment = Alignment(horizontal="center")
        ws.cell(row, 5, prov.get("unit") or "--").border = border
        ws.cell(row, 5).alignment = Alignment(horizontal="center")
        status_cell = ws.cell(row, 6, prov.get("formula_status") or "--")
        status_cell.border = border
        status_cell.alignment = Alignment(horizontal="center")
        if prov.get("formula_status") not in (None, "current"):
            status_cell.font = Font(color="E65100", bold=True)
        oc = ws.cell(row, 7, "Yes" if a.is_outlier else "No")
        oc.border = border
        oc.alignment = Alignment(horizontal="center")
        if a.is_outlier:
            oc.font = Font(color="C62828", bold=True)
        row += 1

    # Column widths
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 40
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 16
    ws.column_dimensions["G"].width = 12

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"report_{hospital_name}_{report_month}.xlsx".replace(" ", "_")
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})