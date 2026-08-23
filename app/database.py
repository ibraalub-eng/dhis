import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

logger = logging.getLogger(__name__)
_db_ready = False

if DATABASE_URL:
    is_postgres = DATABASE_URL.startswith("postgresql")
    _engine_kwargs = {
        "pool_pre_ping": True,
    }

    if is_postgres:
        # Render free tier: 512MB RAM, 1 gunicorn worker.
        # 5 base + 10 overflow = 15 max connections (~150MB).
        _engine_kwargs["pool_size"] = 5
        _engine_kwargs["max_overflow"] = 10
        _engine_kwargs["pool_timeout"] = 30
        _engine_kwargs["pool_recycle"] = 1800

    engine = create_engine(DATABASE_URL, **_engine_kwargs)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _db_ready = True

    if is_postgres:
        logger.info("Database engine created (pool_size=5, max_overflow=10, recycle=1800s)")
    else:
        logger.info("Database engine created (SQLite)")
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


def get_pool_status():
    """Return connection pool stats for monitoring."""
    if not engine or not hasattr(engine, "pool"):
        return {}
    pool = engine.pool
    try:
        return {
            "pool_size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "total_connections": pool.size() + pool.overflow(),
        }
    except Exception:
        return {}


def init_db():
    """No-op - Alembic manages all schema. Kept for backward compatibility."""
    pass
