"""
Small shared helpers: an async HTTP getter and a TTL cache.

Every outbound call goes through here so timeouts, error handling and caching
are consistent, and a failing upstream never crashes a request — callers get
None (or a cached value) and decide how to degrade.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from config import settings

# --- naive in-process TTL cache (fine for a single-instance demo) ----------
_cache: dict[str, tuple[float, Any]] = {}


def cache_get(key: str) -> Optional[Any]:
    hit = _cache.get(key)
    if not hit:
        return None
    expires, value = hit
    if time.time() > expires:
        _cache.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any, ttl: Optional[int] = None) -> None:
    ttl = settings.CACHE_TTL_SECONDS if ttl is None else ttl
    _cache[key] = (time.time() + ttl, value)


async def get_json(
    url: str, params: Optional[dict] = None, headers: Optional[dict] = None
) -> Optional[Any]:
    """GET a URL and parse JSON. Returns None on any failure."""
    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return None


async def get_text(
    url: str, params: Optional[dict] = None, headers: Optional[dict] = None
) -> Optional[str]:
    """GET a URL and return text (used for RSS). Returns None on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=settings.REQUEST_TIMEOUT, follow_redirects=True
        ) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.text
    except Exception:
        return None
