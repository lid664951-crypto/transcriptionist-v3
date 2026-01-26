"""
Performance Monitoring and Optimization Module

Provides tools for profiling and optimizing memory usage.

Validates: Requirements 10.3
"""

from .memory_profiler import (
    MemoryProfiler,
    get_memory_profiler,
    memory_usage,
    track_memory,
    MemorySnapshot
)
from .startup_optimizer import (
    StartupOptimizer,
    lazy_import,
    deferred_init,
    StartupPhase
)

__all__ = [
    'MemoryProfiler',
    'get_memory_profiler',
    'memory_usage',
    'track_memory',
    'MemorySnapshot',
    'StartupOptimizer',
    'lazy_import',
    'deferred_init',
    'StartupPhase',
]
