"""In-memory log collector and /api/logs endpoint for superadmin viewing."""
import logging
import threading
import time
from collections import deque
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import require_permission

router = APIRouter(prefix="/logs", tags=["logs"])

# ---------------------------------------------------------------------------
# In-memory ring buffer that stores the last N log records
# ---------------------------------------------------------------------------
_MAX_ENTRIES = 500
_buffer: deque = []
_buffer_lock = threading.Lock()


class _BufferHandler(logging.Handler):
    """Logging handler that stores records in a thread-safe deque."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            with _buffer_lock:
                _buffer.append(entry)
                while len(_buffer) > _MAX_ENTRIES:
                    _buffer.popleft()
        except Exception:
            pass  # never let logging break the app


def install_buffer_handler(level: int = logging.WARNING) -> None:
    """Attach the ring-buffer handler to the root logger.

    Call once at startup (from main.py).  By default we capture WARNING+
    to avoid flooding memory with DEBUG/INFO from every request.
    """
    handler = _BufferHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------
@router.get("")
def get_logs(
    level: str = Query("WARNING", description="Minimum level: DEBUG, INFO, WARNING, ERROR, CRITICAL"),
    limit: int = Query(100, ge=1, le=500, description="Max entries to return"),
    user=Depends(require_permission("admin.manage")),
):
    """Return the most recent log entries stored in memory.

    Only accessible to superadmin users.
    """
    level_order = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_level = level_order.get(level.upper(), 2)

    with _buffer_lock:
        filtered = [e for e in _buffer if level_order.get(e["level"], 0) >= min_level]

    # Return most recent entries first
    recent = list(reversed(filtered[-limit:]))

    return {
        "total": len(filtered),
        "returned": len(recent),
        "min_level": level.upper(),
        "entries": recent,
    }
