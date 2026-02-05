"""
Unit tests for in-memory TTL cache.

Tests cache operations, TTL expiration, decorator behavior, and statistics.
"""

import asyncio

import pytest

from app.utils.cache import InMemoryCache, cache, cached, clear_analytics_cache


@pytest.mark.unit
class TestInMemoryCache:
    """Test InMemoryCache class."""

    @pytest.fixture
    def test_cache(self):
        """Create a fresh cache instance for each test."""
        return InMemoryCache()

    def test_generate_key_basic(self, test_cache):
        """Test cache key generation with basic args."""
        key = test_cache.generate_key("my_function", ("arg1", "arg2"), {})
        assert isinstance(key, str)
        assert len(key) == 32  # MD5 hash length

    def test_generate_key_with_kwargs(self, test_cache):
        """Test cache key generation with keyword args."""
        key = test_cache.generate_key(
            "my_function", ("arg1",), {"key1": "value1", "key2": "value2"}
        )
        assert isinstance(key, str)

    def test_generate_key_consistency(self, test_cache):
        """Test that same args produce same key."""
        key1 = test_cache.generate_key("func", ("a", "b"), {"x": 1})
        key2 = test_cache.generate_key("func", ("a", "b"), {"x": 1})
        assert key1 == key2

    def test_generate_key_different_args(self, test_cache):
        """Test that different args produce different keys."""
        key1 = test_cache.generate_key("func", ("a",), {})
        key2 = test_cache.generate_key("func", ("b",), {})
        assert key1 != key2

    def test_generate_key_different_kwargs(self, test_cache):
        """Test that different kwargs produce different keys."""
        key1 = test_cache.generate_key("func", (), {"x": 1})
        key2 = test_cache.generate_key("func", (), {"x": 2})
        assert key1 != key2

    def test_generate_key_different_functions(self, test_cache):
        """Test that different function names produce different keys."""
        key1 = test_cache.generate_key("func1", ("a",), {})
        key2 = test_cache.generate_key("func2", ("a",), {})
        assert key1 != key2

    def test_generate_key_kwargs_order_independent(self, test_cache):
        """Test that kwargs order doesn't affect key."""
        # kwargs are sorted internally
        key1 = test_cache.generate_key("func", (), {"a": 1, "b": 2})
        key2 = test_cache.generate_key("func", (), {"b": 2, "a": 1})
        assert key1 == key2

    @pytest.mark.asyncio
    async def test_set_and_get(self, test_cache):
        """Test basic set and get operations."""
        await test_cache.set("key1", "value1", ttl_seconds=300)
        result = await test_cache.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, test_cache):
        """Test getting a key that doesn't exist."""
        result = await test_cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, test_cache):
        """Test that values expire after TTL."""
        await test_cache.set("key1", "value1", ttl_seconds=1)

        # Should exist immediately
        result = await test_cache.get("key1")
        assert result == "value1"

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired now
        result = await test_cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, test_cache):
        """Test delete operation."""
        await test_cache.set("key1", "value1")
        await test_cache.delete("key1")
        result = await test_cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, test_cache):
        """Test deleting a key that doesn't exist (no error)."""
        # Should not raise
        await test_cache.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_clear(self, test_cache):
        """Test clearing all cache entries."""
        await test_cache.set("key1", "value1")
        await test_cache.set("key2", "value2")
        await test_cache.clear()

        result1 = await test_cache.get("key1")
        result2 = await test_cache.get("key2")
        assert result1 is None
        assert result2 is None

    @pytest.mark.asyncio
    async def test_clear_expired(self, test_cache):
        """Test clearing only expired entries."""
        await test_cache.set("short_ttl", "expires", ttl_seconds=1)
        await test_cache.set("long_ttl", "stays", ttl_seconds=300)

        # Wait for short_ttl to expire
        await asyncio.sleep(1.1)

        await test_cache.clear_expired()

        # Short TTL should be cleared
        result1 = await test_cache.get("short_ttl")
        assert result1 is None

        # Long TTL should still exist
        result2 = await test_cache.get("long_ttl")
        assert result2 == "stays"

    def test_get_stats_empty(self, test_cache):
        """Test stats on empty cache."""
        stats = test_cache.get_stats()
        assert stats["total_entries"] == 0
        assert stats["active_entries"] == 0
        assert stats["expired_entries"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_entries(self, test_cache):
        """Test stats with active entries."""
        await test_cache.set("key1", "value1", ttl_seconds=300)
        await test_cache.set("key2", "value2", ttl_seconds=300)

        stats = test_cache.get_stats()
        assert stats["total_entries"] == 2
        assert stats["active_entries"] == 2
        assert stats["expired_entries"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_expired(self, test_cache):
        """Test stats with expired entries."""
        await test_cache.set("expired", "value", ttl_seconds=1)
        await test_cache.set("active", "value", ttl_seconds=300)

        # Wait for first to expire
        await asyncio.sleep(1.1)

        stats = test_cache.get_stats()
        assert stats["total_entries"] == 2
        assert stats["active_entries"] == 1
        assert stats["expired_entries"] == 1

    @pytest.mark.asyncio
    async def test_overwrite_value(self, test_cache):
        """Test overwriting an existing key."""
        await test_cache.set("key", "value1")
        await test_cache.set("key", "value2")
        result = await test_cache.get("key")
        assert result == "value2"

    @pytest.mark.asyncio
    async def test_complex_values(self, test_cache):
        """Test caching complex data types."""
        # Dict
        await test_cache.set("dict_key", {"nested": {"data": [1, 2, 3]}})
        result = await test_cache.get("dict_key")
        assert result == {"nested": {"data": [1, 2, 3]}}

        # List
        await test_cache.set("list_key", [1, 2, {"a": "b"}])
        result = await test_cache.get("list_key")
        assert result == [1, 2, {"a": "b"}]


@pytest.mark.unit
class TestCachedDecorator:
    """Test the @cached decorator."""

    @pytest.mark.asyncio
    async def test_cached_function_basic(self):
        """Test that cached decorator works."""
        call_count = 0

        @cached(ttl_seconds=300)
        async def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        # Clear global cache first
        await cache.clear()

        # First call - should execute function
        result1 = await expensive_function(5)
        assert result1 == 10
        assert call_count == 1

        # Second call - should return cached value
        result2 = await expensive_function(5)
        assert result2 == 10
        assert call_count == 1  # Not called again

    @pytest.mark.asyncio
    async def test_cached_different_args(self):
        """Test that different args create different cache entries."""
        call_count = 0

        @cached(ttl_seconds=300)
        async def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        # Clear global cache first
        await cache.clear()

        # Different args should both be computed
        result1 = await expensive_function(5)
        result2 = await expensive_function(10)

        assert result1 == 10
        assert result2 == 20
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_cached_ttl_expiration(self):
        """Test that cached values expire."""
        call_count = 0

        @cached(ttl_seconds=1)
        async def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        # Clear global cache first
        await cache.clear()

        # First call
        await expensive_function(5)
        assert call_count == 1

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be called again after expiration
        await expensive_function(5)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_cached_with_kwargs(self):
        """Test cached function with keyword arguments."""
        call_count = 0

        @cached(ttl_seconds=300)
        async def expensive_function(x, y=10):
            nonlocal call_count
            call_count += 1
            return x + y

        # Clear global cache first
        await cache.clear()

        result1 = await expensive_function(5, y=20)
        assert result1 == 25
        assert call_count == 1

        # Same args - cached
        result2 = await expensive_function(5, y=20)
        assert result2 == 25
        assert call_count == 1

        # Different kwargs - new computation
        result3 = await expensive_function(5, y=30)
        assert result3 == 35
        assert call_count == 2


@pytest.mark.unit
class TestCacheHelperFunctions:
    """Test cache helper functions."""

    @pytest.mark.asyncio
    async def test_clear_analytics_cache(self):
        """Test clearing analytics cache."""
        # Add some entries to global cache
        await cache.set("test1", "value1")
        await cache.set("test2", "value2")

        # Verify entries exist
        assert await cache.get("test1") == "value1"

        # Clear cache
        await clear_analytics_cache()

        # Verify entries are gone
        assert await cache.get("test1") is None
        assert await cache.get("test2") is None


@pytest.mark.unit
class TestGlobalCacheInstance:
    """Test the global cache instance."""

    def test_global_cache_exists(self):
        """Test that global cache instance exists."""
        assert cache is not None
        assert isinstance(cache, InMemoryCache)

    @pytest.mark.asyncio
    async def test_global_cache_operations(self):
        """Test operations on global cache."""
        await cache.set("global_test", "value")
        result = await cache.get("global_test")
        assert result == "value"

        # Clean up
        await cache.delete("global_test")
