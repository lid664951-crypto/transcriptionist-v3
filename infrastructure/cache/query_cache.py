"""
Query Cache for Database Optimization

Caches database query results to reduce database load.

Validates: Requirements 10.3
"""

from __future__ import annotations

import logging
import hashlib
import time
from typing import Any, Optional, Callable
from dataclasses import dataclass, field

from .lru_cache import LRUCache
from .utils import CacheStats

logger = logging.getLogger(__name__)


@dataclass
class QueryCacheEntry:
    """A cached query result."""
    result: Any
    query_hash: str
    created_at: float = field(default_factory=time.time)
    access_count: int = 0


class QueryCache:
    """
    Cache for database query results.
    
    Features:
    - Query result caching with configurable TTL
    - Automatic cache invalidation on data changes
    - Query hash-based deduplication
    - Statistics tracking
    
    Usage:
        cache = QueryCache(max_size=500, ttl=60)
        
        # Cache a query result
        result = cache.get_or_compute(
            "SELECT * FROM audio_files WHERE format = ?",
            params=("wav",),
            compute_fn=lambda: db.execute(query, params)
        )
    """
    
    def __init__(
        self,
        max_size: int = 500,
        ttl: float = 60.0,
        enabled: bool = True
    ):
        """
        Initialize the query cache.
        
        Args:
            max_size: Maximum number of queries to cache
            ttl: Time-to-live in seconds
            enabled: Whether caching is enabled
        """
        self._cache = LRUCache[str, QueryCacheEntry](max_size=max_size, ttl=ttl)
        self._enabled = enabled
        self._stats = CacheStats()
        self._invalidation_tags: dict[str, set[str]] = {}  # tag -> query_hashes
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        if not value:
            self.clear()
    
    @property
    def stats(self) -> CacheStats:
        return self._stats
    
    def _hash_query(self, query: str, params: tuple = ()) -> str:
        """Generate a hash for a query and its parameters."""
        key = f"{query}|{params}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]
    
    def get(self, query: str, params: tuple = ()) -> Optional[Any]:
        """
        Get a cached query result.
        
        Args:
            query: SQL query string
            params: Query parameters
            
        Returns:
            Cached result or None
        """
        if not self._enabled:
            return None
        
        query_hash = self._hash_query(query, params)
        entry = self._cache.get(query_hash)
        
        if entry is not None:
            entry.access_count += 1
            self._stats.record_hit()
            logger.debug(f"Query cache hit: {query_hash}")
            return entry.result
        
        self._stats.record_miss()
        return None
    
    def set(
        self,
        query: str,
        params: tuple,
        result: Any,
        tags: Optional[list[str]] = None
    ) -> None:
        """
        Cache a query result.
        
        Args:
            query: SQL query string
            params: Query parameters
            result: Query result to cache
            tags: Invalidation tags (e.g., table names)
        """
        if not self._enabled:
            return
        
        query_hash = self._hash_query(query, params)
        entry = QueryCacheEntry(result=result, query_hash=query_hash)
        self._cache.set(query_hash, entry)
        
        # Register invalidation tags
        if tags:
            for tag in tags:
                if tag not in self._invalidation_tags:
                    self._invalidation_tags[tag] = set()
                self._invalidation_tags[tag].add(query_hash)
        
        logger.debug(f"Query cached: {query_hash}")
    
    def get_or_compute(
        self,
        query: str,
        params: tuple = (),
        compute_fn: Optional[Callable[[], Any]] = None,
        tags: Optional[list[str]] = None
    ) -> Any:
        """
        Get cached result or compute and cache it.
        
        Args:
            query: SQL query string
            params: Query parameters
            compute_fn: Function to compute result if not cached
            tags: Invalidation tags
            
        Returns:
            Query result (cached or computed)
        """
        result = self.get(query, params)
        
        if result is not None:
            return result
        
        if compute_fn is None:
            return None
        
        result = compute_fn()
        self.set(query, params, result, tags)
        return result
    
    def invalidate_by_tag(self, tag: str) -> int:
        """
        Invalidate all queries with a specific tag.
        
        Args:
            tag: Invalidation tag (e.g., table name)
            
        Returns:
            Number of queries invalidated
        """
        if tag not in self._invalidation_tags:
            return 0
        
        query_hashes = self._invalidation_tags.pop(tag)
        count = 0
        
        for query_hash in query_hashes:
            if self._cache.delete(query_hash):
                count += 1
                self._stats.record_eviction()
        
        logger.debug(f"Invalidated {count} queries for tag: {tag}")
        return count
    
    def invalidate_all(self) -> None:
        """Invalidate all cached queries."""
        self.clear()
    
    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()
        self._invalidation_tags.clear()
        self._stats.reset()
        logger.debug("Query cache cleared")


# Global query cache instance
_query_cache: Optional[QueryCache] = None


def get_query_cache() -> QueryCache:
    """Get the global query cache instance."""
    global _query_cache
    if _query_cache is None:
        _query_cache = QueryCache()
    return _query_cache


def invalidate_table_cache(table_name: str) -> None:
    """
    Invalidate cache for a specific table.
    
    Call this after INSERT, UPDATE, or DELETE operations.
    """
    cache = get_query_cache()
    cache.invalidate_by_tag(table_name)
