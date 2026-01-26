"""
Cache Utilities

Common utilities for caching, inspired by Quod Libet patterns.

Validates: Requirements 10.3
"""

from __future__ import annotations

import hashlib
import time
from functools import wraps
from typing import Any, Callable, TypeVar, Generic

T = TypeVar('T')


class cached_property(Generic[T]):
    """
    A read-only @property that is only evaluated once.
    
    Inspired by Quod Libet's cached_property implementation.
    The result is cached in the instance's __dict__.
    
    Usage:
        class MyClass:
            @cached_property
            def expensive_computation(self) -> int:
                return sum(range(1000000))
    """
    
    def __init__(self, fget: Callable[[Any], T], doc: str | None = None):
        self.fget = fget
        self.__doc__ = doc or fget.__doc__
        self.__name__ = name = fget.__name__
        # Dunder methods get name mangled, so caching won't work
        assert not (
            name.startswith("__") and not name.endswith("__")
        ), "can't cache a dunder method"
    
    def __get__(self, obj: Any, cls: type) -> T:
        if obj is None:
            return self  # type: ignore
        obj.__dict__[self.__name__] = result = self.fget(obj)
        return result


def timed_cache(seconds: float = 300):
    """
    Decorator that caches function results for a specified time.
    
    Args:
        seconds: Cache TTL in seconds (default 5 minutes)
    
    Usage:
        @timed_cache(seconds=60)
        def get_data():
            return expensive_operation()
    """
    def decorator(func: Callable) -> Callable:
        cache: dict[tuple, tuple[Any, float]] = {}
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            
            if key in cache:
                result, timestamp = cache[key]
                if now - timestamp < seconds:
                    return result
            
            result = func(*args, **kwargs)
            cache[key] = (result, now)
            return result
        
        wrapper.cache_clear = lambda: cache.clear()  # type: ignore
        return wrapper
    
    return decorator


def hash_key(*args, **kwargs) -> str:
    """
    Generate a hash key from arguments.
    
    Useful for creating cache keys from complex arguments.
    """
    key_parts = [str(arg) for arg in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_str = "|".join(key_parts)
    return hashlib.md5(key_str.encode()).hexdigest()


class CacheStats:
    """Track cache hit/miss statistics."""
    
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    def record_hit(self):
        self.hits += 1
    
    def record_miss(self):
        self.misses += 1
    
    def record_eviction(self):
        self.evictions += 1
    
    def reset(self):
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def __repr__(self) -> str:
        return (
            f"CacheStats(hits={self.hits}, misses={self.misses}, "
            f"evictions={self.evictions}, hit_rate={self.hit_rate:.2%})"
        )
