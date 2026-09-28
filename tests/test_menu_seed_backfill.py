"""seed_menu new-tab backfill: new TAB_REGISTRY entries must reach existing DBs.

The default seed only runs when the menu table is empty, so tabs added to the
registry later (indicator-groups) would never appear for already-initialized
databases. The backfill appends missing registry tabs to the matching default
group without touching custom ordering/groups.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MenuGroup, MenuItem
from app.menu_registry import DEFAULT_GROUPS, TAB_REGISTRY
from scripts.seed_menu import seed_menu


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _group_of(session, tab_key):
    item = session.query(MenuItem).filter_by(tab_key=tab_key).first()
    return session.query(MenuGroup).filter_by(id=item.group_id).first() if item else None


def test_fresh_seed_contains_all_registry_tabs(session):
    seed_menu(session)
    seeded = {i.tab_key for i in session.query(MenuItem).all()}
    assert seeded == set(TAB_REGISTRY.keys())
    data_group = session.query(MenuGroup).filter_by(name="Data").first()
    item_keys = [i.tab_key for i in session.query(MenuItem).filter_by(group_id=data_group.id).all()]
    assert item_keys == ["upload", "indicator-tree", "indicator-groups", "rules-manager"]


def test_backfill_adds_new_tab_to_existing_db(session):
    # Simulate a DB seeded BEFORE indicator-groups existed.
    session.add(MenuGroup(name="Home", icon="", sort_order=0, is_active=True))
    session.flush()
    home = session.query(MenuGroup).filter_by(name="Home").first()
    session.add(MenuItem(group_id=home.id, tab_key="dashboard", sort_order=0))
    session.add(MenuGroup(name="Data", icon="", sort_order=1, is_active=True))
    session.flush()
    data = session.query(MenuGroup).filter_by(name="Data").first()
    session.add(MenuItem(group_id=data.id, tab_key="upload", sort_order=0))
    session.commit()

    added = seed_menu(session)

    # The fixture only pre-seeded 2 tabs, so the backfill brings the whole
    # remaining registry — indicator-groups must be among them, landing in
    # the Data group right after indicator-tree's default position.
    assert "indicator-groups" in added
    assert _group_of(session, "indicator-groups").name == "Data"
    keys = [i.tab_key for i in session.query(MenuItem).filter_by(group_id=data.id).all()]
    assert keys == ["upload", "indicator-tree", "indicator-groups", "rules-manager"]


def test_backfill_is_idempotent(session):
    seed_menu(session)
    assert seed_menu(session) == []
    assert session.query(MenuItem).count() == len(TAB_REGISTRY)


def test_backfill_falls_back_when_group_renamed(session):
    # The default "Data" group was renamed by an admin — the tab must still
    # become reachable instead of being silently dropped.
    session.add(MenuGroup(name="Old Home", icon="", sort_order=0, is_active=True))
    session.add(MenuGroup(name="Renamed Data", icon="", sort_order=1, is_active=True))
    session.flush()
    first = session.query(MenuGroup).filter_by(name="Old Home").first()
    session.add(MenuItem(group_id=first.id, tab_key="upload", sort_order=0))
    session.commit()

    seed_menu(session)

    assert _group_of(session, "indicator-groups").name == "Old Home"


def test_backfill_respects_deactivated_group(session):
    # An admin DEACTIVATED the Data group (hid that content) — the backfill
    # must not resurrect it via the fallback and must not add the tab to a
    # hidden group.
    session.add(MenuGroup(name="Home", icon="", sort_order=0, is_active=True))
    session.add(MenuGroup(name="Data", icon="", sort_order=1, is_active=False))
    session.flush()
    home = session.query(MenuGroup).filter_by(name="Home").first()
    session.add(MenuItem(group_id=home.id, tab_key="dashboard", sort_order=0))
    session.commit()

    seed_menu(session)

    assert session.query(MenuItem).filter_by(tab_key="indicator-groups").first() is None
