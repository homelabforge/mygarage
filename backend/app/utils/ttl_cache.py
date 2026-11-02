"""A small in-process cache whose entries expire and whose size is bounded.

For answers worth keeping for minutes (a public API's page, a DNS verdict)
in the single worker the app runs: an expired entry is dropped when it is
read or when room is needed, and past `max_size` the oldest entry goes, so
a long-running instance never keeps everything it was ever asked about.
Not thread-safe; the callers run on the event loop.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable


class TTLCache[K: Hashable, V]:
    """``key -> value`` for ``ttl_seconds``, at most ``max_size`` entries."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_size: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._clock = clock
        # Insertion order is age order: a rewrite moves the key to the end.
        self._entries: dict[K, tuple[float, V]] = {}

    def get(self, key: K) -> V | None:
        """The live value for ``key``, else None (an expired one is dropped)."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if self._clock() - stored_at >= self.ttl_seconds:
            del self._entries[key]
            return None
        return value

    def put(self, key: K, value: V) -> None:
        """Store ``value``, making room first: expired entries, then the oldest."""
        now = self._clock()
        self._entries.pop(key, None)
        if len(self._entries) >= self.max_size:
            for stale in [
                k for k, (at, _v) in self._entries.items() if now - at >= self.ttl_seconds
            ]:
                del self._entries[stale]
        while len(self._entries) >= self.max_size:
            del self._entries[next(iter(self._entries))]
        self._entries[key] = (now, value)

    def clear(self) -> None:
        """Forget everything."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
