"""Shared filesystem helpers for handling client-supplied names."""
import os

from fastapi import HTTPException


def safe_upload_name(name: str | None) -> str:
    """Return a safe basename for a client-supplied upload filename.

    Strips any directory components (both POSIX ``/`` and Windows ``\\``
    separators) so a crafted name such as ``../../etc/passwd`` or
    ``..\\..\\win.ini`` cannot escape the upload directory when joined with
    it. Rejects empty, dot, and traversal-only names with HTTP 400.
    """
    candidate = (name or "").replace("\\", "/")
    base = os.path.basename(candidate).strip()
    if not base or base in {".", ".."} or "/" in base or "\\" in base:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return base
