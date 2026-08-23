from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

_db_ready = False

if DATABASE_URL:
    _engine_kwargs = {
        "pool_pre_ping": True,      # auto-reconnect dropped connections (Render idle)
        "pool_recycle": 300,         # recycle connections every 5 min
    }
    # PostgreSQL-specific pool settings
    if DATABASE_URL.startswith("postgresql"):
        _engine_kwargs["pool_size"] = 5
        _engine_kwargs["max_overflow"] = 10

    engine = create_engine(DATABASE_URL, **_engine_kwargs)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _db_ready = True
else:
    engine = None
    SessionLocal = None

Base = declarative_base()


def get_db():
    if not _db_ready:
        raise RuntimeError("DATABASE_URL is not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """No-op — Alembic manages all schema. Kept for backward compatibility."""
    pass
