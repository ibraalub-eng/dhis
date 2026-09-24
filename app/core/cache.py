"""Re-export of the shared TTLCache.

error_handler.safe_endpoint imported `app.core.cache`, a module that never
existed — the error-path cache invalidation silently no-opped. This shim
points it at the real app.cache so those invalidations actually run.
"""
from app.cache import (  # noqa: F401
    cache,
    TTLCache,
    get_data_epoch,
    refresh_data_epoch,
    compute_data_epoch,
)
