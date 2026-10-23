"""Static contract for the Quality Alerts tab (no browser needed).

Pins the navigation wiring (menu registry, index.html container, module
registration, init dispatch), the fragment structure, and — most importantly
— that the frontend module contains no indicator formula math: it only
fetches and displays server-computed results (spec §10).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
JS = STATIC / "js"
TABS = STATIC / "tabs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Navigation (spec §1: tab appears under the Quality group) ───────────────

def test_menu_registry_declares_quality_alerts_under_oversight():
    from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY
    assert "quality-alerts" in TAB_REGISTRY
    entry = TAB_REGISTRY["quality-alerts"]
    assert entry["label"] == "Quality Alerts"
    assert entry["permission"] == "quality_alerts.read"
    oversight = next(g for g in DEFAULT_GROUPS if g["name"] == "Oversight")
    assert "quality-alerts" in oversight["items"]
    assert "quality" in oversight["items"], "existing Quality tabs preserved"


def test_index_html_has_quality_alerts_container():
    src = _read(STATIC / "index.html")
    assert 'id="tab-quality-alerts"' in src
    assert "/static/tabs/quality-alerts.html" in src


def test_app_registers_module_and_binds_handlers():
    src = _read(JS / "app.js")
    assert "quality-alerts.js" in src
    for handler in ("initQualityAlerts", "loadQualityAlerts", "openQualityAlert",
                    "scanQualityAlerts", "recomputeStaleQualityAlerts",
                    "setQualityAlertStatus",
                    "exportQualityAlertsCSV"):
        assert handler in src, f"{handler} must be bound for onclick handlers"


def test_main_dispatches_init_and_labels():
    src = _read(JS / "main.js")
    assert "quality-alerts" in src
    assert "_tryInit('initQualityAlerts'" in src
    assert "'quality-alerts': 'Quality Alerts'" in src


def test_sidebar_fallback_includes_quality_alerts():
    src = _read(JS / "renderSidebar.js")
    assert "quality-alerts" in src
    assert "quality_alerts.read" in src


def test_i18n_has_quality_alerts_labels():
    src = _read(JS / "i18n.js")
    for key in ("'Quality Alerts': 'تنبيهات الجودة'",
                "'Red Alerts':",
                "'Comparison perspectives':",
                "'Risk issues':"):
        assert key in src, f"missing Arabic translation for {key}"


# ── Fragment structure (recommended screen layout) ──────────────────────────

def test_fragment_has_kpis_filters_and_issue_table():
    src = _read(TABS / "quality-alerts.html")
    for kpi in ("qaKpiRedOnly", "qaKpiMixed", "qaKpiTotal", "qaKpiHospitals",
                "qaKpiIndicators", "qaKpiNew", "qaKpiUnresolved"):
        assert kpi in src, f"missing KPI card {kpi}"
    for filt in ("qaMonthFilter", "qaHospitalFilter", "qaIndicatorFilter",
                 "qaIndicatorTypeFilter",
                 "qaStatusFilter", "qaOwnershipFilter",
                 "qaGovernorateFilter", "qaTypeFilter", "qaSearchFilter"):
        assert filt in src, f"missing filter {filt}"
    assert "qaPerspectiveChips" in src
    assert "qaTableBody" in src
    assert "scanQualityAlerts()" in src


def test_fragment_pins_very_high_severity_only():
    """The screen is the Red-Alerts screen: severity is pinned to VERY_HIGH
    in the query and the severity dropdown is deliberately absent."""
    frag = _read(TABS / "quality-alerts.html")
    assert "qaSeverityFilter" not in frag, \
        "severity must be pinned, not user-selectable on this screen"
    assert "Very High (Red) alerts only" in frag
    js = _read(JS / "quality-alerts.js")
    assert "_PINNED_SEVERITY = 'VERY_HIGH'" in js
    assert "p.set('severity', _PINNED_SEVERITY)" in js


def test_scan_button_falls_back_to_all_periods():
    """With no period selected, Run Scan scans every month (catch-up)."""
    js = _read(JS / "quality-alerts.js")
    assert "month ? { month: month } : {}" in js


def test_recompute_stale_action_previews_then_asks_before_scanning():
    """The stale action must preview the affected months and require an
    explicit confirmation before any month is rescanned."""
    frag = _read(TABS / "quality-alerts.html")
    assert 'id="qaRescanStaleBtn"' in frag
    assert 'onclick="recomputeStaleQualityAlerts()"' in frag

    js = _read(JS / "quality-alerts.js")
    assert "export async function recomputeStaleQualityAlerts" in js
    assert "'/quality-alerts/rescan-stale'" in js
    # A preview first, the rescan only after the operator confirms.
    assert "confirm: false" in js
    assert "confirm: true" in js
    assert "confirmAction(" in js
    assert js.index("confirm: false") < js.index("confirm: true")

    i18n = _read(JS / "i18n.js")
    for key in ("'Recompute stale':", "'Recompute stale results':",
                "'Recompute failed: '"):
        assert key in i18n, f"missing Arabic translation for {key}"


# ── No hardcoded formulas in the frontend (spec §10) ────────────────────────

def test_frontend_module_computes_no_indicator_math():
    src = _read(JS / "quality-alerts.js")
    # It fetches server-computed results only.
    assert "apiGet('/quality-alerts/" in src
    assert "apiPostJSON('/quality-alerts/scan'" in src
    # No rate-formula shapes or data-tree code literals anywhere in the module.
    # ({code} references anchored to arithmetic context so the month-format
    # regex \d{2} is not a false positive.)
    for forbidden in ("numerator / denominator", "{5}", "{6}", "{10}",
                      "{2} /", "{2} *", "/ {2}",
                      "deliveries", "live_births", "c_section",
                      "* 100", "/ 1000"):
        assert forbidden not in src, f"hardcoded formula hint: {forbidden!r}"


def test_detail_renders_the_peer_group_as_a_visible_table():
    """The detail must show the peer hospitals and their values, not hide the
    only evidence for the baseline inside a collapsed toggle — and a history
    alert must still show the issue's peer groups."""
    src = _read(JS / "quality-alerts.js")
    assert "peer_groups" in src
    assert "qa-peer-table" in src
    assert "qa-peer-group" in src
    assert '<details class="qa-peers">' not in src, \
        "peer list must not be collapsed by default"
    assert "no peer hospitals were used" in src, \
        "own-history findings need an explicit explanation"


def test_detail_view_surfaces_direction_and_workflow():
    src = _read(JS / "quality-alerts.js")
    # Direction-aware interpretation + investigation workflow + audit links.
    assert "interpretation" in src
    assert "direction" in src
    assert "setQualityAlertStatus" in src
    assert "addQualityAlertNote" in src
    # Both cross-screen links open their target in a NEW browser tab
    # (newtab.js), so the alerts screen keeps its filters and scroll position.
    assert "openAuditTrailInNewTab" in src
    assert "window.openScreenInNewTab" in src
    assert "indicators" in src, "detail links to the Indicators registry tab"


# ── Indicator-type filter (Data Element vs Derivative Indicator) ────────────

# ── Arabic coverage of the strings the screen shows ─────────────────────────

def _translations_object() -> str:
    """The literal `translations` object out of i18n.js (braces balanced)."""
    content = _read(JS / "i18n.js")
    start = content.index("{", content.index("export const translations"))
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                return content[start:i + 1]
    raise AssertionError("unbalanced braces in translations object")


def _ui_string_keys(path: Path) -> list:
    """Every literal key passed to __() in a module, in source order."""
    keys = []
    for raw in re.findall(r"__\(\s*'((?:[^'\\]|\\.)*)'", _read(path)):
        key = raw.replace("\\'", "'")
        if key not in keys:
            keys.append(key)
    return keys


def _arabic_value(obj: str, key: str):
    """The translated value for `key`, or None when no entry exists."""
    for candidate in (key, key.replace("'", "\\'")):
        m = re.search(r"'" + re.escape(candidate) +
                      r"'\s*:\s*'((?:[^'\\]|\\.)*)'", obj)
        if m:
            return m.group(1)
    return None


def test_every_quality_alerts_ui_string_has_an_arabic_translation():
    """No user-visible string may fall back to English in Arabic mode."""
    keys = _ui_string_keys(JS / "quality-alerts.js")
    assert len(keys) > 50, "the __() extraction found suspiciously few strings"
    obj = _translations_object()
    untranslated = []
    for key in keys:
        value = _arabic_value(obj, key)
        if value is None:
            untranslated.append(f"missing: {key!r}")
        elif not re.search(r"[\u0600-\u06FF]", value):
            untranslated.append(f"no Arabic: {key!r} -> {value!r}")
        elif value == key:
            untranslated.append(f"untranslated passthrough: {key!r}")
    assert not untranslated, "Quality Alerts i18n gaps:\n  " + "\n  ".join(untranslated)


def test_quality_alerts_completion_messages_are_arabic():
    """Pin the wording of what the operator sees when an action finishes."""
    expected = {
        "Scan complete: ": "اكتمل المسح: ",
        "Scan failed: ": "فشل المسح: ",
        "Run the Quality Alerts scan for ": "تشغيل مسح تنبيهات الجودة لشهر ",
        "Recompute failed: ": "فشلت إعادة الحساب: ",
        "Note saved.": "تم حفظ الملاحظة.",
        "Type a note first.": "اكتب ملاحظة أولاً.",
        "Failed to save note: ": "تعذّر حفظ الملاحظة: ",
        "Failed to update status: ": "تعذّر تحديث الحالة: ",
        "Failed to load alert: ": "تعذّر تحميل التنبيه: ",
        "error": "خطأ",
    }
    obj = _translations_object()
    wrong = {k: _arabic_value(obj, k) for k, v in expected.items()
             if _arabic_value(obj, k) != v}
    assert not wrong, f"wrong completion wording: {wrong}"


def test_quality_alerts_fragment_labels_are_arabic():
    """Static labels in the fragment go through data-i18n; all must translate."""
    frag = _read(TABS / "quality-alerts.html")
    keys = sorted(set(re.findall(r'data-i18n="([^"]+)"', frag)))
    assert keys, "fragment should use data-i18n attributes"
    obj = _translations_object()
    untranslated = [k for k in keys
                    if not re.search(r"[\u0600-\u06FF]",
                                     _arabic_value(obj, k) or "")]
    assert not untranslated, f"untranslated fragment labels: {untranslated}"


def test_quality_alerts_error_fallbacks_are_translated():
    """The bare 'error' fallback must go through __() too."""
    src = _read(JS / "quality-alerts.js")
    assert not re.findall(r"(?<!__\()'error'", src), \
        "an untranslated 'error' fallback remains"


def test_kpi_and_pager_count_grouped_issues_not_perspective_rows():
    """Cards and pager use the same unit as the table: one row per issue.

    The summary also returns perspective-row counts (total_active,
    red_alerts, …). Showing those beside a table of grouped issues made the
    cards overstate findings and the pager advertise empty pages.
    """
    src = _read(JS / "quality-alerts.js")
    # Pager and row counter page through the server's grouped issue total.
    assert "_state.issuesTotal = issues.total" in src
    assert "_renderPager(_state.issuesTotal" in src
    # Every KPI card reads an issue-unit field. Red-only and mixed replace the
    # old Red card, which merely repeated the total on this pinned screen.
    for field in ("total_issues", "new_issues", "unresolved_issues",
                  "red_only_issues", "mixed_severity_issues"):
        assert f"s.{field}" in src, f"KPI must read s.{field}"
    for row_field in ("total_active", "red_alerts", "new_alerts"):
        assert f"s.{row_field}" not in src, \
            f"KPI must not read the row count s.{row_field}"
        assert f"_state.summary.{row_field}" not in src, \
            f"pager must not count rows via summary.{row_field}"

    api = (ROOT / "app" / "api" / "quality_alerts.py").read_text(encoding="utf-8")
    for field in ("total_issues", "red_issues", "new_issues",
                  "unresolved_issues", "red_only_issues",
                  "mixed_severity_issues"):
        assert f'"{field}"' in api, f"summary must publish {field}"


def test_open_issues_kpi_label_names_every_status_it_counts():
    """"Open issues" counts New + Under Review + Confirmed Issue.

    The card read "Under review" while showing every status except Resolved
    and False Positive, so New and Confirmed Issue hid inside a number whose
    label promised something narrower. The count did not change — only its
    wording, which now names all three statuses in rollup order.
    """
    from app.engine import quality_alerts as engine

    frag = _read(TABS / "quality-alerts.html")
    card = next(line for line in frag.splitlines()
                if 'id="qaKpiUnresolved"' in line)
    assert 'data-i18n="Open issues"' in card
    assert "data-i18n=\"Under review\"" not in frag, \
        "no KPI card may claim the whole open backlog is under review"

    sub_label = next(part for part in re.findall(r'data-i18n="([^"]*)"', card)
                     if part.startswith("New ·"))
    assert sub_label == " · ".join((engine.STATUS_NEW,
                                    engine.STATUS_UNDER_REVIEW,
                                    engine.STATUS_CONFIRMED)), \
        "the sub-line must list exactly the statuses the count includes"

    # Only the wording changed; the card still reads the same field.
    assert "s.unresolved_issues" in _read(JS / "quality-alerts.js")

    i18n = _read(JS / "i18n.js")
    for key, arabic in (("Open issues", "مشكلات مفتوحة"),
                        (sub_label, "جديد · قيد المراجعة · مؤكد")):
        assert f"'{key}': '{arabic}'" in i18n, f"missing Arabic for {key}"


def test_indicator_type_filter_wiring():
    """The indicator-type dropdown narrows by the alert's indicator TYPE:
    data elements have a NULL registry FK, derivatives carry one."""
    frag = _read(TABS / "quality-alerts.html")
    assert 'id="qaIndicatorTypeFilter"' in frag
    assert 'value="element"' in frag
    assert 'value="derivative"' in frag
    js = _read(JS / "quality-alerts.js")
    assert "['indicator_type', 'qaIndicatorTypeFilter']" in js

    import inspect

    from app.api import quality_alerts as api_mod
    src_api = inspect.getsource(api_mod)
    assert "indicator_type" in src_api
    # The NULL-FK discriminator must be pinned: element = NULL, derivative = set
    assert 'QualityAlert.indicator_id.is_(None)' in src_api
    assert 'QualityAlert.indicator_id.isnot(None)' in src_api
