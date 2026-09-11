"""Cache layer with a Redis backend and an in-process fallback.

Redis matters when more than one process reads the books - an API replica, a
screener worker, a backtest - because they must all see the same snapshot.
A single-process run does not need it, so the fallback is a plain dict and the
service never fails to start just because Redis is absent.
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from backend.app.config import get_settings


class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: float | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def keys(self, prefix: str) -> list[str]: ...
    async def close(self) -> None: ...
    @property
    def backend(self) -> str: ...


class MemoryCache:
    """Dict with TTLs. Correct for one process, useless across replicas."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}

    async def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if expiry is not None and expiry < time.time():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        self._data[key] = (value, time.time() + ttl if ttl else None)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def keys(self, prefix: str) -> list[str]:
        now = time.time()
        return [
            key
            for key, (_, expiry) in list(self._data.items())
            if key.startswith(prefix) and (expiry is None or expiry >= now)
        ]

    async def close(self) -> None:
        self._data.clear()

    @property
    def backend(self) -> str:
        return "memory"


class RedisCache:
    def __init__(self, client) -> None:
        self._client = client

    async def get(self, key: str) -> Any | None:
        raw = await self._client.get(key)
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        payload = json.dumps(value, default=str)
        if ttl:
            await self._client.set(key, payload, ex=int(ttl))
        else:
            await self._client.set(key, payload)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def keys(self, prefix: str) -> list[str]:
        return [
            key.decode() if isinstance(key, bytes) else key
            async for key in self._client.scan_iter(match=f"{prefix}*")
        ]

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def backend(self) -> str:
        return "redis"


async def build_cache() -> Cache:
    settings = get_settings()
    if not settings.redis_url:
        return MemoryCache()
    try:
        import redis.asyncio as redis  # imported lazily: optional dependency

        client = redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        return RedisCache(client)
    except Exception:
        # A screener that refuses to boot because a cache is down is worse
        # than one that runs single-process.
        return MemoryCache()
