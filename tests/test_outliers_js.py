"""Static tests for outliers.js."""
import os


def _read_outliers():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "outliers.js")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_outliers_exports_expected_api():
    js = _read_outliers()
    for name in ["loadOutliers", "togglePeerPopover"]:
        assert f"export function {name}" in js or f"export async function {name}" in js, name


def test_outlier_rows_have_no_native_peer_tooltip():
    """The hospital-name cell must show only the hospital name.

    A native `title` attribute on <tr> makes a browser tooltip with peer
    mean/std/median pop up over the hospital name, which reads as the peer
    stats being attached to the hospital column.
    """
    js = _read_outliers()
    assert "\ttitle=" not in js
    assert "peerTip" not in js


def test_outlier_peer_cell_keeps_drill_down():
    """Removing the tooltip must not remove the clickable Peers cell."""
    js = _read_outliers()
    assert "togglePeerPopover" in js
    assert "peers_detail" in js


def test_peer_popover_keeps_fractional_rates():
    """Tiny-but-nonzero peer rates must not render as 0.00%."""
    js = _read_outliers()
    assert "toFixed(2)" in js
    assert "0.00%" not in js