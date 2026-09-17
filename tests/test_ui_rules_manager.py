"""Static checks for the Rules Manager frontend module (static/js/rules.js)."""
import os
from types import SimpleNamespace


def _read_rules_js():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "rules.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_settings_js():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "settings.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_rules_js_imports_confirm_destructive():
    """deleteRule() awaits confirmDestructive(). Without the import the rule
    delete buttons silently no-op because confirmDestructive is module-scoped
    (confirm-modal.js) and never exposed on window."""
    js = _read_rules_js()
    assert "import { confirmDestructive } from './confirm-modal.js';" in js


def test_rules_js_uses_confirm_destructive():
    """Sanity guard: the delete confirmation path must actually be present."""
    js = _read_rules_js()
    assert "confirmDestructive({" in js


# ── Formula comparison operator picker ─────────────────────────────

def test_formula_op_picker_rendered_in_builder():
    """The formula card renders an op dropdown bound to _vbOnOpChange with
    every supported operator as an option."""
    js = _read_rules_js()
    assert 'id="vb_op_select"' in js
    assert '_vbOnOpChange()' in js  # wired via inline onchange
    for op in ("=", "!=", ">", "<", ">=", "<="):
        assert op in js  # options built from _FORMULA_OP_ORDER
    assert "_FORMULA_OP_ORDER = ['=', '!=', '>', '<', '>=', '<=']" in js


def test_formula_op_saved_into_params():
    """_vbBuildParams includes op for formula rules, so the engine's
    dispatch_rule receives it via params."""
    js = _read_rules_js()
    formula_case = js.split("case 'formula':")[1].split("default:")[0]
    assert "op: _vbState.op" in formula_case
    assert "op: _vbState.op || '='" in formula_case  # never undefined


def test_formula_op_loaded_from_existing_params():
    """Editing a formula rule restores the saved op instead of resetting to '='."""
    js = _read_rules_js()
    # the formula branch of _vbLoadExistingParams must read params.op
    load_branch = js.split("_vbState.formulaParts = _formulaStringToParts(params.formula || '');")[1]
    assert "_vbState.op = params.op || '=';" in load_branch


def test_formula_op_state_reset_defaults_to_equals():
    """Every expr reset starts from op='=' so legacy rules without op behave unchanged."""
    js = _read_rules_js()
    assert "target:'', op:'='" in js


def test_formula_op_app_binding_present():
    """_vbOnOpChange must be bound in app.js, otherwise the inline onchange
    silently no-ops (same failure mode as the confirmDestructive import)."""
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "app.js")
    with open(path, encoding="utf-8") as f:
        app_js = f.read()
    assert "_bind(mod, '_vbOnOpChange')" in app_js


def test_formula_op_arabic_labels_present():
    """The operator relation texts and the picker tooltip have Arabic translations."""
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "i18n.js")
    with open(path, encoding="utf-8") as f:
        i18n = f.read()
    assert "'Comparison operator':" in i18n
    for key in (
        "formula result == target indicator",
        "formula result > target indicator",
        "formula result < target indicator",
        "formula result \\u2265 target indicator",
        "formula result \\u2264 target indicator",
        "formula result \\u2260 target indicator",
    ):
        assert f"'{key}':" in i18n


def test_formula_explanation_mentions_operators():
    """The expr explanation teaches users the op option exists."""
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "settings.js")
    with open(path, encoding="utf-8") as f:
        settings = f.read()
    assert '"op":">"' in settings
    assert "\u2265, \u2264" in settings or "≥, ≤" in settings


# ── Seeded formula rules with comparison operators ─────────────────

def _seed_rules_source():
    path = os.path.join(os.path.dirname(__file__), "..", "scripts", "seed_rules.py")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_seed_rules_include_op_formula_rules():
    """The catalog has formula rules beyond the original equality one, and
    every seeded formula rule carries a valid op (or none, which means =)."""
    from scripts.seed_rules import RULES
    src = _seed_rules_source()
    assert "R073" in src and "R076" in src  # new formula rules present
    valid_ops = {"=", "!=", ">", "<", ">=", "<="}
    formula = [r for r in RULES if r["expression_type"] == "formula"]
    assert len(formula) >= 5  # R072 equality + at least 4 op-bearing rules
    op_count = 0
    for r in formula:
        params = __import__("json").loads(r["params"])
        if "op" in params:
            assert params["op"] in valid_ops, (r["code"], params)
            op_count += 1
    assert op_count >= 4  # at least four rules actually use the operators


def test_seed_op_rules_dispatch_correctly(db_session):
    """The seeded op-bearing formula rules actually pass/fail through the real
    engine on plausible and implausible data."""
    import json as _json
    from scripts.seed_rules import RULES
    from app.engine.quality import ValidationContext, dispatch_rule, RuleStatus

    by_code = {r["code"]: r for r in RULES}

    def _run(code, values):
        spec = by_code[code]
        rule = SimpleNamespace(
            code=code, name=spec["name"], rule_type=spec["rule_type"],
            severity=spec["severity"], category=spec["category"],
            expression_type=spec["expression_type"], params=spec["params"],
            enabled=True, sort_order=0,
        )
        ctx = ValidationContext(
            values=values, hospital_name="T", month="2026-06",
        )
        return dispatch_rule(rule, ctx)

    # R073 Stillbirths <= Live Births: plausible passes, more stillbirths fails
    assert _run("R073", {"7": 3, "6": 100}).status == RuleStatus.PASS
    assert _run("R073", {"7": 100, "6": 100}).status == RuleStatus.PASS  # boundary: <=
    assert _run("R073", {"7": 101, "6": 100}).status == RuleStatus.FAIL

    # R074 Maternal Deaths < Total Deliveries: strict — equality fails
    assert _run("R074", {"11": 1, "2": 200}).status == RuleStatus.PASS
    assert _run("R074", {"11": 200, "2": 200}).status == RuleStatus.FAIL

    # R075 adolescent share strictly below 50% of deliveries
    assert _run("R075", {"2.c": 10, "2.d": 80, "2": 200}).status == RuleStatus.PASS
    assert _run("R075", {"2.c": 120, "2.d": 90, "2": 200}).status == RuleStatus.FAIL

    # R076 SMM < 25% of deliveries: 4*10=40 < 200 passes; 4*60=240 fails
    assert _run("R076", {"10": 10, "2": 200}).status == RuleStatus.PASS
    assert _run("R076", {"10": 60, "2": 200}).status == RuleStatus.FAIL

    # missing data must never fail a rule (formula unobservable -> PASS)
    assert _run("R074", {}).status == RuleStatus.PASS


# ── Bulk Enable/Disable-all persistence (rules manager) ─────────────

def _get_bulk_toggle_block():
    js = _read_settings_js()
    start = js.index("window.bulkToggleCategory = function")
    end = js.index("window.", start + 10)
    return js[start:end]


def test_bulk_toggle_persists_immediately():
    """Enable all / Disable all must PUT /rules/save-enabled right away instead
    of deferring to a manual Save click, and must never claim 'click Save'."""
    block = _get_bulk_toggle_block()
    assert "/rules/save-enabled" in block
    assert "authFetch(" in block
    assert "click Save to apply" not in block


def test_bulk_toggle_reloads_after_save():
    """After persisting, the rules manager must reload so the UI reflects the
    saved state (what the user sees matches the database)."""
    block = _get_bulk_toggle_block()
    assert "loadRulesManager(" in block


# ── Flat category-free table + Category filter ───────────────────────

def test_rules_table_has_no_category_sections():
    """The rules table renders one flat code-sorted list — no category
    header rows, no collapse toggles. Category moved to the filter bar."""
    js = _read_settings_js()
    assert 'rule-category-header' not in js, \
        "category header rows must be gone from the render path"
    assert 'Category collapse/expand' not in js
    # Rows carry their category as data so other tooling can still target them
    assert 'data-cat=' in js
    # Flat render sorts by code defensively
    assert "visible.slice().sort(function(a, b)" in js
    # Category column remains a per-row cell
    assert "esc(r.category)" in js


def test_rules_html_has_category_filter():
    """Category filtering lives in the filter bar as a dropdown."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "rules-manager.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    assert 'id="rulesCategoryFilter"' in html
    assert 'onchange="loadRulesManager()"' in html
    for cat in ("BASIC_LOGIC", "CLINICAL_CONSISTENCY", "CLINICAL_LOGIC",
                "PLAUSIBILITY", "STATISTICAL_BENCHMARK", "TREND_DATA_QUALITY"):
        assert cat in html, f"missing category option {cat}"


def test_load_rules_manager_sends_category_filter():
    """loadRulesManager must pass the selected category to the API, which
    already supports the category query param (server-side filter)."""
    js = _read_settings_js()
    assert "rulesCategoryFilter" in js
    assert "'category=' + encodeURIComponent(catFilter)" in js


# ── Sortable columns (Code / Severity / Affected Hospitals) ─────────

def test_rules_table_sortable_headers_declared():
    """Code, Severity, and Affected Hospitals headers carry the sortable
    class, a data-col key, and the inline onRulesSort() hook."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "rules-manager.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    for col in ("code", "severity", "impact"):
        assert f'data-col="{col}"' in html
        assert f"onRulesSort('{col}')" in html
    assert html.count('class="sortable"') == 3


def test_rules_sort_state_and_cycle_logic():
    """onRulesSort cycles asc → desc → default (code asc) and the render
    sorts by the active key: severity rank, impact count, or code."""
    js = _read_settings_js()
    assert "let _rulesSortCol = null;" in js
    assert "window.onRulesSort = function(col)" in js
    assert "_rulesSortAsc = false;" in js            # second click
    assert "_rulesSortCol = null; _rulesSortAsc = true;" in js  # third click
    assert "sevRank = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }" in js
    assert "_rulesSortCol === 'impact'" in js
    assert "hospitals_affected || []).length" in js


def test_rules_sort_indicators_applied_on_render():
    """Every render reapplies sort-asc/sort-desc classes to the headers."""
    js = _read_settings_js()
    assert "querySelectorAll('#rulesTable thead th.sortable')" in js
    assert "classList.add(_rulesSortAsc ? 'sort-asc' : 'sort-desc')" in js


# ── Search box clear button (no hard-coded auto-clear) ──────────────

def test_rules_search_has_clear_button():
    """The search row carries a ✕ button wired to clearRulesSearch(), and the
    input keeps its autofill defenses (autocomplete=off)."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "rules-manager.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    assert 'id="rulesSearchClear"' in html
    assert 'onclick="clearRulesSearch()"' in html
    assert 'autocomplete="off"' in html


def test_rules_search_not_force_cleared_on_load():
    """loadRulesManager must not silently wipe the search box (removed hard-
    coded auto-clear); the ✕ button is always visible in the toolbar and
    clearRulesSearch() is the single explicit clear path."""
    js = _read_settings_js()
    fn_start = js.index("export function loadRulesManager()")
    fn_src = js[fn_start:fn_start + 900]
    assert "searchBox.value = ''" not in fn_src
    assert 'id="rulesSearchClear"' not in js  # button lives in the tab HTML, static
    assert "window.clearRulesSearch" in js    # explicit clear handler


# ── Suggested rule name (New Rule modal) ────────────────────────────

def _read_index_html():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_i18n_js():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "i18n.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


RULES_MANAGER_EXPRS = [
    "ge", "gt", "ge_factor", "eq", "le", "lt", "le_sum",
    "benchmark_rate", "benchmark_low_rate", "cross_hospital_rate",
    "month_over", "month_under", "neg_check", "decimal_check",
    "missing", "all_zero", "formula",
]


def test_suggest_rule_name_function_exists():
    """suggestRuleName() must exist and have a suggestion template for every
    expression type the builder can produce."""
    js = _read_rules_js()
    assert "export function suggestRuleName(" in js
    fn_start = js.index("export function suggestRuleName(")
    tail = js[fn_start:]
    for expr in RULES_MANAGER_EXPRS:
        assert f"case '{expr}':" in tail, f"suggestRuleName missing template for {expr}"


def test_suggest_rule_name_uses_indicator_names():
    """The name must be built from human-readable indicator names (via
    _indicatorsCache), never raw codes, matching seeded rules like
    'Total Deliveries >= Normal Vaginal + ...'."""
    js = _read_rules_js()
    fn_start = js.index("export function suggestRuleName(")
    fn_src = js[fn_start:]
    assert "_indicatorsCache" in fn_src
    assert ".name" in fn_src
    # ge template is parent-first with '>=' and children joined by ' + '
    assert "+ '" in fn_src or "join(' + ')" in fn_src
    assert ">= " in fn_src or ">= '" in fn_src


def test_suggest_rule_name_preview_updates_in_builder():
    """Rebuilding the visual builder must refresh the live name suggestion
    preview so it tracks whatever the user has dropped in."""
    js = _read_rules_js()
    # buildVisualBuilder is called on every param change; it must call the
    # suggestion updater (which also hides the preview when not applicable).
    assert "buildVisualBuilder(expr) {" in js
    tail = js[js.index("function buildVisualBuilder(expr) {"):]
    assert "updateRuleNameSuggestion(" in tail


def test_suggest_rule_name_modal_ui_exists():
    """The New Rule modal must contain a suggestion preview span plus a way to
    apply it into the Name field."""
    html = _read_index_html()
    assert 'id="ruleNameSuggestion"' in html
    assert 'id="ruleEditName"' in html
    assert "onclick=\"applyRuleNameSuggestion()\"" in html


def test_apply_rule_name_suggestion_bound_and_exported():
    """applyRuleNameSuggestion() must be exported from rules.js (so app.js can
    bind it) and actually writes into the ruleEditName input."""
    js = _read_rules_js()
    assert "export function applyRuleNameSuggestion(" in js
    assert "ruleEditName" in js


def test_apply_rule_name_suggestion_bound_in_app_js():
    """Inline onclick=applyRuleNameSuggestion() needs it on window via _bind,
    otherwise the button silently no-ops (same failure mode as the
    confirmDestructive import)."""
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "app.js")
    with open(path, encoding="utf-8") as f:
        app_js = f.read()
    assert "_bind(mod, 'applyRuleNameSuggestion')" in app_js


def test_suggest_rule_name_i18n_keys_exist():
    """The suggestion preview label and the apply button carry translatable
    English keys (Arabic values must be present too, per i18n policy)."""
    i18n = _read_i18n_js()
    assert "'Suggested name:':" in i18n
    assert "'Use suggestion':" in i18n
