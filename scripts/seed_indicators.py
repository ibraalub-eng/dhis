"""Seed the indicator definitions into the database."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, init_db
from app.models import Indicator
from app.indicators import INDICATOR_FLAT_LIST


def seed_indicators(session):
    """Seed indicators into the database using the given session."""
    existing = {ind.code for ind in session.query(Indicator).all()}
    if not existing:
        code_to_id = {}
        for ind in INDICATOR_FLAT_LIST:
            parent_id = None
            if ind["parent_id"] is not None and ind["parent_id"] in code_to_id:
                parent_id = code_to_id[ind["parent_id"]]
            db_ind = Indicator(
                code=ind["code"],
                name=ind["name"],
                parent_id=parent_id,
                level=ind["level"],
                group_name=ind.get("group_name", "SRMNH Inpatient Indicators"),
            )
            session.add(db_ind)
            session.flush()
            code_to_id[ind["code"]] = db_ind.id
    else:
        code_to_id = {}
        for db_ind in session.query(Indicator).all():
            code_to_id[db_ind.code] = db_ind.id
        for ind in INDICATOR_FLAT_LIST:
            if ind["code"] in code_to_id:
                continue
            parent_id = None
            if ind["parent_id"] is not None and ind["parent_id"] in code_to_id:
                parent_id = code_to_id[ind["parent_id"]]
            db_ind = Indicator(
                code=ind["code"],
                name=ind["name"],
                parent_id=parent_id,
                level=ind["level"],
                group_name=ind.get("group_name", "SRMNH Inpatient Indicators"),
            )
            session.add(db_ind)
            session.flush()
            code_to_id[ind["code"]] = db_ind.id
    if session.new:
        session.commit()


def seed():
    init_db()
    session = SessionLocal()
    try:
        seed_indicators(session)
    finally:
        session.close()


if __name__ == "__main__":
    seed()