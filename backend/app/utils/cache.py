"""Simple in-memory TTL cache for analytics results."""

import asyncio
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import wraps
from typing import Any


class InMemoryCache:
    """Thread-safe in-memory cache with TTL support."""

    def __init__(self):
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._lock = asyncio.Lock()

    def generate_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """Generate a cache key from function name and arguments."""
        # Convert args and kwargs to a stable string representation
        key_parts = [func_name]

        # Add positional args
        for arg in args:
            if hasattr(arg, "id"):  # For database sessions, use id
                key_parts.append(f"session_{id(arg)}")
            else:
                key_parts.append(str(arg))

        # Add keyword args (sorted for consistency)
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}={v}")

        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    async def get(self, key: str) -> Any | None:
        """Get value from cache if not expired."""
        async with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if datetime.now() < expiry:
                    return value
                else:
                    # Clean up expired entry
                    del self._cache[key]
        return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 300):
        """Set value in cache with TTL."""
        expiry = datetime.now() + timedelta(seconds=ttl_seconds)
        async with self._lock:
            self._cache[key] = (value, expiry)

    async def delete(self, key: str):
        """Delete a specific key from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]

    async def clear(self):
        """Clear all cached data."""
        async with self._lock:
            self._cache.clear()

    async def clear_expired(self):
        """Remove all expired entries."""
        now = datetime.now()
        async with self._lock:
            expired_keys = [key for key, (_, expiry) in self._cache.items() if expiry <= now]
            for key in expired_keys:
                del self._cache[key]

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        now = datetime.now()
        active = sum(1 for _, expiry in self._cache.values() if expiry > now)
        return {
            "total_entries": len(self._cache),
            "active_entries": active,
            "expired_entries": len(self._cache) - active,
        }


# Global cache instance
cache = InMemoryCache()


def cached(ttl_seconds: int = 300):
    """
    Decorator to cache async function results with TTL.

    Args:
        ttl_seconds: Time to live in seconds (default: 5 minutes)

    Usage:
        @cached(ttl_seconds=600)
        async def expensive_function(param1, param2):
            # ... expensive computation
            return result
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Generate cache key
            cache_key = cache.generate_key(func.__name__, args, kwargs)

            # Try to get from cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # Call function and cache result
            result = await func(*args, **kwargs)
            await cache.set(cache_key, result, ttl_seconds)

            return result

        return wrapper

    return decorator


async def invalidate_cache_for_vehicle(vin: str):
    """
    Invalidate all cached analytics for a specific vehicle.
    This should be called when vehicle data is updated.
    """
    # For simplicity, we'll clear the entire cache
    # In production, you might want more granular cache key management
    await cache.clear()


async def clear_analytics_cache():
    """Clear all analytics cache entries."""
    await cache.clear()
