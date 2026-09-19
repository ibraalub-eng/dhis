"""Drift-guard regression tests for System Control.

These pin the two P1 bugs documented in
``docs/superpowers/plans/2026-09-19-system-control-cleanup.md``:

1. The Role UI Visibility Matrix must be derived from the real sidebar
   registry (``TAB_REGISTRY``), never from a hand-copied ``_TAB_DEFS`` that
   drifts (phantom ``hospitals`` tab, missing ``indicator-tree``,
   ``smart_analytics`` vs ``smart-analytics`` ids).
2. Every ``require_permission(...)`` codename used by the API must exist in
   ``CANONICAL_PERMISSION_CODENAMES`` — a guard with a codename that is never
   seeded can never be granted to any role (the ``admin.manage`` bug on
   /logs).
"""

import ast
import os
import re

import pytest

from app.menu_registry import TAB_REGISTRY
from app.main import CANONICAL_PERMISSION_CODENAMES


# ── Task 1: Visibility Matrix derives from TAB_REGISTRY ────────────


def test_admin_module_has_no_tab_defs():
    """The hand-copied _TAB_DEFS must not come back."""
    import app.api.admin as admin_api
    assert not hasattr(admin_api, "_TAB_DEFS"), (
        "_TAB_DEFS reappeared in app/api/admin.py — derive tabs from "
        "TAB_REGISTRY instead"
    )


def test_visibility_tabs_match_registry():
    """_visibility_tabs() must enumerate exactly the real sidebar tabs."""
    from app.api.admin import _visibility_tabs
    tabs = _visibility_tabs()
    assert set(tabs.keys()) == set(TAB_REGISTRY.keys()), (
        f"visibility tabs drifted from TAB_REGISTRY: "
        f"extra={set(tabs) - set(TAB_REGISTRY)}, "
        f"missing={set(TAB_REGISTRY) - set(tabs)}"
    )


def test_visibility_tabs_labels_and_permissions_from_registry():
    """Labels are 'icon + space + label' and permissions match the registry."""
    from app.api.admin import _visibility_tabs
    tabs = _visibility_tabs()
    for tab_id, spec in TAB_REGISTRY.items():
        t = tabs[tab_id]
        assert t["label"] == f"{spec['icon']} {spec['label']}"
        assert t["permission"] == spec["permission"]


def test_visibility_matrix_shape_unchanged(db_session):
    """The response shape (tabs dict + roles[].tab_access) must not change —
    consumers (admin.js Roles tab, tests) depend on it."""
    from app.models import Role
    db_session.add(Role(name="viewer", description="", is_system=True))
    db_session.commit()

    from app.api.admin import get_visibility_matrix
    result = get_visibility_matrix(db=db_session)
    assert set(result.keys()) == {"tabs", "roles"}
    for tab_id, entry in result["tabs"].items():
        assert set(entry.keys()) == {"label", "permission"}
    assert len(result["roles"]) >= 1
    for role in result["roles"]:
        assert set(role["tab_access"].keys()) == set(result["tabs"].keys())
        assert isinstance(role["is_superuser"], bool)


def test_visibility_matrix_marks_superuser(db_session):
    """The superadmin role must see every tab regardless of granted perms."""
    from app.models import Role
    db_session.add(Role(name="superadmin", description="", is_system=True))
    db_session.commit()

    from app.api.admin import get_visibility_matrix
    result = get_visibility_matrix(db=db_session)
    by_name = {r["name"]: r for r in result["roles"]}
    assert "superadmin" in by_name
    sa = by_name["superadmin"]
    assert sa["is_superuser"] is True
    assert all(sa["tab_access"].values()), "superadmin must see all tabs"


def test_registry_includes_real_sidebar_ids():
    """Sanity: the bug this guards against — real tabs present, phantom gone."""
    assert "indicator-tree" in TAB_REGISTRY
    assert "smart-analytics" in TAB_REGISTRY
    assert "hospitals" not in TAB_REGISTRY


# ── Task 2: permission guard codenames must be grantable ───────────


def _py_files_under_api():
    api_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
    for root, _dirs, files in os.walk(api_dir):
        if os.path.basename(root) in ("__pycache__",):
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def _extract_permission_literals(path):
    """Yield (codename, lineno) for every require_permission('<code>') literal."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            is_rp = (
                (isinstance(fn, ast.Name) and fn.id == "require_permission")
                or (isinstance(fn, ast.Attribute) and fn.attr == "require_permission")
            )
            if is_rp and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                yield node.args[0].value, node.lineno


def test_all_permission_guards_are_grantable():
    """Every require_permission codename in app/ must exist in the canonical
    (seeded) permission list — otherwise no role can ever be granted it."""
    app_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"
    )
    offenders = []
    for path in _py_files_under_api():
        rel = os.path.relpath(path, app_dir)
        for codename, lineno in _extract_permission_literals(path):
            if codename not in CANONICAL_PERMISSION_CODENAMES:
                offenders.append(f"{rel}:{lineno} -> '{codename}'")
    assert not offenders, (
        "require_permission codenames that are never seeded (so no role can "
        "be granted them):\n" + "\n".join(offenders)
    )
