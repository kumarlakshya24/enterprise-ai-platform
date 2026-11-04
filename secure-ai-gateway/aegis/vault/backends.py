"""Key-value backends with TTL: Redis for deployments, in-memory for tests and single-process dev."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Protocol


class BackendUnavailable(RuntimeError):
    pass


class KVBackend(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int) -> None: ...
    def set_if_absent(self, key: str, value: str, ttl: int) -> bool: ...
    def incr(self, key: str, ttl: int) -> int: ...
    def delete(self, key: str) -> None: ...
    def ttl(self, key: str) -> int | None: ...
    def ping(self) -> bool: ...


class MemoryBackend:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def _alive(self, key: str) -> tuple[str, float] | None:
        item = self._data.get(key)
        if item is None:
            return None
        if item[1] <= self._clock():
            del self._data[key]
            return None
        return item

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._alive(key)
            return item[0] if item else None

    def set(self, key: str, value: str, ttl: int) -> None:
        with self._lock:
            self._data[key] = (value, self._clock() + ttl)

    def set_if_absent(self, key: str, value: str, ttl: int) -> bool:
        with self._lock:
            if self._alive(key) is not None:
                return False
            self._data[key] = (value, self._clock() + ttl)
            return True

    def incr(self, key: str, ttl: int) -> int:
        with self._lock:
            item = self._alive(key)
            n = int(item[0]) + 1 if item else 1
            expiry = item[1] if item else self._clock() + ttl
            self._data[key] = (str(n), expiry)
            return n

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def ttl(self, key: str) -> int | None:
        with self._lock:
            item = self._alive(key)
            return int(item[1] - self._clock()) if item else None

    def ping(self) -> bool:
        return True

    def dump(self) -> dict[str, str]:
        """Test helper: raw stored values (to prove no plaintext at rest)."""
        with self._lock:
            return {k: v for k, (v, _) in self._data.items()}


class RedisBackend:
    def __init__(self, url: str) -> None:
        import redis

        self._redis: Any = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2.0)
        self._errors: tuple[type[BaseException], ...] = (
            redis.exceptions.ConnectionError,
            redis.exceptions.TimeoutError,
        )

    def _call(self, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except self._errors as exc:
            raise BackendUnavailable("vault backend unavailable") from exc

    def get(self, key: str) -> str | None:
        v = self._call(lambda: self._redis.get(key))
        return str(v) if v is not None else None

    def set(self, key: str, value: str, ttl: int) -> None:
        self._call(lambda: self._redis.set(key, value, ex=ttl))

    def set_if_absent(self, key: str, value: str, ttl: int) -> bool:
        return bool(self._call(lambda: self._redis.set(key, value, ex=ttl, nx=True)))

    def incr(self, key: str, ttl: int) -> int:
        def _do() -> int:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl, nx=True)
            n, _ = pipe.execute()
            return int(n)

        result: int = self._call(_do)
        return result

    def delete(self, key: str) -> None:
        self._call(lambda: self._redis.delete(key))

    def ttl(self, key: str) -> int | None:
        v = int(self._call(lambda: self._redis.ttl(key)))
        return v if v >= 0 else None

    def ping(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:
            return False


def build_backend(redis_url: str) -> KVBackend:
    return RedisBackend(redis_url) if redis_url else MemoryBackend()
