import os
import json
from typing import Any, Optional

CACHE_TTL = 300  # seconds — 5 minutes balances freshness vs hit rate
_VERSION_KEY = "profiles:v"

# Client initialisation

def _make_client():
    url = os.getenv("UPSTASH_REDIS_REST_URL", "")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return None
    try:
        from upstash_redis import Redis
        return Redis(url=url, token=token)
    except Exception:
        return None


# Module-level singleton — created once per cold start
_redis = _make_client()


def _client():
    return _redis


# Version helpers

def _get_version() -> str:
    r = _client()
    if not r:
        return "0"
    try:
        v = r.get(_VERSION_KEY)
        return str(v) if v is not None else "0"
    except Exception:
        return "0"


def invalidate_cache() -> None:
    """
    Bump the cache version counter.

    All existing cache keys reference the old version number, so they will
    never be served again. They expire naturally after CACHE_TTL seconds.
    No key scanning or mass deletion required.
    """
    r = _client()
    if not r:
        return
    try:
        r.incr(_VERSION_KEY)
    except Exception:
        pass


# Public cache operations

def cache_get(key: str) -> Optional[Any]:
    """Return the cached value for *key*, or None on miss / Redis unavailable."""
    r = _client()
    if not r:
        return None
    try:
        version = _get_version()
        full_key = f"v{version}:{key}"
        raw = r.get(full_key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        return None


def cache_set(key: str, value: Any) -> None:
    """Store *value* under *key* with the current version prefix and TTL."""
    r = _client()
    if not r:
        return
    try:
        version = _get_version()
        full_key = f"v{version}:{key}"
        r.set(full_key, json.dumps(value, default=str), ex=CACHE_TTL)
    except Exception:
        pass
