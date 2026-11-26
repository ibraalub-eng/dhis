import uuid
import threading
from datetime import datetime
from typing import Callable

_task_store: dict[str, dict] = {}
_lock = threading.Lock()


def create_task(name: str, fn: Callable = None, *args, meta: dict | None = None,
                **kwargs) -> str:
    task_id = uuid.uuid4().hex[:12]
    with _lock:
        _task_store[task_id] = {
            "id": task_id,
            "name": name,
            "status": "pending",
            "progress": 0,
            "result": None,
            "error": None,
            # What the task covers (months/hospital ids). The upload screen has
            # no task id to poll — /upload/ keeps its published response — so it
            # finds a running analysis by the months this metadata names.
            "meta": dict(meta or {}),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return task_id


def run_task(task_id: str, fn: Callable, *args, **kwargs):
    set_status(task_id, "running")
    try:
        result = fn(*args, **kwargs)
        with _lock:
            t = _task_store.get(task_id)
            if t:
                t["status"] = "done"
                t["progress"] = 100
                t["result"] = result
                t["updated_at"] = datetime.utcnow().isoformat()
    except Exception as e:
        with _lock:
            t = _task_store.get(task_id)
            if t:
                t["status"] = "error"
                t["error"] = str(e)
                t["updated_at"] = datetime.utcnow().isoformat()


def set_progress(task_id: str, progress: int):
    with _lock:
        t = _task_store.get(task_id)
        if t:
            t["progress"] = progress
            t["updated_at"] = datetime.utcnow().isoformat()


def set_status(task_id: str, status: str):
    with _lock:
        t = _task_store.get(task_id)
        if t:
            t["status"] = status
            t["updated_at"] = datetime.utcnow().isoformat()


def get_task(task_id: str) -> dict | None:
    with _lock:
        t = _task_store.get(task_id)
        if t:
            return dict(t)
        return None


def set_task_meta(task_id: str, meta: dict) -> None:
    """Attach or extend a task's scope (months, hospital ids)."""
    with _lock:
        t = _task_store.get(task_id)
        if t:
            merged = dict(t.get("meta") or {})
            merged.update(meta or {})
            t["meta"] = merged
            t["updated_at"] = datetime.utcnow().isoformat()


def list_tasks() -> list[dict]:
    """Snapshot every task, metadata included."""
    with _lock:
        return [{**t, "meta": dict(t.get("meta") or {})} for t in _task_store.values()]



