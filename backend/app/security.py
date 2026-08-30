"""Shared security dependency: the local-token guard.

Kept in its own module so both main.py and the profile router can depend on it
without importing each other (avoids a circular import).
"""
from typing import Optional

from fastapi import Header, HTTPException

from .config import settings


def require_token(x_local_token: Optional[str] = Header(default=None)) -> None:
    if x_local_token != settings.LOCAL_TOKEN:
        raise HTTPException(status_code=401, detail="Bad or missing X-Local-Token")
