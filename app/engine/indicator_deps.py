"""Indicator dependency registry — which system module consumes what.

Static, code-declared map (2026-10-18 centralized-indicators design): for
every indicator surfaced by the Indicators screen, answer "which other
screens depend on this?" so the UI can show dependencies, and deletion /
deactivation prompts can name the modules a change touches.

Grounded in the code inventory of 2026-10-18:

* ``zscore``/``db`` rate specs feed Audit (benchmark + Why), Outlier Scan
  (z-score/trends), Outlier Diagnostics (layered), Hospital Comparisons,
  Confidence signals and Root-cause rate series — all of them read
  ``rate_config`` / ``anomaly.zscore.RATE_DEFINITIONS``.
* ``clinical`` rate specs feed Clinical Intelligence and the Dashboard's
  clinical-rate cards (both resolve through ``clinical.thresholds``).
* ``forecast`` rate specs feed Smart Analytics, Smart Forecast and Regional
  Analysis (``smart.__init__`` feature sources / ``indicator_forecast``).
* RAW data elements feed the raw-data layer: Data Tree, Data Groups,
  Upload & Completeness, Validation Rules (raw-data ONLY — never indicator
  formulas), Audit evidence, Outlier raw layer and Smart feature sources.

Leaf module: imports nothing from app.models or the engine (avoids cycles).
"""
from typing import Dict, List, Optional, Sequence

# module_id -> display + what it consumes. "sites" limits the entry to
# rate specs of those rate_config sites; None = applies to raw elements.
MODULES: Dict[str, Dict[str, str]] = {
    "audit": {
        "label": "Audit",
        "label_ar": "التدقيق",
        "how": "Benchmark table and Why-explanations recompute this indicator for peer comparison",
    },
    "outliers": {
        "label": "Outlier Scan",
        "label_ar": "فحص الشواذ",
        "how": "Historical / cross-hospital z-score anomaly detection runs on this indicator",
    },
    "layered": {
        "label": "Outlier Diagnostics",
        "label_ar": "تشخيص الشواذ",
        "how": "Layered peer / volume / historical diagnostics use this indicator",
    },
    "comparison": {
        "label": "Hospital Comparisons",
        "label_ar": "مقارنة المستشفيات",
        "how": "Cross-hospital deviation comparisons include this indicator",
    },
    "confidence": {
        "label": "Confidence Score",
        "label_ar": "درجة الثقة",
        "how": "Rate-consistency signals contribute to the confidence score",
    },
    "clinical": {
        "label": "Clinical Intelligence",
        "label_ar": "التحليل السريري",
        "how": "Classification, risk bands and clinical narratives use this indicator",
    },
    "dashboard": {
        "label": "Dashboard",
        "label_ar": "لوحة القيادة",
        "how": "Clinical-rate KPI cards display this indicator",
    },
    "smart": {
        "label": "Smart Analytics",
        "label_ar": "التحليل الذكي",
        "how": "Feature series and anomaly models consume this indicator",
    },
    "forecast": {
        "label": "Smart Forecast",
        "label_ar": "التوقعات",
        "how": "Forecast models are trained on this indicator's series",
    },
    "regional": {
        "label": "Regional Analysis",
        "label_ar": "التحليل الإقليمي",
        "how": "Governorate-level aggregation uses this indicator",
    },
    "reports": {
        "label": "Reports",
        "label_ar": "التقارير",
        "how": "Audit and outlier report outputs include this indicator and its formula provenance",
    },
    "quality": {
        "label": "Quality Reports",
        "label_ar": "تقارير الجودة",
        "how": "The Quality tab's anomaly table and PDF/Excel exports display this indicator with its registry unit and formula status",
    },
    # ── raw-data layer (raw elements only) ────────────────────────────────
    "indicators_screen": {
        "label": "Indicators screen",
        "label_ar": "شاشة المؤشرات",
        "how": "Managed in the central Indicators registry",
    },
    "data_tree": {
        "label": "Data Tree",
        "label_ar": "شجرة البيانات",
        "how": "Displayed and maintained as a raw data element",
    },
    "data_groups": {
        "label": "Data Groups",
        "label_ar": "مجموعات البيانات",
        "how": "Bulk enable/disable configuration applies to this element",
    },
    "upload": {
        "label": "Upload & Completeness",
        "label_ar": "الرفع والاكتمال",
        "how": "Import and completeness denominators count this element",
    },
    "validation_rules": {
        "label": "Data Validation Rules",
        "label_ar": "قواعد التحقق",
        "how": "Raw-data validation rules may reference this element (raw data only — indicator formulas are never validated as rules)",
    },
    "evidence": {
        "label": "Audit evidence",
        "label_ar": "أدلة التدقيق",
        "how": "Raw values back indicator explanations and data-auditor evidence",
    },
    "smart_features": {
        "label": "Smart feature sources",
        "label_ar": "مصادر الخصائص الذكية",
        "how": "ML feature series are extracted from this element",
    },
}

# rate_config site -> module ids that consume specs of that site
SITE_MODULES: Dict[str, List[str]] = {
    "zscore": ["audit", "outliers", "layered", "comparison", "confidence", "quality"],
    "db": ["audit", "outliers", "layered", "comparison", "confidence", "quality"],
    "clinical": ["clinical", "dashboard"],
    "forecast": ["smart", "forecast", "regional"],
}

# raw element -> the raw-data modules that consume every raw element
RAW_MODULES: List[str] = [
    "data_tree", "data_groups", "upload", "validation_rules",
    "evidence", "smart_features",
]


def _entry(module_id: str) -> Optional[dict]:
    meta = MODULES.get(module_id)
    if meta is None:
        return None
    return {"id": module_id, "label": meta["label"],
            "label_ar": meta["label_ar"], "how": meta["how"]}


def dependencies_for(source: str, code: str,
                     site: Optional[str] = None,
                     ref_codes: Sequence[str] = ()) -> List[dict]:
    """Modules depending on one indicator.

    source: "derived" | "rate_spec" | "raw"
    site:   rate_config site for rate_spec (zscore | clinical | forecast | db)
    ref_codes: raw codes a derived definition references (their consumers
               are reported with via='source element').
    """
    seen: Dict[str, dict] = {}

    def _add(module_id: str, via: str) -> None:
        entry = _entry(module_id)
        if entry is None or entry["id"] in seen:
            return
        entry = dict(entry, via=via)
        seen[entry["id"]] = entry

    if source == "rate_spec" or (source == "derived" and site):
        for module_id in SITE_MODULES.get(site or "zscore", []):
            _add(module_id, "rate definition")
    if source == "raw":
        for module_id in RAW_MODULES:
            _add(module_id, "raw data element")
    elif source == "derived":
        if not site:
            _add("indicators_screen", "registry")
            for module_id in (
                "audit", "outliers", "comparison", "clinical", "dashboard",
                "reports", "quality"
            ):
                _add(module_id, "calculated indicator")
        for raw_code in ref_codes:
            for module_id in RAW_MODULES:
                _add(module_id, f"source element {{{raw_code}}}")
    return list(seen.values())
