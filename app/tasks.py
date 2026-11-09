import uuid
import threading
from datetime import datetime
from typing import Callable

_task_store: dict[str, dict] = {}
_lock = threading.Lock()


def create_task(name: str, fn: Callable = None, *args, **kwargs) -> str:
    task_id = uuid.uuid4().hex[:12]
    with _lock:
        _task_store[task_id] = {
            "id": task_id,
            "name": name,
            "status": "pending",
            "progress": 0,
            "result": None,
            "error": None,
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



