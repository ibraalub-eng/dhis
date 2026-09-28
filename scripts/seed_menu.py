"""Seed default menu groups into the database."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db
from app.models import MenuGroup, MenuItem
from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY


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