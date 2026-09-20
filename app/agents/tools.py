"""Read-only agent tool registry. Scope enforcement is server-side."""
import json
import re
import statistics

from app.core.deps import get_user_hospital_ids
from app.engine.smart import _load_hospital_data
from app.models import Hospital, QualityScore, ValidationResult, AnomalyResult, ClinicalInsight

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
MAX_ROWS = 20
MAX_CHARS = 4000
MAX_HOSPITALS = 20
MAX_INDICATORS = 10
DERIVED = {"cs_rate": ("2", "5")}  # derived from stored codes in _load_hospital_data


class _InvalidArg(ValueError):
    pass


def _valid_month(month):
    m = MONTH_RE.match(str(month))
    if m is None:
        return False
    return 1 <= int(m.group(2)) <= 12


class ToolContext:
    def __init__(self, db, user, month):
        self.db = db
        self.user = user
        self.month = month
        self._data = None
        self._quality = {}
        self._rules = {}
        self._anomalies = {}
        self._clinical = {}
        if getattr(user, "is_superuser", False):
            self.authorized_ids = [h.id for h in db.query(Hospital).filter(Hospital.is_active).all()]
        else:
            self.authorized_ids = get_user_hospital_ids(user, db) or \
                [h.id for h in db.query(Hospital).filter(Hospital.is_active).all()]

    def allowed_hospital_ids(self, requested):
        try:
            wanted = [int(i) for i in (requested or [])]
        except (TypeError, ValueError):
            raise _InvalidArg("hospital_ids must be a list of integers")
        allowed = [i for i in wanted if i in self.authorized_ids]
        denied = [i for i in wanted if i not in self.authorized_ids]
        return allowed, denied

    def hospital_data(self):
        if self._data is None:
            data = _load_hospital_data(self.db, self.month)
            flattened = {}
            for name, row in data.items():
                if row.get("hospital_id") not in self.authorized_ids:
                    continue
                flat = dict(row.get("values") or {})
                flat["hospital_id"] = row["hospital_id"]
                flattened[name] = flat
            self._data = flattened
        return self._data

    def quality_row(self, hid):
        if hid not in self._quality:
            self._quality[hid] = self.db.query(QualityScore).filter(
                QualityScore.hospital_id == hid, QualityScore.month == self.month).first()
        return self._quality[hid]

    def rule_rows(self, hid):
        if hid not in self._rules:
            self._rules[hid] = self.db.query(ValidationResult).filter(
                ValidationResult.hospital_id == hid,
                ValidationResult.month == self.month).all()
        return self._rules[hid]

    def anomaly_rows(self, hid):
        if hid not in self._anomalies:
            self._anomalies[hid] = self.db.query(AnomalyResult).filter(
                AnomalyResult.hospital_id == hid,
                AnomalyResult.month == self.month,
                AnomalyResult.is_outlier.is_(True)).all()
        return self._anomalies[hid]

    def clinical_row(self, hid):
        if hid not in self._clinical:
            self._clinical[hid] = self.db.query(ClinicalInsight).filter(
                ClinicalInsight.hospital_id == hid,
                ClinicalInsight.month == self.month).first()
        return self._clinical[hid]

    def indicator_history(self, hid, code, months=6):
        from app.models import Indicator, IndicatorValue
        ind = self.db.query(Indicator).filter(Indicator.code == code).first()
        if ind is None:
            return []
        rows = self.db.query(IndicatorValue).filter(
            IndicatorValue.hospital_id == hid,
            IndicatorValue.indicator_id == ind.id,
        ).order_by(IndicatorValue.month.desc()).limit(months).all()
        return [{"month": r.month, "value": round(float(r.value), 2) if r.value is not None else None}
                for r in rows]

    def peer_stats(self, code, include_ids, exclude_ids=()):
        vals = []
        for name, row in self.hospital_data().items():
            hid = row.get("hospital_id")
            if hid in exclude_ids or hid not in include_ids:
                continue
            v = row.get(code)
            if v is not None:
                vals.append(v)
        if not vals:
            return {}
        return {"mean": round(statistics.mean(vals), 2),
                "median": round(statistics.median(vals), 2),
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "count": len(vals)}


def _is_known_code(db, code):
    from app.models import Indicator
    return db.query(Indicator).filter(Indicator.code == code).first() is not None


def _derived_history(db, hid, code, months=6):
    from app.models import Indicator, IndicatorValue
    src_codes = DERIVED[code]
    inds = db.query(Indicator).filter(Indicator.code.in_(src_codes)).all()
    id_to_code = {ind.id: ind.code for ind in inds}
    if not all(c in id_to_code.values() for c in src_codes):
        return []
    month_rows = db.query(IndicatorValue.month).filter(
        IndicatorValue.hospital_id == hid,
        IndicatorValue.indicator_id.in_(id_to_code),
    ).distinct().order_by(IndicatorValue.month.desc()).limit(months).all()
    month_list = [m[0] for m in month_rows]
    rows = db.query(IndicatorValue).filter(
        IndicatorValue.hospital_id == hid,
        IndicatorValue.indicator_id.in_(id_to_code),
        IndicatorValue.month.in_(month_list),
    ).all()
    by_month = {}
    for r in rows:
        by_month.setdefault(r.month, {})[id_to_code[r.indicator_id]] = r.value
    out = []
    for m in month_list:
        pair = by_month.get(m, {})
        total = pair.get(src_codes[0])
        cs = pair.get(src_codes[1])
        if total is not None and cs is not None and total > 0:
            out.append({"month": m, "value": round(cs / total * 100, 2)})
    return out


def _cap(rows, max_rows=MAX_ROWS, max_chars=MAX_CHARS):
    out = (rows or [])[:max_rows]
    text = json.dumps(out, ensure_ascii=False)
    return out if len(text) <= max_chars else out[:10]


def _list_accessible_hospitals(ctx, args):
    rows = [{"id": r.id, "name": r.name, "region": r.region}
            for r in ctx.db.query(Hospital).filter(Hospital.id.in_(ctx.authorized_ids)).all()]
    return {"ok": True, "data": _cap(rows)}


def _get_indicator_values(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied and not allowed:
        return {"ok": False, "error": "ACCESS_DENIED"}
    if not allowed:
        return {"ok": False, "error": "validation: hospital_ids must be non-empty"}
    indicators = (args.get("indicators") or [])[:MAX_INDICATORS]
    rows = []
    for name, row in ctx.hospital_data().items():
        if row.get("hospital_id") not in allowed:
            continue
        if indicators:
            vals = {k: round(v, 2) for k, v in row.items()
                    if k != "hospital_id" and k in indicators and v is not None}
        else:
            vals = {k: round(v, 2) for k, v in row.items() if k != "hospital_id" and v is not None}
        rows.append({"hospital_id": row["hospital_id"], "hospital": name, "values": vals})
    return {"ok": True, "data": _cap(rows)}


def _get_quality_score(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied and not allowed:
        return {"ok": False, "error": "ACCESS_DENIED"}
    rows = []
    for hid in allowed[:MAX_HOSPITALS]:
        row = ctx.quality_row(hid)
        rows.append({
            "hospital_id": hid,
            "score": round(row.score, 2) if row else None,
            "rule_compliance": round(row.rule_compliance, 2) if row and row.rule_compliance is not None else None,
            "completeness": round(row.completeness, 2) if row and row.completeness is not None else None,
            "consistency": round(row.consistency, 2) if row and row.consistency is not None else None,
        })
    return {"ok": True, "data": _cap(rows)}


def _get_rule_results(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied and not allowed:
        return {"ok": False, "error": "ACCESS_DENIED"}
    status = args.get("status")
    rows = []
    for hid in allowed[:MAX_HOSPITALS]:
        for r in ctx.rule_rows(hid):
            if status and r.status != status:
                continue
            rows.append({"hospital_id": hid, "rule_code": r.rule_code,
                         "description": r.rule_description, "status": r.status,
                         "severity": r.severity})
    return {"ok": True, "data": _cap(rows, max_rows=MAX_ROWS)}


def _get_anomalies(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied and not allowed:
        return {"ok": False, "error": "ACCESS_DENIED"}
    rows = []
    for hid in allowed[:MAX_HOSPITALS]:
        for a in ctx.anomaly_rows(hid):
            rows.append({"hospital_id": hid, "indicator": a.rate_name,
                         "value": round(a.value, 2) if a.value is not None else None,
                         "benchmark": round(a.benchmark, 2) if a.benchmark is not None else None,
                         "z_score": round(a.z_score, 2) if a.z_score is not None else None})
    return {"ok": True, "data": _cap(rows)}


def _get_clinical_profile(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied and not allowed:
        return {"ok": False, "error": "ACCESS_DENIED"}
    rows = []
    for hid in allowed[:MAX_HOSPITALS]:
        row = ctx.clinical_row(hid)
        payload = {"hospital_id": hid}
        if row:
            try:
                payload["profile"] = json.loads(row.analysis_data)
            except (TypeError, ValueError):
                payload["profile"] = {}
        rows.append(payload)
    return {"ok": True, "data": _cap(rows)}


def _get_peer_comparison(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied and not allowed:
        return {"ok": False, "error": "ACCESS_DENIED"}
    indicators = (args.get("indicators") or ["cs_rate"])[:MAX_INDICATORS]
    rows = []
    for code in indicators:
        stats = ctx.peer_stats(code, ctx.authorized_ids, exclude_ids=[])
        rows.append({"indicator": code, **stats})
    return {"ok": True, "data": _cap(rows)}


def _get_historical_trends(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied and not allowed:
        return {"ok": False, "error": "ACCESS_DENIED"}
    if not allowed:
        return {"ok": True, "data": []}
    indicators = (args.get("indicators") or ["cs_rate"])[:MAX_INDICATORS]
    rows = []
    for hid in allowed[:1]:
        for code in indicators:
            if code in DERIVED:
                hist = _derived_history(ctx.db, hid, code)
            elif not _is_known_code(ctx.db, code):
                return {"ok": False, "error": f"validation: unknown indicator {code}"}
            else:
                hist = ctx.indicator_history(hid, code)
            rows.append({"hospital_id": hid, "indicator": code, "history": hist})
    return {"ok": True, "data": _cap(rows)}


def _query_month_aggregates(ctx, args):
    allowed, denied = ctx.allowed_hospital_ids(args.get("hospital_ids"))
    if denied and not allowed:
        return {"ok": False, "error": "ACCESS_DENIED"}
    indicators = (args.get("indicators") or [])[:MAX_INDICATORS]
    include = allowed if allowed else ctx.authorized_ids
    data = ctx.hospital_data()
    agg = {}
    for name, row in data.items():
        if row.get("hospital_id") not in include:
            continue
        for code, val in row.items():
            if code == "hospital_id":
                continue
            if indicators and code not in indicators:
                continue
            if val is None:
                continue
            bucket = agg.setdefault(code, [])
            bucket.append(val)
    out = []
    for code, vals in agg.items():
        out.append({"indicator": code, "hospitals": len(vals),
                    "mean": round(statistics.mean(vals), 2),
                    "min": round(min(vals), 2), "max": round(max(vals), 2)})
    return {"ok": True, "data": _cap(out)}


TOOL_DEFS = [
    {"name": "list_accessible_hospitals", "description": "List hospitals the user can access.",
     "schema": {}, "permission": "ai.read", "scope": "none", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_indicator_values", "description": "Indicator values for hospitals in a month.",
     "schema": {"hospital_ids": ["int"], "month": "str", "indicators": ["str"]},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_quality_score", "description": "Quality score components for hospitals.",
     "schema": {"hospital_ids": ["int"], "month": "str"},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_rule_results", "description": "Rule validation results for hospitals.",
     "schema": {"hospital_ids": ["int"], "month": "str", "status": "str"},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_anomalies", "description": "Outlier anomalies for hospitals in a month.",
     "schema": {"hospital_ids": ["int"], "month": "str"},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_clinical_profile", "description": "Clinical profile analysis for hospitals.",
     "schema": {"hospital_ids": ["int"], "month": "str"},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_peer_comparison", "description": "Peer benchmark stats for indicators across authorized hospitals.",
     "schema": {"hospital_ids": ["int"], "month": "str", "indicators": ["str"]},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "get_historical_trends", "description": "Recent monthly history for indicators of a hospital.",
     "schema": {"hospital_ids": ["int"], "month": "str", "indicators": ["str"]},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
    {"name": "query_month_aggregates", "description": "Cross-hospital aggregate stats for indicators in a month.",
     "schema": {"hospital_ids": ["int"], "month": "str", "indicators": ["str"]},
     "permission": "ai.read", "scope": "hospital", "max_results": MAX_ROWS, "max_tokens": 400},
]

_TOOL_FUNCS = {
    "list_accessible_hospitals": _list_accessible_hospitals,
    "get_indicator_values": _get_indicator_values,
    "get_quality_score": _get_quality_score,
    "get_rule_results": _get_rule_results,
    "get_anomalies": _get_anomalies,
    "get_clinical_profile": _get_clinical_profile,
    "get_peer_comparison": _get_peer_comparison,
    "get_historical_trends": _get_historical_trends,
    "query_month_aggregates": _query_month_aggregates,
}


def execute_tool(name, args, ctx):
    if name not in _TOOL_FUNCS:
        return {"ok": False, "error": f"validation: unknown tool {name}"}
    month = args.get("month")
    if month is not None and not _valid_month(month):
        return {"ok": False, "error": "validation: month must be YYYY-MM"}
    try:
        return _TOOL_FUNCS[name](ctx, args)
    except _InvalidArg as e:
        return {"ok": False, "error": f"validation: {e}"}
    except Exception:
        return {"ok": False, "error": "internal: tool execution failed"}
