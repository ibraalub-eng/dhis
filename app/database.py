from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

# SQLite needs check_same_thread=False + timeout for concurrent access.
# PostgreSQL does not need these.
_connect_args = {}
_engine_kwargs = {
    "pool_pre_ping": True,      # auto-reconnect dropped connections (Render idle)
    "pool_recycle": 300,         # recycle connections every 5 min
}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
    _connect_args["timeout"] = 30  # wait up to 30s for locked DB instead of failing
    _engine_kwargs["connect_args"] = _connect_args

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """No-op — Alembic manages all schema. Kept for backward compatibility."""
    pass