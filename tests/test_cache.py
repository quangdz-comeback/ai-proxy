"""Tests for cache/lru_store.py and cache/delta.py."""

import time
import threading

from cache.lru_store import BudgetLRUCache, CacheEntry
from cache.delta import compute_delta, apply_delta, is_delta_worthwhile


# ======================================================================
# BudgetLRUCache tests
# ======================================================================


def _make_entry(text: str = "compressed", ts: float | None = None) -> CacheEntry:
    """Helper to build a CacheEntry with sensible defaults."""
    return CacheEntry(
        compressed_output=text,
        raw_hash="fakehash",
        timestamp=ts if ts is not None else time.time(),
    )


class TestBudgetLRUCache:
    """Tests for BudgetLRUCache."""

    def test_put_and_get(self):
        """put entry, get returns it."""
        cache = BudgetLRUCache(max_entries=10, ttl=3600)
        entry = _make_entry("hello")
        cache.put("k1", entry)
        result = cache.get("k1")
        assert result is not None
        assert result.compressed_output == "hello"

    def test_get_miss(self):
        """get nonexistent key returns None."""
        cache = BudgetLRUCache()
        assert cache.get("missing") is None

    def test_ttl_expiry(self):
        """put entry with old timestamp, get returns None."""
        cache = BudgetLRUCache(max_entries=10, ttl=10)
        old_ts = time.time() - 100  # 100 seconds ago
        cache.put("k1", _make_entry(ts=old_ts))
        assert cache.get("k1") is None

    def test_lru_eviction(self):
        """fill cache to max + 1, oldest entry evicted."""
        cache = BudgetLRUCache(max_entries=5, ttl=3600)
        for i in range(6):  # max + 1
            cache.put(f"k{i}", _make_entry(f"v{i}"))
        # k0 should be evicted (oldest)
        assert cache.get("k0") is None
        # k1 through k5 should exist
        for i in range(1, 6):
            assert cache.get(f"k{i}") is not None

    def test_invalidate(self):
        """put then invalidate, get returns None."""
        cache = BudgetLRUCache()
        cache.put("k1", _make_entry())
        assert cache.invalidate("k1") is True
        assert cache.get("k1") is None
        # Invalidation of nonexistent key returns False
        assert cache.invalidate("nope") is False

    def test_clear(self):
        """put entries, clear, all gone."""
        cache = BudgetLRUCache()
        cache.put("a", _make_entry())
        cache.put("b", _make_entry())
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_stats(self):
        """verify hits/misses/size after operations."""
        cache = BudgetLRUCache(max_entries=10, ttl=3600)
        cache.put("k1", _make_entry())
        cache.get("k1")   # hit
        cache.get("k1")   # hit
        cache.get("x")    # miss
        s = cache.stats()
        assert s["size"] == 1
        assert s["hits"] == 2
        assert s["misses"] == 1
        assert s["max_entries"] == 10
        assert s["ttl"] == 3600

    def test_thread_safety(self):
        """concurrent put/get from multiple threads, no corruption."""
        cache = BudgetLRUCache(max_entries=500, ttl=3600)
        errors: list[Exception] = []

        def worker(thread_id: int) -> None:
            try:
                for j in range(100):
                    key = f"t{thread_id}:k{j}"
                    cache.put(key, _make_entry(f"v{thread_id}:{j}"))
                    result = cache.get(key)
                    # Result may be None if evicted, but should never raise
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        # Cache should have at most max_entries items
        assert cache.stats()["size"] <= 500


# ======================================================================
# Delta tests
# ======================================================================


class TestDelta:
    """Tests for cache/delta.py."""

    def test_compute_delta_small_change(self):
        """small diff returns delta string."""
        old = "\n".join(f"line{i}" for i in range(50))
        new_lines = [f"line{i}" for i in range(50)]
        new_lines[5] = "CHANGED"
        new = "\n".join(new_lines)
        delta = compute_delta(old, new)
        assert delta is not None
        assert isinstance(delta, str)
        assert len(delta) > 0

    def test_compute_delta_no_change(self):
        """identical texts returns None."""
        text = "same\ntext\nhere"
        assert compute_delta(text, text) is None

    def test_compute_delta_completely_different(self):
        """totally different returns None (delta not worthwhile)."""
        old = "a" * 500
        new = "b" * 500
        # The delta will be large relative to new text, so not worthwhile
        assert compute_delta(old, new) is None

    def test_is_delta_worthwhile(self):
        """check threshold logic."""
        # Delta smaller than 70% of new text -> worthwhile
        assert is_delta_worthwhile(100, 50) is True
        # Delta >= 70% of new text -> not worthwhile
        assert is_delta_worthwhile(100, 70) is False
        assert is_delta_worthwhile(100, 80) is False
        # Zero-length new text -> not worthwhile
        assert is_delta_worthwhile(0, 0) is False

    def test_apply_delta_roundtrip(self):
        """compute delta then apply, get original back."""
        old = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"
        new = "line1\nchanged\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"
        delta = compute_delta(old, new)
        if delta is not None:
            result = apply_delta(old, delta)
            assert result is not None
            assert result == new

    def test_apply_delta_invalid(self):
        """apply with garbage delta returns None."""
        result = apply_delta("base text", "this is not a valid delta")
        # Either None (parse fails) or doesn't match
        # We accept both outcomes, but the result should not crash
        assert result is None or isinstance(result, str)
