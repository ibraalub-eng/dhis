"""Seed default menu groups into the database."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db
from app.models import MenuGroup, MenuItem
from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY


def seed_menu(session):
    """Idempotent: only seeds if menu_groups table is empty."""
    if session.query(MenuGroup).first() is not None:
        return
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


def seed():
    init_db()
    session = SessionLocal()
    try:
        seed_menu(session)
    finally:
        session.close()


if __name__ == "__main__":
    seed()