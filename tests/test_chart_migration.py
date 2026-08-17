"""Tests for Chart.js migration: verifies the root cause timeline chart
uses Chart.js instead of Plotly.js, and that all structural, API, and
visual contract requirements are met.

Covers:
- Task 2: chart-utils.js (CHART_COLORS, ciBandPlugin)
- Task 3: canvas element in root-cause.html
- Task 4: drawRcTimelineChart uses Chart.js
- Task 5: renderRcTimeline / renderRcTimelineChart wired correctly
- Task 6: API timeline endpoint returns correct data shape
"""
import os

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
_JS = os.path.join(_STATIC, "js")
_TABS = os.path.join(_STATIC, "tabs")
_VENDOR = os.path.join(_STATIC, "vendor")


def _read(rel_path):
    full = os.path.join(os.path.dirname(__file__), "..", rel_path)
    with open(full, "r", encoding="utf-8") as f:
        return f.read()


# ===================================================================
# 1. Structural / static-file checks (Tasks 2-5)
# ===================================================================

class TestChartUtilsExists:
    """Task 2: chart-utils.js must define CHART_COLORS and ciBandPlugin."""

    def test_chart_utils_file_exists(self):
        path = os.path.join(_JS, "chart-utils.js")
        assert os.path.isfile(path), "chart-utils.js not found"

    def test_chart_colors_defined(self):
        content = _read("static/js/chart-utils.js")
        assert "CHART_COLORS" in content
        assert "#0d9488" in content  # teal primary
        assert "#7c3aed" in content  # secondary purple

    def test_ci_band_plugin_defined(self):
        content = _read("static/js/chart-utils.js")
        assert "ciBandPlugin" in content
        assert "id: 'ciBand'" in content
        assert "beforeDraw" in content

    def test_ci_band_color_includes_alpha(self):
        content = _read("static/js/chart-utils.js")
        assert "rgba(124,58,237,0.12)" in content or "rgba" in content

    def test_exports_on_window(self):
        content = _read("static/js/chart-utils.js")
        assert "window.CHART_COLORS" in content
        assert "window.ciBandPlugin" in content


class TestChartJsLoaded:
    """Chart.js UMD bundle must be present and loaded in index.html."""

    def test_vendor_file_exists(self):
        path = os.path.join(_VENDOR, "chart.umd.min.js")
        assert os.path.isfile(path), "chart.umd.min.js not found in vendor/"

    def test_index_loads_chart_utils_before_chart(self):
        content = _read("static/index.html")
        cu_pos = content.find("chart-utils.js")
        chart_pos = content.find("chart.umd.min.js")
        assert cu_pos >= 0, "chart-utils.js not in index.html"
        assert chart_pos >= 0, "chart.umd.min.js not in index.html"
        assert cu_pos < chart_pos, "chart-utils.js must load before chart.umd.min.js"


class TestCanvasElement:
    """Task 3: root-cause.html must use a <canvas> element for the chart."""

    def test_canvas_element_present(self):
        content = _read("static/tabs/root-cause.html")
        assert 'id="rcTimelineChart"' in content

    def test_element_is_canvas(self):
        content = _read("static/tabs/root-cause.html")
        import re
        m = re.search(r'<canvas\s+id="rcTimelineChart"[^>]*>', content)
        assert m is not None, "rcTimelineChart should be a <canvas> element"
        assert "width:100%" in m.group() or "width: 100%" in m.group()

    def test_no_plotly_div_remain(self):
        """Old Plotly div should not be present."""
        content = _read("static/tabs/root-cause.html")
        assert "Plotly.newPlot" not in content
        assert "plotly" not in content.lower() or "plotly" in "plotly.min.js"


class TestDrawRcTimelineChart:
    """Task 4: drawRcTimelineChart must use Chart.js, not Plotly."""

    def test_draw_function_uses_chart_js(self):
        content = _read("static/js/settings.js")
        assert "new Chart(ctx," in content or "new Chart(" in content

    def test_no_plotly_in_draw_function(self):
        content = _read("static/js/settings.js")
        # Within the drawRcTimelineChart function scope, no Plotly calls
        assert "Plotly.newPlot" not in content
        assert "Plotly.react" not in content

    def test_uses_charts_primary_color(self):
        content = _read("static/js/settings.js")
        assert "CHART_COLORS.primary" in content

    def test_uses_charts_secondary_color(self):
        content = _read("static/js/settings.js")
        assert "CHART_COLORS.secondary" in content

    def test_two_datasets_defined(self):
        content = _read("static/js/settings.js")
        # The datasets array should have two entries: hospital + peer
        assert "المستشفى" in content  # hospital label in Arabic
        assert "متوسط النظير" in content  # peer mean label

    def test_ci_band_plugin_registered(self):
        content = _read("static/js/settings.js")
        assert "ciBandPlugin" in content

    def test_ci_band_data_passed_to_options(self):
        content = _read("static/js/settings.js")
        assert "peer_upper" in content
        assert "peer_lower" in content

    def test_chart_is_responsive(self):
        content = _read("static/js/settings.js")
        assert "responsive: true" in content
        assert "maintainAspectRatio: false" in content

    def test_legend_enabled(self):
        content = _read("static/js/settings.js")
        assert "legend:" in content
        assert "position:" in content

    def test_tooltip_configured(self):
        content = _read("static/js/settings.js")
        assert "tooltip:" in content

    def test_existing_chart_destroyed_before_rebuild(self):
        content = _read("static/js/settings.js")
        assert "destroy()" in content
        assert "_rcTimelineChartInstance" in content

    def test_dashed_peer_line(self):
        content = _read("static/js/settings.js")
        assert "borderDash" in content

    def test_interaction_mode(self):
        content = _read("static/js/settings.js")
        assert "intersect: false" in content
        assert "mode: 'index'" in content


class TestRenderRcTimeline:
    """Task 5: renderRcTimeline and renderRcTimelineChart exports."""

    def test_render_rc_timeline_exported(self):
        content = _read("static/js/settings.js")
        assert "export function renderRcTimeline()" in content

    def test_render_rc_timeline_chart_exported(self):
        content = _read("static/js/settings.js")
        assert "export function renderRcTimelineChart()" in content

    def test_render_rc_timeline_populates_dropdown(self):
        content = _read("static/js/settings.js")
        assert "rcTimelineIndicator" in content

    def test_handles_empty_data(self):
        content = _read("static/js/settings.js")
        assert "لا توجد بيانات زمنية كافية" in content

    def test_app_joins_and_exports(self):
        content = _read("static/js/app.js")
        assert "renderRcTimelineChart" in content
        assert "window.renderRcTimelineChart" in content


class TestTextDescription:
    """Timeline text description should reference Chart.js concepts."""

    def test_text_mentions_hospital_line(self):
        content = _read("static/js/settings.js")
        assert "الخط الصلب: قيمة المستشفى" in content

    def test_text_mentions_peer_dashed(self):
        content = _read("static/js/settings.js")
        assert "الخط المتقطع: متوسط النظير" in content

    def test_text_mentions_ci_band(self):
        content = _read("static/js/settings.js")
        assert "فاصل ثقة 95%" in content


# ===================================================================
# 2. API timeline endpoint tests
# ===================================================================

class TestTimelineAPI:
    """Verify the /root-cause/{id}/timeline endpoint returns data
    in the shape the Chart.js frontend expects."""

    @pytest.fixture()
    def _setup_timeline(self, db_session):
        from app.models import (
            Hospital, HospitalType, Indicator, IndicatorValue,
        )
        from app.engine.root_cause import _month_offset

        htype = HospitalType(name="TimelineGov")
        db_session.add(htype)
        db_session.flush()

        target = Hospital(name="TimelineTarget", hospital_type_id=htype.id, is_active=True)
        peers = [
            Hospital(name=f"TimelinePeer{i}", hospital_type_id=htype.id, is_active=True)
            for i in range(4)
        ]
        db_session.add_all([target] + peers)
        db_session.flush()

        code_to_id = {i.code: i.id for i in db_session.query(Indicator).all()}
        months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

        for h in [target] + peers:
            for mi, m in enumerate(months):
                base = 250 if h is target else 220
                db_session.add(IndicatorValue(
                    hospital_id=h.id, indicator_id=code_to_id["2"],
                    month=m, value=base + mi * 5,
                ))
                db_session.add(IndicatorValue(
                    hospital_id=h.id, indicator_id=code_to_id["6"],
                    month=m, value=base - 10 + mi * 5,
                ))
                db_session.add(IndicatorValue(
                    hospital_id=h.id, indicator_id=code_to_id["5"],
                    month=m, value=40 + mi * 2,
                ))
                db_session.add(IndicatorValue(
                    hospital_id=h.id, indicator_id=code_to_id["10"],
                    month=m, value=2 + mi * 0.5,
                ))
        db_session.commit()
        return target.id

    def test_timeline_returns_200(self, db_session, _setup_timeline):
        from app.main import app
        from app.database import get_db

        def override():
            yield db_session
        app.dependency_overrides[get_db] = override
        try:
            client = TestClient(app)
            resp = client.get(f"/root-cause/{_setup_timeline}/timeline?month=2026-06&months_back=6")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_timeline_structure(self, db_session, _setup_timeline):
        from app.main import app
        from app.database import get_db

        def override():
            yield db_session
        app.dependency_overrides[get_db] = override
        try:
            client = TestClient(app)
            data = client.get(f"/root-cause/{_setup_timeline}/timeline?month=2026-06&months_back=6").json()

            assert "indicators" in data
            assert "hospital_id" in data
            assert data["hospital_id"] == _setup_timeline

            for ind in data["indicators"]:
                assert "indicator_code" in ind
                assert "indicator_name" in ind
                assert "series" in ind
                assert len(ind["series"]) >= 2  # Need 2+ months for chart
                for pt in ind["series"]:
                    assert "month" in pt
                    assert "hospital_value" in pt
                    assert "peer_mean" in pt
                    assert "peer_lower" in pt
                    assert "peer_upper" in pt
                    assert "peer_count" in pt
        finally:
            app.dependency_overrides.clear()

    def test_timeline_ci_bands_are_valid(self, db_session, _setup_timeline):
        """CI lower must be <= peer_mean <= CI upper for each point."""
        from app.main import app
        from app.database import get_db

        def override():
            yield db_session
        app.dependency_overrides[get_db] = override
        try:
            client = TestClient(app)
            data = client.get(f"/root-cause/{_setup_timeline}/timeline?month=2026-06&months_back=6").json()

            for ind in data["indicators"]:
                for pt in ind["series"]:
                    if pt["peer_mean"] is not None and pt["peer_count"] > 1:
                        assert pt["peer_lower"] <= pt["peer_mean"], \
                            f"peer_lower {pt['peer_lower']} > peer_mean {pt['peer_mean']}"
                        assert pt["peer_mean"] <= pt["peer_upper"], \
                            f"peer_mean {pt['peer_mean']} > peer_upper {pt['peer_upper']}"
        finally:
            app.dependency_overrides.clear()

    def test_timeline_no_plotly_references(self):
        """The frontend code should not reference Plotly for the timeline chart."""
        content = _read("static/js/settings.js")
        # The drawRcTimelineChart function should not use Plotly
        assert "Plotly.newPlot" not in content
        assert "Plotly.react" not in content


class TestTimelineAPIEdgeCases:
    """Edge case: missing hospital, insufficient months."""

    def test_missing_hospital_returns_404(self, db_session):
        from app.main import app
        from app.database import get_db

        def override():
            yield db_session
        app.dependency_overrides[get_db] = override
        try:
            client = TestClient(app)
            resp = client.get("/root-cause/99999/timeline?month=2026-06&months_back=6")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_insufficient_months_yields_empty_indicators(self, db_session):
        """If a hospital has only 1 month of data, no indicators should be returned
        (minimum 2 months needed for a timeline chart)."""
        from app.main import app
        from app.database import get_db
        from app.models import Hospital, Indicator, IndicatorValue

        h = Hospital(name="SingleMonth", is_active=True)
        db_session.add(h)
        db_session.flush()
        ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
        db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=ind.id, month="2026-06", value=100))
        db_session.commit()

        def override():
            yield db_session
        app.dependency_overrides[get_db] = override
        try:
            client = TestClient(app)
            data = client.get(f"/root-cause/{h.id}/timeline?month=2026-06&months_back=3").json()
            assert len(data["indicators"]) == 0
        finally:
            app.dependency_overrides.clear()
