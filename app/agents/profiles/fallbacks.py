"""Deterministic, bilingual profile fallbacks built only from tool reads.

Used when the LLM synthesis fails after bounded retries (see the agents spec's
failure chain). Every value here comes from the same read-only tools as the
live agents (ctx.quality_row / ctx.rule_rows / ctx.anomaly_rows /
ctx.hospital_data), never from the LLM and never invented.
"""
MAX_RULES = 10
MAX_ANOMALIES = 20
MAX_HOSPITALS = 20
QUALITY_THRESHOLD = 60.0

def _GRADE(s):
    return "good" if (s or 0) >= 80 else ("moderate" if (s or 0) >= 60 else "poor")

_AR = {
    "quality": "جودة البيانات",
    "rule": "القاعدة",
    "anomaly": "الشذوذ",
    "hospital": "المستشفى",
    "insufficient": "Insufficient data to determine the cause.",
    "insufficient_ar": "البيانات غير كافية لتحديد السبب.",
    "summary_ar": "نتائج مستخلصة من البيانات",
    "sources_ar": "ومصادر البيانات",
    "priority_ar": "بحسب الأولوية",
}

_PROFILES = ("qa", "explainer", "report_writer", "triage")


def _label(key, lang):
    return _AR[key] if lang == "ar" else key


def _call(ctx, name, arg):
    """Safely invoke ctx.<name>(arg) regardless of ctx's real shape."""
    fn = getattr(ctx, name, None)
    if fn is None:
        return None
    try:
        return fn(arg)
    except Exception:
        return None


def _call0(ctx, name):
    fn = getattr(ctx, name, None)
    if fn is None:
        return None
    try:
        return fn()
    except Exception:
        return None


def _rnum(v, nd=1):
    try:
        return round(float(v), nd) if v is not None else None
    except (TypeError, ValueError):
        return None


def _quality_facts(ctx, hid, lang):
    q = _call(ctx, "quality_row", hid)
    if q is None:
        return []
    score = getattr(q, "score", None)
    if score is None:
        return []
    comps = {}
    for key in ("rule_compliance", "completeness", "consistency", "outlier_penalty"):
        v = _rnum(getattr(q, key, None))
        if v is not None:
            comps[key] = v
    return [{
        "kind": "quality",
        "component": _label("quality", lang),
        "value": _rnum(score),
        "grade": _GRADE(score),
        "components": comps,
        "source": "quality_scores",
    }]


def _rule_facts(ctx, hid, lang):
    rows = _call(ctx, "rule_rows", hid) or []
    out = []
    for r in rows[:MAX_RULES]:
        if getattr(r, "status", None) != "FAIL":
            continue
        out.append({
            "kind": "rule",
            "rule_code": getattr(r, "rule_code", None),
            "rule_description": getattr(r, "rule_description", None),
            "status": getattr(r, "status", None),
            "severity": getattr(r, "severity", None),
            "rule_type": getattr(r, "rule_type", None),
            "source": "validation_results",
        })
    return out


def _anomaly_facts(ctx, hid, lang):
    rows = _call(ctx, "anomaly_rows", hid) or []
    out = []
    for a in rows[:MAX_ANOMALIES]:
        out.append({
            "kind": "anomaly",
            "rate_name": getattr(a, "rate_name", None),
            "value": _rnum(getattr(a, "value", None)),
            "benchmark": _rnum(getattr(a, "benchmark", None)),
            "z_score": _rnum(getattr(a, "z_score", None)),
            "peer_median": _rnum(getattr(a, "peer_median", None)),
            "source": "anomaly_results",
        })
    return out


def _hospital_facts(ctx, lang):
    data = _call0(ctx, "hospital_data") or {}
    out = []
    for name in sorted(data)[:MAX_HOSPITALS]:
        row = data[name] or {}
        n = sum(1 for k, v in row.items() if k != "hospital_id" and v is not None)
        out.append({
            "kind": "hospital",
            "name": name,
            "indicators_with_data": n,
            "source": "hospital_data",
        })
    return out


def _analysis(q, rules, anomalies, lang):
    out = []
    if q is not None:
        score = getattr(q, "score", None)
        if score is not None and float(score) < QUALITY_THRESHOLD:
            out.append({"metric": _label("quality", lang),
                        "observed": "below threshold (<60)",
                        "value": _rnum(score)})
        for key in ("completeness", "consistency", "rule_compliance"):
            v = _rnum(getattr(q, key, None))
            if v is not None:
                out.append({"metric": key,
                            "observed": f"observed {v} of 100",
                            "value": v})
    for a in anomalies:
        z = _rnum(getattr(a, "z_score", None), 2)
        if z is not None:
            out.append({"metric": getattr(a, "rate_name", None),
                        "observed": f"z-score {z:+.2f}",
                        "value": _rnum(getattr(a, "value", None)),
                        "benchmark": _rnum(getattr(a, "benchmark", None))})
    return out


def _contributors(q, rules, anomalies):
    out = []
    failed = [r for r in rules if getattr(r, "status", None) == "FAIL"]
    comp = getattr(q, "completeness", None) if q is not None else None
    cons = getattr(q, "consistency", None) if q is not None else None
    if failed and (comp is not None or cons is not None):
        out.append({"factor": "low data completeness/consistency may be associated "
                              "with the failed validation rules",
                    "evidence": f"{len(failed)} failed rule(s); component scores present"})
    if anomalies and q is not None:
        score = getattr(q, "score", None)
        if score is not None and float(score) < QUALITY_THRESHOLD:
            out.append({"factor": "outlier values may be associated with the low "
                                  "quality score",
                        "evidence": f"{len(anomalies)} anomaly(ies); score {_rnum(score)}"})
    return out


def _actions(q, rules, anomalies):
    out = []
    failed = [r for r in rules if getattr(r, "status", None) == "FAIL"]
    for r in failed[:5]:
        if getattr(r, "severity", None) in ("critical", "high"):
            out.append({"rule_code": getattr(r, "rule_code", None),
                        "action": "Review the failed rule's contributing indicators"})
    if failed:
        out.append({"action": "Correct the affected data entries and re-run validation"})
    one_grade = _GRADE(getattr(q, "score", 0)) if q is not None else None
    if one_grade == "poor":
        out.append({"action": "Prioritize quality improvement; inspect components below "
                              f"{QUALITY_THRESHOLD:.0f}"})
    return out


def _sources(facts):
    return ", ".join(sorted({str(f["source"]) for f in facts if f.get("source")}))


def _kinds(facts, lang):
    counts = {}
    for f in facts:
        k = f.get("kind")
        if k:
            counts[k] = counts.get(k, 0) + 1
    return {_label(k, lang): v for k, v in counts.items()}


def _answer(profile, lang, facts, analysis, contributors, anomalies, q):
    if not facts:
        return _AR["insufficient_ar"] if lang == "ar" else _AR["insufficient"]

    n = len(facts)
    kinds = ", ".join(f"{label}={cnt}" for label, cnt in _kinds(facts, lang).items())
    srcs = _sources(facts)

    if lang == "ar":
        parts = [f"{n} {_AR['summary_ar']}: {kinds} ({srcs})."]
        if analysis:
            first = analysis[0]
            parts.append(f"الملاحظة: {first.get('metric')} — {first.get('observed')}.")
        if contributors:
            parts.append("العوامل المساهمة المحتملة: " +
                         "؛ ".join(c["factor"] for c in contributors) + ".")
        return " ".join(parts)

    profile = profile if profile in _PROFILES else "explainer"
    base = f"{n} finding(s) from {srcs}: {kinds}."
    if profile == "qa":
        text = (f"Based on the available data, I found {n} finding(s) — {kinds}. "
                f"Sources used: {srcs}.")
    elif profile == "triage":
        prio = []
        if any(f.get("kind") == "anomaly" and f.get("z_score") is not None
               for f in facts):
            prio.append("outlier anomalies sorted by z-score severity")
        if any(f.get("kind") == "rule" and f.get("severity") in ("critical", "high")
               for f in facts):
            prio.append("high/critical rule failures")
        if any(f.get("kind") == "quality" and (f.get("value") or 0) < QUALITY_THRESHOLD
               for f in facts):
            prio.append("quality below threshold")
        prio_txt = ", ".join(prio) if prio else "quality, rules, and anomalies"
        text = (f"Triage digest: {n} finding(s) ({kinds}). "
                f"Prioritized by severity: {prio_txt}. Sources: {srcs}.")
    elif profile == "report_writer":
        ana = analysis[0]["observed"] if analysis else "no deltas observed this month"
        text = (f"Monthly data summary: {base} Observed: {ana}.")
    else:  # explainer
        ana = "; ".join(f"{a.get('metric')} {a.get('observed')}" for a in analysis)
        tail = f" Observed: {ana}." if ana else ""
        text = f"{base}{tail} Review the failed rules identified above."
    return text


def fallback_answer(profile, ctx, question, lang):
    """Build the deterministic fallback answer strictly from ctx tool reads.

    Returns {"facts", "analysis", "contributors", "actions", "answer"} honoring
    the spec's structured output contract; never raises on malformed ctx.
    """
    facts, analysis, contributors, actions = [], [], [], []
    q = None
    anomalies = []
    rules = []

    authorized = getattr(ctx, "authorized_ids", None) or []
    hid = (list(authorized) or [1])[0]

    facts.extend(_quality_facts(ctx, hid, lang))
    rules = _call(ctx, "rule_rows", hid) or []
    facts.extend(_rule_facts(ctx, hid, lang))
    anomalies = _call(ctx, "anomaly_rows", hid) or []
    facts.extend(_anomaly_facts(ctx, hid, lang))
    facts.extend(_hospital_facts(ctx, lang))

    q = _call(ctx, "quality_row", hid)
    analysis = _analysis(q, rules, anomalies, lang)
    contributors = _contributors(q, rules, anomalies)
    actions = _actions(q, rules, anomalies)

    answer = _answer(profile, lang, facts, analysis, contributors, anomalies, q)
    return {"facts": facts, "analysis": analysis, "contributors": contributors,
            "actions": actions, "answer": answer}
