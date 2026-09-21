"""Regression tests: the Quality Reports grid must NOT render gray
'Analysis disabled' cards for reports flagged is_enabled=false (months with
no analyzed data — e.g. the poisoned '__all__' rows the old tree save bug
created). They are hidden and summarized in a count note instead.
"""

from pathlib import Path

JS_PATH = Path(__file__).resolve().parent.parent / "static" / "js" / "upload.js"
I18N_PATH = Path(__file__).resolve().parent.parent / "static" / "js" / "i18n.js"


def test_disabled_reports_are_hidden_not_rendered():
    js = JS_PATH.read_text(encoding="utf-8")
    start = js.index("export function filterQualityReports")
    src = js[start:js.index("\n        let currentValidation")]
    # strip // comments so doc comments don't trip the 'must be gone' checks
    code = "\n".join(ln for ln in src.split("\n") if not ln.strip().startswith("//"))
    # disabled rows must be filtered OUT of the card list...
    assert "r.is_enabled === false" in code
    # ...and no code path may append a 'report-card disabled' element anymore
    assert "report-card disabled" not in code, (
        "the gray 'Analysis disabled' card must not be rendered anymore"
    )
    assert "Analysis disabled" not in code
    # a count note must be appended when disabled reports exist
    assert "qualityDisabledNote" in code
    assert "disabled report(s) not shown" in code


def test_disabled_note_is_translated():
    i18n = I18N_PATH.read_text(encoding="utf-8")
    assert "'disabled report(s) not shown':" in i18n


def test_empty_state_still_shows_when_nothing_at_all():
    js = JS_PATH.read_text(encoding="utf-8")
    start = js.index("export function filterQualityReports")
    src = js[start:js.index("\n        let currentValidation")]
    # the 'no reports match' empty state must survive and consider disabled rows
    assert "No reports match the selected filters." in src
    assert "!filtered.length && !disabled.length" in src
