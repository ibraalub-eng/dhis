"""Shared error-handling utilities for API endpoints.

Eliminates the repeated try/except/cache-invalidate/raise-500 pattern
that was duplicated across every endpoint in the project.
"""
import functools
import logging
from typing import Callable, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def safe_endpoint(
    error_msg: str = "خطأ في المعالجة",
    cache_keys: Optional[list] = None,
    invalidate_on_error: bool = True,
):
    """Decorator that wraps endpoint functions with standard error handling.

    Usage:
        @router.get("/some-endpoint/{month}")
        @safe_endpoint("خطأ في التحليل", cache_keys=["smart_overview_{month}"])
        def my_endpoint(month: str, db: Session = Depends(get_db)):
            ...

    Replaces:
        try:
            result = ...
            return result
        except Exception as e:
            cache.invalidate(f"smart_overview_{month}_")
            raise HTTPException(status_code=500, detail=f"خطأ في التحليل: {str(e)}")
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except HTTPException:
                raise  # Don't re-wrap known HTTP errors
            except Exception as e:
                logger.error(f"[safe_endpoint] {fn.__name__} failed: {e}", exc_info=True)
                # Invalidate cache keys if provided
                if invalidate_on_error and cache_keys:
                    _invalidate_caches(cache_keys, kwargs)
                raise HTTPException(status_code=500, detail=f"{error_msg}: {str(e)}")
        return wrapper
    return decorator


def _invalidate_caches(key_templates: list, kwargs: dict):
    """Invalidate cache entries using templates with endpoint kwargs.

    Example: key_templates=["smart_overview_{month}"], kwargs={"month": "2026-06"}
    """
    try:
        from app.core.cache import cache
        for template in key_templates:
            try:
                key = template.format(**kwargs)
            except (KeyError, IndexError):
                key = template  # Use as-is if no placeholders
            cache.invalidate(key)
            cache.invalidate(key + "_")  # Common suffix pattern
    except Exception:
        pass  # Don't let cache errors propagate


def get_envelope_or_empty(result: dict, section_key: Optional[str] = None):
    """Check if a smart analytics envelope has data, computing, or empty.

    Returns (response_dict, should_return) tuple.
    Callers do: resp, ok = get_envelope_or_empty(data); if ok: return resp

    Replaces the duplicated pattern:
        result = _get_envelope_or_empty(db, month)
        if "empty" in result or "computing" in result:
            return result
        data = result["data"]
        response = {"month": month, "section_data": data["section_key"]}
        return response
    """
    if "empty" in result or "computing" in result:
        return result, True
    if section_key:
        return {"data": result["data"][section_key]}, False
    return result, False
