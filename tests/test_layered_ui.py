"""Static tests for the layered classification UI (design spec 2026-10-08 §10A/§10B).

Outliers-tab classification column first; the Layered tab (§10B) appends its
tab-registration tests here. Mirrors the test_outliers_js.py idiom: the tabs
are plain HTML/JS, so the contract lives in the file contents."""
import os


def _read(*parts):
    path = os.path.join(os.path.dirname(__file__), "..", "static", *parts)
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_outliers_table_has_classification_column_before_why():
    html = _read("tabs", "outliers.html")
    assert 'data-col="layered_type"' in html
    assert html.index('data-col="layered_type"') < html.index('data-i18n="Why"')
    # Column header + legend entry both carry the i18n key.
    assert html.count('data-i18n="Classification"') >= 2


def test_classification_badge_colors_follow_spec():
    """Spec §10A: red / orange / blue / amber, gray for NORMAL + unmatched."""
    js = _read("js", "outliers.js")
    assert "export function classificationBadge" in js
    for type_name, css_class in (
        ("POSSIBLE_DATA_ENTRY_ERROR", "badge-critical"),
        ("CLINICAL_INVESTIGATION_REQUIRED", "badge-medium"),
        ("PEER_ANOMALY", "badge-low"),
        ("VOLUME_DRIVEN_ANOMALY", "badge-amber"),
    ):
        assert type_name in js, type_name
        assert css_class in js, css_class
    assert "badge-muted" in js                      # NORMAL / unmatched / other
    assert "layered_type" in js and "layered_interpretation" in js


def test_outliers_colspan_grew_to_ten_columns():
    js = _read("js", "outliers.js")
    assert js.count('colspan="9"') == 0
    assert js.count('colspan="10"') == 3            # loading, error, empty rows


def test_outliers_csv_carries_classification():
    js = _read("js", "outliers.js")
    assert "'Classification'" in js
    assert "d.layered_type" in js


def test_outliers_why_button_still_opens_anomaly_explanation():
    """Spec §10A: the Why button is unchanged — classification rides in the
    badge tooltip (the one-line interpretation), not in a new popup path."""
    js = _read("js", "outliers.js")
    assert "showWhyPopup(\\'anomaly\\'" in js


def test_classification_badge_styles_exist():
    css = _read("css", "styles.css")
    assert ".badge-amber" in css
    assert ".badge-muted" in css


def test_classification_label_is_translated():
    i18n = _read("js", "i18n.js")
    assert "'Classification': '" in i18n
