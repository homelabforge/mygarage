"""`TTLCache`: entries expire, and the cache never outgrows its bound (B9)."""

from __future__ import annotations

from app.utils.ttl_cache import TTLCache


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_an_entry_lives_for_its_ttl() -> None:
    clock = _Clock()
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=10, max_size=4, clock=clock)
    cache.put("a", 1)
    clock.now = 9.9
    assert cache.get("a") == 1
    clock.now = 10.0
    assert cache.get("a") is None
    assert len(cache) == 0  # an expired entry is dropped when read


def test_the_oldest_entry_goes_past_the_bound() -> None:
    clock = _Clock()
    cache: TTLCache[int, int] = TTLCache(ttl_seconds=60, max_size=3, clock=clock)
    for key in range(5):
        clock.now = float(key)
        cache.put(key, key)
    assert len(cache) == 3
    assert [cache.get(k) for k in range(5)] == [None, None, 2, 3, 4]


def test_expired_entries_are_pruned_before_anything_is_evicted() -> None:
    clock = _Clock()
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=5, max_size=2, clock=clock)
    cache.put("old", 1)
    clock.now = 3
    cache.put("fresh", 2)
    clock.now = 6  # "old" has expired, "fresh" has not
    cache.put("new", 3)
    assert cache.get("fresh") == 2 and cache.get("new") == 3


def test_a_rewrite_refreshes_the_entry() -> None:
    clock = _Clock()
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=5, max_size=2, clock=clock)
    cache.put("a", 1)
    clock.now = 4
    cache.put("a", 2)
    clock.now = 8
    assert cache.get("a") == 2


def test_clear() -> None:
    cache: TTLCache[str, int] = TTLCache(ttl_seconds=5, max_size=2)
    cache.put("a", 1)
    cache.clear()
    assert cache.get("a") is None and len(cache) == 0
