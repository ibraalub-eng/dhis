"""The upload screen must show each month's analysis state after an upload.

The month rows exist as soon as the import commits, while the analysis still
runs in the background, so the upload tab reported nothing and a fresh month
looked empty. These tests pin the panel, the month-keyed status reader and the
three states it renders.
"""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_upload_tab_has_a_month_status_panel():
    html = _read("static", "tabs", "upload.html")
    assert 'id="monthAnalysisStatus"' in html


def test_upload_js_reads_status_by_month_not_by_task():
    js = _read("static", "js", "upload.js")
    assert "showMonthAnalysisStatus" in js
    assert "resumeMonthAnalysisStatus" in js
    assert "/upload/analysis-status?months=" in js


def test_upload_js_shows_the_panel_while_the_analysis_runs():
    js = _read("static", "js", "upload.js")
    # Started as soon as the file is confirmed (preview months are known), and
    # resumed when the tab is opened while a background run is already going.
    confirm = js.split("export function confirmImport")[1].split("export function cancelPreview")[0]
    assert "showMonthAnalysisStatus(previewMonths)" in confirm
    assert "previewMonths = months.slice()" in js
    init = js.split("export function initUploadTab")[1].split("let previewFilePath")[0]
    assert "resumeMonthAnalysisStatus()" in init


def test_upload_js_renders_the_three_states_and_polls_until_final():
    js = _read("static", "js", "upload.js")
    for state in ("analyzing", "complete", "failed", "pending"):
        assert state + ":" in js, state
    body = js.split("export function showMonthAnalysisStatus")[1].split("export function resumeMonthAnalysisStatus")[0]
    assert "setTimeout(tick, 2500)" in body
    assert "busy" in body


def test_upload_result_still_renders_month_status():
    js = _read("static", "js", "upload.js")
    body = js.split("export function displayResults")[1].split("function _setHtml")[0]
    assert "showMonthAnalysisStatus(result.months)" in body
