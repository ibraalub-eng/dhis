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
