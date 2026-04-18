"""Simple file-based cache with TTL for financial data."""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

_CACHE_DIR = Path(os.getenv("CACHE_DIR", "/tmp/stock_sentinel_cache"))
_DEFAULT_TTL = int(os.getenv("CACHE_TTL_SECONDS", 3600))  # 1 hour


def _cache_path(key: str) -> Path:
    hashed = hashlib.sha256(key.encode()).hexdigest()
    return _CACHE_DIR / f"{hashed}.json"


def _ensure_dir() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get(key: str) -> Any | None:
    """Return cached value or None if missing/expired."""
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if time.time() > data["expires_at"]:
            path.unlink(missing_ok=True)
            return None
        return data["value"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def set(key: str, value: Any, ttl: int = _DEFAULT_TTL) -> None:
    """Store value in cache with TTL."""
    _ensure_dir()
    payload = {"value": value, "expires_at": time.time() + ttl}
    _cache_path(key).write_text(json.dumps(payload, default=str))


def invalidate(key: str) -> None:
    _cache_path(key).unlink(missing_ok=True)


def clear_all() -> int:
    """Delete all cache files. Returns count deleted."""
    if not _CACHE_DIR.exists():
        return 0
    count = 0
    for f in _CACHE_DIR.glob("*.json"):
        f.unlink(missing_ok=True)
        count += 1
    return count


def cached(key: str, fn, ttl: int = _DEFAULT_TTL) -> Any:
    """Return cached result for key, or call fn() and cache it."""
    result = get(key)
    if result is None:
        result = fn()
        set(key, result, ttl)
    return result
