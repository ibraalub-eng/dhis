"""Modal → screen navigation opens a NEW browser tab.

Every button inside a modal that leads to another screen (Why popup → Audit
screen / Audit trail, Quality Alert detail → Audit screen / Indicators
registry, clinical recommendations → Root Cause) used to call `SwitchTab`,
which replaced the screen the modal belonged to. The target screen now opens
as a new browser tab at `/dashboard?screen=<tab>&…`, and `applyBootScreen`
replays the context (hospital, month, scroll target, trail query) when that
tab loads.

The screens themselves are sidebar tabs in a single-page shell, so a "new
tab" can only mean a browser tab — the current one keeps its screen, filters
and scroll position.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "static", "js")


def _read(name):
    with open(os.path.join(JS, name), encoding="utf-8") as f:
        return f.read()


# ── The helper ──────────────────────────────────────────────────────────────

def test_helper_opens_a_browser_tab_with_the_screen_param():
    src = _read("newtab.js")
    assert "export function openScreenInNewTab" in src
    assert "anchor.target = '_blank'" in src
    assert "anchor.rel = 'noopener'" in src
    assert "SCREEN_PATH = '/dashboard'" in src
    assert "url.searchParams.set('screen', screen)" in src
    # exposed for inline onclick handlers
    assert "window.openScreenInNewTab = openScreenInNewTab" in src


def test_helper_drops_empty_context_but_keeps_falsy_zero():
    src = _read("newtab.js")
    # null/undefined/'' mean "no context", 0 is a real id
    assert "value === undefined || value === null || value === ''" in src


def _run_node(script: str):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def test_screen_url_is_built_from_the_app_origin_and_context():
    script = r"""
import { pathToFileURL } from 'node:url';
const clicked = [];
globalThis.document = {
    createElement: () => ({
        style: {},
        click() { clicked.push({ href: this.href, target: this.target, rel: this.rel }); },
        remove() {},
    }),
    body: { appendChild(node) { node._attached = true; } },
};
globalThis.window = { location: { origin: 'http://127.0.0.1:8000', href: '' } };
const m = await import(pathToFileURL('./static/js/newtab.js').href);
const audit = m.screenUrl('audit', { mode: 'why', hospital_id: 7, month: '2026-04', component: null });
const indicators = m.screenUrl('indicators');
m.openScreenInNewTab('audit', { hospital_id: 7, mode: 'trail', kind: 'quality_score' });
console.log(JSON.stringify({ audit, indicators, clicked }));
"""
    out = json.loads(_run_node(script))
    assert out["audit"].startswith("http://127.0.0.1:8000/dashboard?screen=audit")
    assert "mode=why" in out["audit"]
    assert "hospital_id=7" in out["audit"]
    assert "month=2026-04" in out["audit"]
    assert "component" not in out["audit"]          # null = no context
    assert out["indicators"].endswith("/dashboard?screen=indicators")
    assert len(out["clicked"]) == 1
    click = out["clicked"][0]
    assert click["target"] == "_blank" and click["rel"] == "noopener"
    assert "screen=audit" in click["href"] and "mode=trail" in click["href"]
    assert "kind=quality_score" in click["href"]


# ── Boot: the new tab lands on the requested screen with its context ────────

def test_app_boots_through_apply_boot_screen():
    app = _read("app.js")
    assert "applyBootScreen" in app
    assert "renderSidebar().then(function() { applyBootScreen(); })" in app
    # the dashboard is now the fallback inside applyBootScreen, not a hardcoded boot
    assert "renderSidebar().then(function() { switchTab('dashboard'); })" not in app


def test_boot_screen_switches_and_replays_context():
    src = _read("main.js")
    assert "export function applyBootScreen" in src
    assert "params.get('screen')" in src
    assert "switchTab(screen)" in src
    # modules bind asynchronously — the boot handler waits for the real one
    assert "_whenBound('openAuditTrail'" in src
    # audit jump context (hospital/month + scroll target)
    assert "_whenBound('_explainApplyJump'" in src
    # audit trail query
    assert "mode === 'trail'" in src
    # root cause context
    assert "screen === 'root-cause'" in src and "_whenBound('goRootCause'" in src
    # unknown/missing screen → dashboard
    assert "switchTab('dashboard')" in src


# ── The modal buttons that used to replace the current screen ───────────────

def test_why_popup_audit_jump_opens_a_new_tab():
    src = _read("explain.js")
    jump = src.split("window._explainJumpTo = function", 1)[1].split("\n};", 1)[0]
    assert "openScreenInNewTab('audit'" in jump
    assert "hospital_id:" in jump and "month:" in jump and "mode:" in jump
    # the in-page half stays available for the new tab's boot handler
    assert "window._explainApplyJump = function" in src
    # the popup's own footer goes through the same helper
    assert "window._explainJumpTo(hid, month, jump);" in src


def test_why_popup_audit_trail_opens_a_new_tab():
    src = _read("explain.js")
    trail = src.split("window._explainJumpTrail = function", 1)[1].split("\n};", 1)[0]
    assert "openAuditTrailInNewTab" in trail
    assert "openScreenInNewTab('audit'" in trail     # fallback when audit.js is absent


def test_audit_exposes_a_new_tab_trail():
    src = _read("audit.js")
    assert "export function openAuditTrailInNewTab" in src
    assert "window.openAuditTrailInNewTab = openAuditTrailInNewTab" in src
    # the in-page renderer stays (the boot handler calls it inside the new tab)
    assert "export function openAuditTrail(opts)" in src


def test_quality_alert_detail_links_open_new_tabs():
    src = _read("quality-alerts.js")
    assert "window.openAuditTrailInNewTab" in src
    assert "window.openScreenInNewTab" in src
    # the old same-tab switches are gone
    assert "window.SwitchTab && window.SwitchTab('indicators')" not in src
    assert "window.openAuditTrail && window.openAuditTrail(" not in src


def test_clinical_recommendation_root_cause_opens_a_new_tab():
    src = _read("validation.js")
    assert "window.openScreenInNewTab('root-cause'" in src
    assert "hospital_id: hid" in src
