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
                "'Very High only':",
                "'Comparison perspectives':",
                "'Risk issues':"):
        assert key in src, f"missing Arabic translation for {key}"


# ── Fragment structure (recommended screen layout) ──────────────────────────

def test_fragment_has_kpis_filters_and_issue_table():
    src = _read(TABS / "quality-alerts.html")
    for kpi in ("qaKpiVeryHighOnly", "qaKpiMixed", "qaKpiTotal", "qaKpiHospitals",
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


def test_severity_filter_defaults_to_very_high_but_can_be_widened():
    """The screen still OPENS on the Very High band, but the band is no longer
    pinned: an operator can widen the list to a lower band or to every
    severity without leaving the screen."""
    frag = _read(TABS / "quality-alerts.html")
    assert 'id="qaSeverityFilter"' in frag
    select = next(line for line in frag.splitlines()
                  if 'id="qaSeverityFilter"' in line)
    assert 'onchange="qualityAlertsFilterChanged()"' in select
    assert 'value="VERY_HIGH" selected' in frag, "Very High is the default scope"
    assert '<option value=""' in frag, "all severities must be reachable"
    for band in ("HIGH", "MODERATE", "LOW"):
        assert f'value="{band}"' in frag, f"{band} must be selectable"
    assert "(Red)" not in frag, \
        "the band is named for itself; no colour label may pin it"

    js = _read(JS / "quality-alerts.js")
    assert "_DEFAULT_SEVERITY = 'VERY_HIGH'" in js
    assert "p.set('severity', severity)" in js
    assert "_PINNED_SEVERITY" not in js
    # The "only Very High" explanation disappears once the list is widened.
    assert "_renderScopeNote()" in js


def test_skip_low_confidence_option_filters_server_side():
    """Hiding low-confidence findings is opt-in and server-side, so the KPIs
    and the pager count exactly the rows the table lists."""
    frag = _read(TABS / "quality-alerts.html")
    marker = frag.index('id="qaSkipLowConfidence"')
    block = frag[frag.rindex("<label", 0, marker):frag.index("</label>", marker)]
    assert 'type="checkbox"' in block
    assert "checked" not in block, "nothing is hidden until the operator asks"
    assert 'onchange="qualityAlertsFilterChanged()"' in block
    assert 'data-i18n="Skip low confidence"' in block

    js = _read(JS / "quality-alerts.js")
    assert "p.set('confidence', 'high')" in js
    assert "_skipsLowConfidence()" in js

    i18n = _read(JS / "i18n.js")
    assert "'Skip low confidence': 'استبعاد الثقة المنخفضة'" in i18n
    assert "'Very High': " in i18n


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


# ── Degenerate (no-dispersion) comparisons ─────────────────────────────────

def test_zero_spread_rows_are_labelled_instead_of_showing_a_bare_zero():
    """A 0/flat baseline from an all-identical group is explained on screen.

    The level is capped at HIGH (engine policy), so the badge must reach both
    the list cell and the detail KPI, and the tooltip must say why rather than
    leaving a bare 0 that reads like broken arithmetic.
    """
    src = _read(JS / "quality-alerts.js")
    assert "function _zeroSpreadBadge()" in src
    assert src.count("_zeroSpreadBadge()") >= 3, \
        "definition + list cell + detail KPI"
    list_cell = src[src.index("primary.baseline_value") - 200:
                    src.index("primary.baseline_value") + 400]
    assert "primary.zero_spread" in list_cell
    assert "a.zero_spread ? _zeroSpreadBadge()" in src

    i18n = _read(JS / "i18n.js")
    assert "'no spread': '" in i18n
    assert "capped at HIGH" in i18n


def test_issue_rows_carry_the_zero_spread_flag_from_the_api():
    """The list cannot label the cap without the flag the API exposes."""
    src = _read(ROOT / "app" / "api" / "quality_alerts.py")
    assert '"zero_spread": engine.zero_spread(' in src
    assert '"dispersion": (alert.evidence or {}).get("dispersion")' in src


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
    very_high_rows, …). Showing those beside a table of grouped issues made
    the cards overstate findings and the pager advertise empty pages.
    """
    src = _read(JS / "quality-alerts.js")
    # Pager and row counter page through the server's grouped issue total.
    assert "_state.issuesTotal = issues.total" in src
    assert "_renderPager(_state.issuesTotal" in src
    # Every KPI card reads an issue-unit field. Very-High-only and mixed split
    # the Very High findings, so neither merely repeats the total.
    for field in ("total_issues", "new_issues", "unresolved_issues",
                  "very_high_only_issues", "mixed_severity_issues"):
        assert f"s.{field}" in src, f"KPI must read s.{field}"
    for row_field in ("total_active", "very_high_rows", "new_alerts"):
        assert f"s.{row_field}" not in src, \
            f"KPI must not read the row count s.{row_field}"
        assert f"_state.summary.{row_field}" not in src, \
            f"pager must not count rows via summary.{row_field}"

    api = (ROOT / "app" / "api" / "quality_alerts.py").read_text(encoding="utf-8")
    for field in ("total_issues", "very_high_issues", "new_issues",
                  "unresolved_issues", "very_high_only_issues",
                  "mixed_severity_issues"):
        assert f'"{field}"' in api, f"summary must publish {field}"
    # The evidence row count is published under its own explicit name, so it is
    # never confused with the Very High issue count.
    assert '"very_high_rows"' in api, "summary must publish very_high_rows"


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


def test_status_filter_scopes_the_list_to_open_alerts():
    """Closing an alert (Resolved / skipped) must clear it from the list.

    The sentinel that asks for closed rows is NOT a status value: sending it as
    one would filter for a status that does not exist and silently empty the
    table. It must travel as include_closed instead, and the confirmation must
    say where the row went — a row that just disappears reads as a failed save.
    """
    js = _read(JS / "quality-alerts.js")
    assert "const _ALL_STATUSES = '__all__';" in js
    assert "p.set('include_closed', '1')" in js
    assert "p.set('status', statusEl.value)" in js
    assert "['status', 'qaStatusFilter']" not in js, \
        "the status sentinel must not be sent as a status filter"
    assert "status === 'Resolved' || status === 'False Positive'" in js, \
        "closing the alert must be reported to the operator"
    assert "__('Open only')" in js, "the default scope must be labelled"

    from app.engine import quality_alerts as engine
    assert engine.CLOSED_STATUSES == (engine.STATUS_RESOLVED,
                                      engine.STATUS_FALSE_POSITIVE)
    assert engine.is_open_status(engine.STATUS_UNDER_REVIEW) is True
    assert engine.is_open_status(engine.STATUS_RESOLVED) is False
    assert engine.is_open_status(engine.STATUS_FALSE_POSITIVE) is False

    i18n = _read(JS / "i18n.js")
    for key, arabic in (("Open only", "المفتوحة فقط"),
                        ("All statuses (incl. closed)",
                         "كل الحالات (بما فيها المغلقة)"),
                        ("Marked ", "تم وضع علامة ")):
        assert f"'{key}': '{arabic}'" in i18n, f"missing Arabic for {key}"


# ── One vocabulary: code → label, on every surface ─────────────────────────

def test_one_label_per_code_across_every_surface():
    """A band, a status and a perspective read the same thing everywhere.

    The table printed the raw code (``VERY_HIGH``) beside a filter that said
    "Very High", so one severity looked like two; the Arabic screen also showed
    untranslated English statuses and perspective names. Every surface now goes
    through one helper per vocabulary, so the badge, the detail modal, the
    sibling tables and the audit trail cannot drift apart again.
    """
    js = _read(JS / "quality-alerts.js")
    for helper in ("function _severityLabel(", "function _statusLabel(",
                   "function _perspectiveLabel("):
        assert helper in js, f"missing {helper}"
    for raw in ("esc(issue.primary_severity)", "esc(a.severity)",
                "esc(s.severity)", "esc(pa.severity)",
                "esc(issue.status)", "esc(a.status)", "esc(s.status)",
                "esc(pa.status)"):
        assert raw not in js, f"raw code rendered instead of its label: {raw}"
    for labeled in ("_severityLabel(issue.primary_severity)",
                    "_severityLabel(a.effective_severity || a.severity)",
                    "_severityLabel(s.severity)",
                    "_severityLabel(pa.severity)",
                    "_statusLabel(issue.status)",
                    "_statusLabel(a.status)",
                    "_statusLabel(s.status)",
                    "_statusLabel(pa.status)"):
        assert labeled in js, f"{labeled} must render the label"
    # A capped row names both bands, never the codes.
    assert "esc(_severityLabel(cap.stored_severity)" in js
    assert "(cap.severity || '')) + '</span>'" not in js


def test_statuses_and_perspectives_have_arabic_labels():
    """The codes the API sends are translated, not printed through.

    Workflow statuses are stored English names and perspective labels arrive in
    English from the engine, so both need a dictionary entry to read as one
    vocabulary in the Arabic UI.
    """
    i18n = _read(JS / "i18n.js")
    for key in ("'New':", "'Under Review':", "'Confirmed Issue':",
                "'False Positive':", "'Resolved':",
                "'Hospital history':", "'Similar hospitals (type)':",
                "'Ownership peers':", "'Facility-type peers':",
                "'Regional peers (governorate)':",
                "'Prior-months baseline':",
                "'Search hospital / indicator':"):
        assert key in i18n, f"missing Arabic label for {key}"


def test_total_kpi_is_named_for_the_unit_it_counts():
    """The card counts grouped issues, so it says issues, not alerts.

    Two units share this screen (perspective rows and grouped issues). A card
    called "Total active alerts" over ``total_issues`` read like the row count
    the dashboard publishes beside it.
    """
    frag = _read(TABS / "quality-alerts.html")
    assert 'data-i18n="Total issues"' in frag
    assert "Total active alerts" not in frag
    i18n = _read(JS / "i18n.js")
    assert "'Total issues':" in i18n
    assert "'Total active alerts':" not in i18n


def test_status_filter_states_its_open_scope_before_metadata_loads():
    """An empty status filter means OPEN alerts, so it must say so at once.

    The fragment said "All" until the metadata fetch replaced it, which read as
    a closed-inclusive scope for the first moment of every visit.
    """
    frag = _read(TABS / "quality-alerts.html")
    select = next(line for line in frag.splitlines()
                  if 'id="qaStatusFilter"' in line)
    assert "Open only" in select
    assert ">All<" not in select


# ── Very High filter vs the two Very High cards ────────────────────────────

def test_very_high_filter_and_cards_state_how_they_relate():
    """The filter and the cards count the same issues differently, so say how.

    ``severity=VERY_HIGH`` lists an issue when AT LEAST ONE perspective is Very
    High, while the "Very High only" card means EVERY fired perspective is Very
    High and "Mixed severity" means a lower band fired too. On the live store
    that is 667 + 550 = 1,217, which read as three disagreeing numbers with the
    rule stated nowhere on the screen.
    """
    js = _read(JS / "quality-alerts.js")
    assert "function _renderSeverityReconcile(" in js
    assert "_renderSeverityReconcile(s)" in js, "the line must be fed by the summary"
    for field in ("s.very_high_only_issues", "s.mixed_severity_issues",
                  "s.total_issues"):
        assert field in js, f"reconciliation must read {field}"
    # The two cards ARE the Very High population, so the line adds them up
    # instead of quoting a third figure counted a different way.
    assert "const veryHigh = only + mixed;" in js

    frag = _read(TABS / "quality-alerts.html")
    assert 'id="qaSeverityReconcile"' in frag
    # The old note claimed every other severity was excluded, which the Very
    # High filter never did: a mixed issue carries a lower band and is listed.
    assert "Showing only Very High alerts" not in frag
    assert "at least one Very High perspective" in frag

    # A single-perspective issue has no lower band by default, so the bucket's
    # label does not claim agreement between perspectives. The split itself
    # (corroborated vs single perspective, with shares and the sum) is stated on
    # the "Very High only" card, so the line must not quote it a second time.
    assert "'no lower band'" in js
    reconcile = js[js.index("function _renderSeverityReconcile("):]
    reconcile = reconcile[:reconcile.index("function _updateChipCounts")]
    for duplicated in ("very_high_single_perspective_issues",
                       "very_high_only_corroborated_issues",
                       "with only one perspective fired",
                       "corroborated by 2+ perspectives"):
        assert duplicated not in reconcile, \
            f"the split belongs to the card, not the line: {duplicated}"
    # The fired sets stay one hover away, so the distribution is still reachable.
    assert "s.very_high_only_by_perspectives" in reconcile

    i18n = _read(JS / "i18n.js")
    for key in ("'no lower band':",
                "'Perspectives that fired on the Very High only issues':",
                "'mixed':", "'total in view':",
                "'No lower band on any perspective':",
                "'Very High lists any issue with at least one Very High "
                "perspective"):
        assert key in i18n, f"missing Arabic label for {key}"


def test_perspective_chip_carries_its_own_band():
    """A row listed as Very High shows which perspective was Very High.

    Without the per-perspective band the chips only named the reference groups,
    so a mixed issue looked exactly like an every-perspective one.
    """
    js = _read(JS / "quality-alerts.js")
    assert "p.severity === 'VERY_HIGH' ? 'badge-critical' : 'badge-muted'" in js
    assert "_severityLabel(p.severity)" in js, "the chip tooltip states the band"


def test_very_high_cards_are_clickable_filters():
    """The two cards filter the list to exactly the number they show.

    They used to be read-only numbers beside a filter that selected a different
    population, so the only way to know which rows a card counted was to trust
    it. Each card now sends ``very_high_scope``, keeps its own unscoped count
    while active, and clears on a second click.
    """
    frag = _read(TABS / "quality-alerts.html")
    for card, scope in (("qaCardVeryHighOnly", "only"),
                        ("qaCardCorroborated", "corroborated"),
                        ("qaCardMixed", "mixed")):
        line = next(l for l in frag.splitlines() if f'id="{card}"' in l)
        assert f"qualityAlertsToggleVeryHighScope('{scope}')" in line
        assert 'role="button"' in line, f"{card} must be operable, not decoration"
        assert 'tabindex="0"' in line, f"{card} must be reachable by keyboard"

    js = _read(JS / "quality-alerts.js")
    assert "export function qualityAlertsToggleVeryHighScope(scope)" in js
    assert "p.set('very_high_scope', _state.vhScope)" in js
    assert "_state.vhScope = _state.vhScope === scope ? null : scope;" in js, \
        "a second click must clear the filter"
    # D4: the band and the card scope INTERSECT, so neither control moves the
    # other. "High" + "Very High only" stays exactly as chosen and is allowed
    # to be empty — the empty state explains it.
    assert "_state.vhScope = null;" not in js, (
        "changing the severity must not silently drop the card scope")
    assert "severityEl.value = 'VERY_HIGH'" not in js, (
        "choosing a card must not silently change the severity")
    assert "function _renderEmptyState()" in js
    assert "_renderScopeCards()" in js
    assert "'is-active'" in js

    app_js = _read(JS / "app.js")
    assert "_bind(mod, 'qualityAlertsToggleVeryHighScope')" in app_js, \
        "the inline onclick needs the module function bound to the window"

    css = _read(STATIC / "css" / "styles.css")
    assert ".kpi-card.is-active" in css, "the active filter must be visible"

    i18n = _read(JS / "i18n.js")
    for key in ("'click a card to filter':", "'click the card again to clear':",
                "'Corroborated':", "'Very High on 2+ perspectives':"):
        assert key in i18n, f"missing Arabic label for {key}"


def test_very_high_only_card_states_the_two_subgroups_it_is_made_of():
    """The card is a total, so it renders the parts and their shares.

    "No lower band on any perspective" is satisfied vacuously by an issue where
    only one comparison fired, so a bare total reads like agreement between
    comparisons. The card now splits itself into Corroborated (2+ distinct
    perspectives, all Very High) and Single perspective, prints each subgroup's
    share, and states the arithmetic that both add up to its value — all from
    server-computed counts, stamped on the screen rather than in a tooltip.
    """
    frag = _read(TABS / "quality-alerts.html")
    for element in ("qaVeryHighOnlySplit", "qaKpiOnlyCorroborated",
                    "qaKpiOnlyCorroboratedPct", "qaKpiOnlySingle",
                    "qaKpiOnlySinglePct", "qaKpiOnlySum"):
        assert f'id="{element}"' in frag, f"{element} must exist for the split"
    assert 'data-i18n="Single perspective"' in frag
    assert 'data-i18n="Corroborated"' in frag
    assert "Perspectives are not independent clinical evidence" in frag
    assert "Mixed severity means at least one perspective is Very High" in frag

    js = _read(JS / "quality-alerts.js")
    assert "function _renderVeryHighOnlyBreakdown(s)" in js
    assert "_renderVeryHighOnlyBreakdown(s)" in js, "must be fed by the summary"
    for field in ("s.very_high_only_breakdown", "b.total", "b.corroborated",
                  "b.single_perspective", "b.corroborated_pct",
                  "b.single_perspective_pct"):
        assert field in js, f"the split must render {field}"
    # One decimal on both shares, and the sum the card states.
    assert "toFixed(1) + '%'" in js
    assert "n(corroborated) + ' + ' + n(single) + ' = ' + n(total)" in js
    # A count of zero is a count, not a share: the empty-scope wording replaces
    # a 0.0% that would read as "none of a measured population".
    assert "'No Very High only issues in this scope'" in js
    # Tooltips state what each card MEANS (the subset relation, and that the
    # perspectives are not independent clinical evidence), not just the click.
    assert "const _VH_SCOPE_HELP" in js
    assert "_VH_SCOPE_HELP[scope]" in js

    i18n = _read(JS / "i18n.js")
    for key in ("'Single perspective':", "'both add up to Very High only':",
                "'No Very High only issues in this scope':",
                "'Every perspective that fired is Very High",
                "'Corroborated is part of Very High only",
                "'Mixed severity means at least one perspective is Very High"):
        assert key in i18n, f"missing Arabic label for {key}"
    assert "زاوية مقارنة واحدة" in i18n

    # The tooltip is bilingual because it is composed at render time; the
    # fragment's static titles are the pre-render fallback.
    assert "Corroborated is part of Very High only" in frag


# ── Cap wording: three different reasons, never one sentence ────────────────

def test_cap_badges_name_the_cap_that_lowered_the_band():
    """Thin-peer, zero-spread and window refusals are three different claims.

    Both badges used to print "the comparison cannot be graded" for all three,
    which made a thin peer group read like a degenerate comparison and made a
    window refusal — where a scale WAS measured and disagreed — read like a
    comparison that could not be graded at all.
    """
    alerts = _read(JS / "quality-alerts.js")
    diagnostics = _read(JS / "layered.js")
    i18n = _read(JS / "i18n.js")
    for text, blocks in (
        ("no measurable spread: every value in the comparison is identical",
         {"quality-alerts.js": "cap.dispersion",
          "layered.js": "cap.zero_spread_layers"}),
        ("too few peer hospitals to measure a spread",
         {"quality-alerts.js": "cap.thin_peer_group",
          "layered.js": "cap.thin_peer_group"}),
        ("the hospital\\u2019s own history window does not support the top band",
         {"quality-alerts.js": "cap.very_high_eligibility",
          "layered.js": "cap.very_high_eligibility"}),
    ):
        for name, src in (("quality-alerts.js", alerts),
                          ("layered.js", diagnostics)):
            assert "'%s'" % text in src, f"{name} does not name this cap: {text}"
            assert blocks[name] in src, f"{name} does not select on {blocks[name]}"
        assert "'%s':" % text in i18n, f"missing Arabic label for: {text}"
    # The generic sentence survives only as the fallback for a block this build
    # does not recognise — never as the answer for a known cap.
    for src in (alerts, diagnostics):
        assert src.count("__('the comparison cannot be graded')") == 1, \
            "the generic sentence must exist exactly once: as _capReason's fallback"


def test_cap_badge_is_hidden_when_the_band_never_moved():
    """A cap block whose band equals the stored one is not a downgrade.

    Such a block exists whenever a cap RUNS (a degenerate comparison on a row
    already at HIGH), so printing "HIGH → HIGH" marked a row as lowered while
    its severity never changed. The provenance is kept; only the no-op is
    hidden.
    """
    for name in ("quality-alerts.js", "layered.js"):
        src = _read(JS / name)
        assert "cap.severity === cap.stored_severity" in src, name


def test_diagnostics_band_cells_print_translated_labels():
    """The stored CODE stays untouched; only what the cell prints is translated."""
    src = _read(JS / "layered.js")
    for code, label in (("VERY_HIGH", "Very High"), ("HIGH", "High"),
                        ("MODERATE", "Moderate"), ("LOW", "Low"),
                        ("NONE", "None")):
        assert "%s: '%s'" % (code, label) in src, code
    assert "_levelLabel(level)" in src
    assert "esc(level || 'NONE')" not in src, "the raw code must not reach the cell"
    i18n = _read(JS / "i18n.js")
    for label in ("Very High", "High", "Moderate", "Low", "None"):
        assert "'%s':" % label in i18n, f"missing Arabic label for {label}"

def test_multi_perspective_selection_is_a_server_filter():
    """Every chip rides the request; the page is not re-filtered in the browser."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "static", "js", "quality-alerts.js").read_text(encoding="utf-8")
    assert "p.append('perspective'" in src, "every selected chip is sent"
    assert "_visibleIssues" not in src, \
        "no second client-side interpretation of the same filter"
    assert "const issues = _state.issues;" in src


def test_very_high_cards_state_they_ignore_the_severity_filter():
    """A lower band must not read as a contradiction beside the VH cards."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "static", "js", "quality-alerts.js").read_text(encoding="utf-8")
    assert "Very High cards ignore the severity filter" in src


def test_empty_state_explains_an_empty_band_and_card_scope_intersection():
    """An empty list beside non-zero cards must say which pair emptied it."""
    frag = _read(TABS / "quality-alerts.html")
    assert 'id="qaEmptyIntersection"' in frag
    line = next(l for l in frag.splitlines()
                if 'id="qaEmptyIntersection"' in l)
    assert 'dir="auto"' in line, "the Arabic explanation needs its own direction"
    js = _read(JS / "quality-alerts.js")
    assert "function _renderEmptyState()" in js
    start = js.index("function _renderEmptyState()")
    body = js[start:start + 2400]
    assert "very_high_issues" in body, (
        "the empty state must repeat the KPI, not imply it is zero")
    for key in ("No issue satisfies both the selected severity and the card scope.",
                "The Very High cards still count",
                "because they ignore the severity and the card scope."):
        assert "'" + key + "'" in body, key



def test_status_control_only_offers_stored_states_and_never_sends_both():
    """The Status select is built from the server's own stored states.

    One status and "include the closed ones" are contradictory, so the query
    builder must send exactly one of them, and the include-closed sentinel must
    never be sent as a status value because it is not one (D6).
    """
    js = _read(JS / "quality-alerts.js")
    assert "const statuses = ((meta && meta.statuses) || [])" in js, \
        "the options must come from /quality-alerts/meta, not a local list"
    block = js[js.index("function _filterQuery()"):]
    block = block[:block.index("function _fillSelect")]
    assert "p.set('include_closed', '1')" in block
    assert "p.set('status', statusEl.value)" in block
    assert "else if (statusEl && statusEl.value)" in block, \
        "status and include_closed must stay mutually exclusive"
    assert "_ALL_STATUSES" in block


def test_audit_link_carries_the_indicator_code_end_to_end():
    """The alert's audit link, its URL builder and the boot parser must all
    agree on `indicator_code` — the audit screen resolves an indicator by code."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "static" / "js"

    def read(name):
        return (root / name).read_text(encoding="utf-8")

    alerts = read("quality-alerts.js")
    assert "indicatorCode: audit.indicator_code" in alerts, \
        "the detail link must forward the alert's indicator code"

    audit = read("audit.js")
    assert "indicator_code: opts.indicatorCode" in audit, \
        "openAuditTrailInNewTab forwards the code under the audit contract name"
    assert "params.set('indicator_code', opts.indicatorCode)" in audit, \
        "_trailQuery sends it to /audit/explain"

    main = read("main.js")
    assert "indicatorCode: params.get('indicator_code')" in main, \
        "the new tab's boot handler reads it back"

    api = (Path(__file__).resolve().parent.parent / "app" / "api" / "audit.py"
           ).read_text(encoding="utf-8")
    assert "indicator_code: str = Query(None)" in api, \
        "/audit/explain is the endpoint that consumes it"
