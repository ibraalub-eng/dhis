"""Static tests for the smart-analytics CSS extraction."""
import os


def _read_styles():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "styles.css")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_smart_mode_bar_css_present():
    css = _read_styles()
    assert ".smart-mode-bar" in css
    assert ".smart-mode-btn" in css
    assert ".smart-mode-btn.active" in css


def test_smart_section_and_kpi_css_present():
    css = _read_styles()
    assert ".smart-section-card" in css
    assert ".smart-kpi-grid" in css
    assert ".smart-priority-item" in css
    assert ".smart-badge-critical" in css


def test_smart_loader_and_error_css_present():
    css = _read_styles()
    assert ".smart-loader" in css
    assert ".smart-error-banner" in css
    assert ".smart-empty-state" in css


def test_smart_responsive_grid_uses_autofit():
    css = _read_styles()
    assert "repeat(auto-fit, minmax(" in css