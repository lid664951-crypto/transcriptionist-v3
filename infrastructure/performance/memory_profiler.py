"""
Memory Profiler

Tools for profiling and optimizing memory usage.

Validates: Requirements 10.3
"""

from __future__ import annotations

import gc
import sys
import logging
import threading
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from functools import wraps
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MemorySnapshot:
    """A snapshot of memory usage."""
    timestamp: datetime
    rss_bytes: int  # Resident Set Size
    vms_bytes: int  # Virtual Memory Size
    peak_bytes: int
    gc_objects: int
    gc_collections: tuple[int, int, int]  # gen0, gen1, gen2
    
    @property
    def rss_mb(self) -> float:
        return self.rss_bytes / (1024 * 1024)
    
    @property
    def vms_mb(self) -> float:
        return self.vms_bytes / (1024 * 1024)
    
    @property
    def peak_mb(self) -> float:
        return self.peak_bytes / (1024 * 1024)
    
    def __repr__(self) -> str:
        return (
            f"MemorySnapshot(rss={self.rss_mb:.1f}MB, "
            f"vms={self.vms_mb:.1f}MB, peak={self.peak_mb:.1f}MB, "
            f"objects={self.gc_objects})"
        )


@dataclass
class AllocationInfo:
    """Information about a memory allocation."""
    size: int
    traceback: list[str]
    count: int = 1


class MemoryProfiler:
    """
    Memory profiler for tracking and optimizing memory usage.
    
    Features:
    - Memory usage snapshots
    - Allocation tracking with tracemalloc
    - Memory leak detection
    - GC statistics
    
    Usage:
        profiler = MemoryProfiler()
        profiler.start()
        
        # ... do work ...
        
        snapshot = profiler.take_snapshot()
        print(f"Memory usage: {snapshot.rss_mb:.1f} MB")
        
        # Find top allocations
        top = profiler.get_top_allocations(10)
    """
    
    def __init__(self, track_allocations: bool = False):
        """
        Initialize the memory profiler.
        
        Args:
            track_allocations: Enable tracemalloc for detailed tracking
        """
        self._track_allocations = track_allocations
        self._snapshots: list[MemorySnapshot] = []
        self._started = False
        self._baseline: Optional[MemorySnapshot] = None
        self._lock = threading.Lock()
    
    def start(self) -> None:
        """Start memory profiling."""
        if self._started:
            return
        
        if self._track_allocations:
            tracemalloc.start(25)  # 25 frames of traceback
        
        self._baseline = self.take_snapshot()
        self._started = True
        logger.info("Memory profiler started")
    
    def stop(self) -> None:
        """Stop memory profiling."""
        if not self._started:
            return
        
        if self._track_allocations:
            tracemalloc.stop()
        
        self._started = False
        logger.info("Memory profiler stopped")
    
    def take_snapshot(self) -> MemorySnapshot:
        """Take a memory usage snapshot."""
        try:
            import psutil
            process = psutil.Process()
            mem_info = process.memory_info()
            rss = mem_info.rss
            vms = mem_info.vms
        except ImportError:
            # Fallback without psutil
            rss = 0
            vms = 0
        
        # Get peak memory if tracemalloc is running
        if tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
        else:
            current, peak = 0, 0
        
        snapshot = MemorySnapshot(
            timestamp=datetime.now(),
            rss_bytes=rss,
            vms_bytes=vms,
            peak_bytes=peak,
            gc_objects=len(gc.get_objects()),
            gc_collections=tuple(gc.get_count())
        )
        
        with self._lock:
            self._snapshots.append(snapshot)
        
        return snapshot
    
    def get_memory_diff(self) -> Optional[tuple[float, float]]:
        """
        Get memory difference since baseline.
        
        Returns:
            Tuple of (rss_diff_mb, vms_diff_mb) or None
        """
        if self._baseline is None:
            return None
        
        current = self.take_snapshot()
        rss_diff = (current.rss_bytes - self._baseline.rss_bytes) / (1024 * 1024)
        vms_diff = (current.vms_bytes - self._baseline.vms_bytes) / (1024 * 1024)
        return (rss_diff, vms_diff)
    
    def get_top_allocations(self, limit: int = 10) -> list[AllocationInfo]:
        """
        Get top memory allocations.
        
        Requires tracemalloc to be enabled.
        
        Args:
            limit: Number of top allocations to return
            
        Returns:
            List of AllocationInfo
        """
        if not tracemalloc.is_tracing():
            return []
        
        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.statistics('lineno')
        
        result = []
        for stat in stats[:limit]:
            result.append(AllocationInfo(
                size=stat.size,
                traceback=[str(stat.traceback)],
                count=stat.count
            ))
        
        return result
    
    def find_memory_leaks(self, threshold_mb: float = 10.0) -> list[str]:
        """
        Find potential memory leaks.
        
        Args:
            threshold_mb: Minimum size to report
            
        Returns:
            List of potential leak descriptions
        """
        if not tracemalloc.is_tracing():
            return ["tracemalloc not enabled"]
        
        # Take two snapshots
        snapshot1 = tracemalloc.take_snapshot()
        gc.collect()
        time.sleep(0.1)
        snapshot2 = tracemalloc.take_snapshot()
        
        # Compare
        diff = snapshot2.compare_to(snapshot1, 'lineno')
        
        leaks = []
        threshold_bytes = threshold_mb * 1024 * 1024
        
        for stat in diff:
            if stat.size_diff > threshold_bytes:
                leaks.append(
                    f"{stat.traceback}: +{stat.size_diff / 1024 / 1024:.1f} MB"
                )
        
        return leaks
    
    def force_gc(self) -> tuple[int, int, int]:
        """
        Force garbage collection.
        
        Returns:
            Tuple of objects collected per generation
        """
        gen0 = gc.collect(0)
        gen1 = gc.collect(1)
        gen2 = gc.collect(2)
        
        logger.debug(f"GC collected: gen0={gen0}, gen1={gen1}, gen2={gen2}")
        return (gen0, gen1, gen2)
    
    def get_object_counts(self) -> dict[str, int]:
        """Get counts of objects by type."""
        counts: dict[str, int] = {}
        
        for obj in gc.get_objects():
            type_name = type(obj).__name__
            counts[type_name] = counts.get(type_name, 0) + 1
        
        return dict(sorted(counts.items(), key=lambda x: -x[1])[:50])
    
    def get_large_objects(self, min_size_kb: float = 100) -> list[tuple[str, int]]:
        """
        Find large objects in memory.
        
        Args:
            min_size_kb: Minimum size in KB
            
        Returns:
            List of (type_name, size_bytes)
        """
        min_size = int(min_size_kb * 1024)
        large = []
        
        for obj in gc.get_objects():
            try:
                size = sys.getsizeof(obj)
                if size >= min_size:
                    large.append((type(obj).__name__, size))
            except (TypeError, RecursionError):
                pass
        
        return sorted(large, key=lambda x: -x[1])[:50]


# Global profiler instance
_profiler: Optional[MemoryProfiler] = None


def get_memory_profiler() -> MemoryProfiler:
    """Get the global memory profiler."""
    global _profiler
    if _profiler is None:
        _profiler = MemoryProfiler()
    return _profiler


def memory_usage() -> float:
    """Get current memory usage in MB."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0


@contextmanager
def track_memory(label: str = ""):
    """
    Context manager to track memory usage of a code block.
    
    Usage:
        with track_memory("loading files"):
            load_files()
    """
    gc.collect()
    start_mem = memory_usage()
    start_time = time.time()
    
    try:
        yield
    finally:
        gc.collect()
        end_mem = memory_usage()
        elapsed = time.time() - start_time
        diff = end_mem - start_mem
        
        logger.info(
            f"Memory [{label}]: {diff:+.1f} MB "
            f"(now: {end_mem:.1f} MB, time: {elapsed:.2f}s)"
        )


def profile_memory(func: Callable) -> Callable:
    """
    Decorator to profile memory usage of a function.
    
    Usage:
        @profile_memory
        def my_function():
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        with track_memory(func.__name__):
            return func(*args, **kwargs)
    return wrapper
