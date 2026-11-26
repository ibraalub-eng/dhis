"""Seed default menu groups into the database."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db
from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY
from app.models import MenuGroup, MenuItem


def _prune_retired_tabs(session):
    """Delete menu items for screens that no longer exist in TAB_REGISTRY.

    Retiring a tab is done by removing it from the registry, but a database
    seeded before that keeps its menu row, and that row would render as a bare
    tab key with no label and no permission. Pruning keeps every existing
    database in step on its next startup (the seed only runs on an empty menu
    table, and the backfill below only ever ADDS).
    """
    retired = [item for item in session.query(MenuItem).all()
               if item.tab_key not in TAB_REGISTRY]
    if not retired:
        return []
    removed = sorted({item.tab_key for item in retired})
    for item in retired:
        session.delete(item)
    session.commit()
    print(f"[menu] Removed retired tab(s): {', '.join(removed)}")
    return removed


def _backfill_new_tabs(session):
    """Add menu items for registry tabs that are missing from every group.

    The seed above only runs on an empty menu table, so tabs added to
    TAB_REGISTRY later would never appear for already-initialized databases.
    Backfilling per item (instead of only on empty) keeps an admin's custom
    groups/ordering intact while making new screens reachable. Items are
    appended to the end of the DEFAULT group that lists the tab, preserving
    any custom ordering for tabs that already exist.
    """
    added = []
    items = session.query(MenuItem).all()
    by_group = {}
    for item in items:
        by_group.setdefault(item.group_id, []).append(item)
    for group_def in DEFAULT_GROUPS:
        for tab_key in group_def["items"]:
            if tab_key not in TAB_REGISTRY:
                continue
            if any(item.tab_key == tab_key for item in items):
                continue
            # Prefer the group whose name matches the default layout. A group
            # that was RENAMED or deleted gets a first-active fallback so the
            # tab stays reachable; a group that was DEACTIVATED is respected —
            # the admin deliberately hid that content.
            # Prefer the section that already holds a sibling tab from this
            # default layout: a renamed section (e.g. "Oversight" renamed to
            # "Quality") keeps receiving its new screens instead of the tab
            # landing in whichever group happens to be first.
            sibling_group_ids = {
                item.group_id for item in items
                if item.tab_key in group_def["items"] and item.tab_key != tab_key
            }
            target = None
            if sibling_group_ids:
                target = (
                    session.query(MenuGroup)
                    .filter(MenuGroup.id.in_(sibling_group_ids), MenuGroup.is_active.is_(True))
                    .order_by(MenuGroup.sort_order, MenuGroup.id)
                    .first()
                )
            if target is None:
                target = (
                    session.query(MenuGroup)
                    .filter(MenuGroup.name == group_def["name"], MenuGroup.is_active.is_(True))
                    .first()
                )
            if target is None and not session.query(MenuGroup).filter(
                MenuGroup.name == group_def["name"]
            ).first():
                target = (
                    session.query(MenuGroup)
                    .filter(MenuGroup.is_active.is_(True))
                    .order_by(MenuGroup.sort_order, MenuGroup.id)
                    .first()
                )
            if target is None:
                continue
            max_order = max((i.sort_order for i in by_group.get(target.id, [])), default=-1)
            session.add(MenuItem(group_id=target.id, tab_key=tab_key, sort_order=max_order + 1))
            added.append(tab_key)
    if added:
        session.commit()
    return added


def seed_menu(session):
    """Seed default menu groups when empty; backfill new registry tabs otherwise.

    Returns the list of tab keys backfilled (empty for a fresh seed).
    """
    if session.query(MenuGroup).first() is not None:
        _prune_retired_tabs(session)
        return _backfill_new_tabs(session)
    for idx, group_def in enumerate(DEFAULT_GROUPS):
        group = MenuGroup(
            name=group_def["name"],
            icon=group_def["icon"],
            sort_order=idx,
            is_active=True,
        )
        session.add(group)
        session.flush()
        for item_idx, tab_key in enumerate(group_def["items"]):
            session.add(MenuItem(
                group_id=group.id,
                tab_key=tab_key,
                sort_order=item_idx,
            ))
    session.commit()
    return []


def seed():
    init_db()
    session = SessionLocal()
    try:
        seed_menu(session)
    finally:
        session.close()


if __name__ == "__main__":
    seed()
