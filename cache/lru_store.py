"""Thread-safe LRU cache for budget-mode compressed outputs.

Provides a fixed-capacity, TTL-aware cache backed by
collections.OrderedDict and guarded by a threading.Lock.
Entries are lazily expired on read and batch-cleaned on write
when the cache exceeds 80% of its capacity.
"""

from __future__ import annotations

import time
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional


@dataclass
class CacheEntry:
    """Single cached result."""

    compressed_output: str
    """The compressed/deduplicated text that was stored."""

    raw_hash: str
    """Hash of the original (uncompressed) content for integrity checks."""

    timestamp: float
    """Epoch time when the entry was created (time.time())."""


class BudgetLRUCache:
    """Thread-safe LRU cache with lazy TTL eviction.

    Parameters
    ----------
    max_entries : int
        Hard cap on the number of entries stored.
    ttl : int
        Time-to-live in seconds.  Entries older than this are evicted
        lazily on get() or in batch during put().
    """

    def __init__(self, max_entries: int = 256, ttl: int = 3600) -> None:
        self._max_entries = max_entries
        self._ttl = ttl
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[CacheEntry]:
        """Return the cached entry for *key*, or None on miss/expiry.

        On a hit the entry is promoted to most-recently-used.
        Expired entries encountered during lookup are silently removed.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if self._is_expired(entry):
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return entry

    def put(self, key: str, entry: CacheEntry) -> None:
        """Insert or replace an entry, evicting as needed.

        Eviction order:
        1. Batch-remove expired entries when above 80% capacity.
        2. If still full, evict the least-recently-used entry.
        """
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self._store[key] = entry
                return

            if len(self._store) >= self._max_entries * 0.8:
                self._evict_expired()

            while len(self._store) >= self._max_entries:
                self._store.popitem(last=False)

            self._store[key] = entry

    def invalidate(self, key: str) -> bool:
        """Remove a specific key.  Returns True if it existed."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def clear(self) -> None:
        """Remove all entries and reset stats."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        """Return a snapshot of cache statistics."""
        with self._lock:
            return {
                "size": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "max_entries": self._max_entries,
                "ttl": self._ttl,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_expired(self, entry: CacheEntry) -> bool:
        """Return True if *entry* has exceeded the TTL."""
        return (time.time() - entry.timestamp) > self._ttl

    def _evict_expired(self) -> None:
        """Remove all expired entries (caller must hold _lock)."""
        now = time.time()
        expired_keys = [
            k for k, v in self._store.items()
            if (now - v.timestamp) > self._ttl
        ]
        for k in expired_keys:
            del self._store[k]


# ----------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------

_cache: Optional[BudgetLRUCache] = None


def get_cache() -> BudgetLRUCache:
    """Return (and lazily create) the process-wide budget cache."""
    global _cache
    if _cache is None:
        from config import BUDGET_CACHE_SIZE, BUDGET_CACHE_TTL
        _cache = BudgetLRUCache(max_entries=BUDGET_CACHE_SIZE, ttl=BUDGET_CACHE_TTL)
    return _cache
