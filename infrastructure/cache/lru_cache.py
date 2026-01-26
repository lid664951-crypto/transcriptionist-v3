"""
LRU Cache Implementation

A thread-safe LRU (Least Recently Used) cache inspired by Quod Libet's
Collection class caching pattern.

Validates: Requirements 10.3
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import TypeVar, Generic, Optional, Callable, Any

from .utils import CacheStats

K = TypeVar('K')
V = TypeVar('V')


class LRUCache(Generic[K, V]):
    """
    Thread-safe LRU cache with optional TTL support.
    
    Inspired by Quod Libet's Collection class caching pattern.
    
    Features:
    - Configurable max size
    - Optional TTL (time-to-live) for entries
    - Thread-safe operations
    - Statistics tracking
    
    Usage:
        cache = LRUCache[str, dict](max_size=1000, ttl=300)
        cache.set("key", {"data": "value"})
        result = cache.get("key")
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        ttl: Optional[float] = None,
        on_evict: Optional[Callable[[K, V], None]] = None
    ):
        """
        Initialize the LRU cache.
        
        Args:
            max_size: Maximum number of items to store
            ttl: Time-to-live in seconds (None for no expiration)
            on_evict: Callback when an item is evicted
        """
        self._max_size = max_size
        self._ttl = ttl
        self._on_evict = on_evict
        self._cache: OrderedDict[K, tuple[V, float]] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats()
    
    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats
    
    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """
        Get an item from the cache.
        
        Args:
            key: Cache key
            default: Default value if key not found
            
        Returns:
            Cached value or default
        """
        with self._lock:
            if key not in self._cache:
                self._stats.record_miss()
                return default
            
            value, timestamp = self._cache[key]
            
            # Check TTL
            if self._ttl is not None:
                if time.time() - timestamp > self._ttl:
                    self._evict(key)
                    self._stats.record_miss()
                    return default
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._stats.record_hit()
            return value
    
    def set(self, key: K, value: V) -> None:
        """
        Set an item in the cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        with self._lock:
            if key in self._cache:
                # Update existing entry
                self._cache[key] = (value, time.time())
                self._cache.move_to_end(key)
            else:
                # Add new entry
                self._cache[key] = (value, time.time())
                
                # Evict oldest if over capacity
                while len(self._cache) > self._max_size:
                    oldest_key = next(iter(self._cache))
                    self._evict(oldest_key)
    
    def delete(self, key: K) -> bool:
        """
        Delete an item from the cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if item was deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all items from the cache."""
        with self._lock:
            self._cache.clear()
            self._stats.reset()
    
    def _evict(self, key: K) -> None:
        """Evict an item from the cache."""
        if key in self._cache:
            value, _ = self._cache.pop(key)
            self._stats.record_eviction()
            if self._on_evict:
                self._on_evict(key, value)
    
    def contains(self, key: K) -> bool:
        """Check if key exists in cache (without updating LRU order)."""
        with self._lock:
            if key not in self._cache:
                return False
            
            # Check TTL without updating order
            if self._ttl is not None:
                _, timestamp = self._cache[key]
                if time.time() - timestamp > self._ttl:
                    return False
            
            return True
    
    def __contains__(self, key: K) -> bool:
        return self.contains(key)
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
    
    def keys(self) -> list[K]:
        """Get all keys in the cache."""
        with self._lock:
            return list(self._cache.keys())
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        if self._ttl is None:
            return 0
        
        removed = 0
        now = time.time()
        
        with self._lock:
            expired_keys = [
                key for key, (_, timestamp) in self._cache.items()
                if now - timestamp > self._ttl
            ]
            
            for key in expired_keys:
                self._evict(key)
                removed += 1
        
        return removed


class TieredCache(Generic[K, V]):
    """
    Two-tier cache with fast L1 and larger L2.
    
    L1 is a small, fast in-memory cache.
    L2 is a larger cache for less frequently accessed items.
    """
    
    def __init__(
        self,
        l1_size: int = 100,
        l2_size: int = 1000,
        l1_ttl: Optional[float] = 60,
        l2_ttl: Optional[float] = 300
    ):
        self._l1 = LRUCache[K, V](max_size=l1_size, ttl=l1_ttl)
        self._l2 = LRUCache[K, V](max_size=l2_size, ttl=l2_ttl)
    
    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Get from L1, then L2."""
        # Try L1 first
        result = self._l1.get(key)
        if result is not None:
            return result
        
        # Try L2
        result = self._l2.get(key)
        if result is not None:
            # Promote to L1
            self._l1.set(key, result)
            return result
        
        return default
    
    def set(self, key: K, value: V, hot: bool = False) -> None:
        """
        Set in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            hot: If True, store in L1 (hot cache)
        """
        if hot:
            self._l1.set(key, value)
        else:
            self._l2.set(key, value)
    
    def delete(self, key: K) -> bool:
        """Delete from both tiers."""
        l1_deleted = self._l1.delete(key)
        l2_deleted = self._l2.delete(key)
        return l1_deleted or l2_deleted
    
    def clear(self) -> None:
        """Clear both tiers."""
        self._l1.clear()
        self._l2.clear()
