"""
Startup Optimizer

Tools for optimizing application startup time, especially for large libraries.

Validates: Requirements 10.3
"""

from __future__ import annotations

import logging
import time
import threading
import importlib
from dataclasses import dataclass, field
from typing import Optional, Callable, Any, TypeVar
from enum import Enum, auto
from functools import wraps
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

T = TypeVar('T')


class StartupPhase(Enum):
    """Startup phases for tracking initialization."""
    BOOTSTRAP = auto()      # Basic runtime setup
    CONFIG = auto()         # Configuration loading
    DATABASE = auto()       # Database initialization
    CACHE = auto()          # Cache warming
    UI_INIT = auto()        # UI framework init
    LIBRARY_SCAN = auto()   # Library scanning
    PLUGINS = auto()        # Plugin loading
    READY = auto()          # Application ready


@dataclass
class PhaseMetrics:
    """Metrics for a startup phase."""
    phase: StartupPhase
    start_time: float = 0.0
    end_time: float = 0.0
    
    @property
    def duration(self) -> float:
        if self.end_time == 0:
            return 0.0
        return self.end_time - self.start_time
    
    @property
    def duration_ms(self) -> float:
        return self.duration * 1000


class StartupOptimizer:
    """
    Optimizer for application startup time.
    
    Features:
    - Lazy module loading
    - Deferred initialization
    - Parallel initialization
    - Startup phase tracking
    - Library index caching
    
    Usage:
        optimizer = StartupOptimizer()
        
        with optimizer.phase(StartupPhase.DATABASE):
            init_database()
        
        # Defer non-critical initialization
        optimizer.defer(load_plugins)
        
        # Run deferred tasks after UI is ready
        optimizer.run_deferred()
    """
    
    def __init__(self, max_workers: int = 4):
        """
        Initialize the startup optimizer.
        
        Args:
            max_workers: Max threads for parallel initialization
        """
        self._phases: dict[StartupPhase, PhaseMetrics] = {}
        self._deferred: list[tuple[Callable, tuple, dict]] = []
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._start_time = time.time()
        self._ready_time: Optional[float] = None
        self._lock = threading.Lock()
    
    @property
    def total_startup_time(self) -> float:
        """Get total startup time in seconds."""
        if self._ready_time is None:
            return time.time() - self._start_time
        return self._ready_time - self._start_time
    
    def phase(self, phase: StartupPhase):
        """
        Context manager for tracking a startup phase.
        
        Usage:
            with optimizer.phase(StartupPhase.DATABASE):
                init_database()
        """
        return _PhaseContext(self, phase)
    
    def _start_phase(self, phase: StartupPhase) -> None:
        """Start tracking a phase."""
        with self._lock:
            self._phases[phase] = PhaseMetrics(
                phase=phase,
                start_time=time.time()
            )
        logger.debug(f"Starting phase: {phase.name}")
    
    def _end_phase(self, phase: StartupPhase) -> None:
        """End tracking a phase."""
        with self._lock:
            if phase in self._phases:
                self._phases[phase].end_time = time.time()
                duration = self._phases[phase].duration_ms
                logger.info(f"Phase {phase.name} completed in {duration:.1f}ms")
    
    def defer(
        self,
        func: Callable,
        *args,
        priority: int = 0,
        **kwargs
    ) -> None:
        """
        Defer a function call until after startup.
        
        Args:
            func: Function to call
            *args: Positional arguments
            priority: Lower = higher priority (default 0)
            **kwargs: Keyword arguments
        """
        with self._lock:
            self._deferred.append((func, args, kwargs))
        logger.debug(f"Deferred: {func.__name__}")
    
    def run_deferred(self, parallel: bool = True) -> None:
        """
        Run all deferred initialization tasks.
        
        Args:
            parallel: Run tasks in parallel if True
        """
        with self._lock:
            tasks = self._deferred.copy()
            self._deferred.clear()
        
        if not tasks:
            return
        
        logger.info(f"Running {len(tasks)} deferred tasks")
        start = time.time()
        
        if parallel:
            futures = []
            for func, args, kwargs in tasks:
                future = self._executor.submit(func, *args, **kwargs)
                futures.append((func.__name__, future))
            
            for name, future in futures:
                try:
                    future.result(timeout=30)
                except Exception as e:
                    logger.error(f"Deferred task {name} failed: {e}")
        else:
            for func, args, kwargs in tasks:
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Deferred task {func.__name__} failed: {e}")
        
        elapsed = (time.time() - start) * 1000
        logger.info(f"Deferred tasks completed in {elapsed:.1f}ms")
    
    def mark_ready(self) -> None:
        """Mark the application as ready."""
        self._ready_time = time.time()
        total = self.total_startup_time * 1000
        logger.info(f"Application ready in {total:.1f}ms")
    
    def get_phase_report(self) -> str:
        """Get a report of startup phase timings."""
        lines = ["Startup Phase Report:"]
        lines.append("-" * 40)
        
        total = 0.0
        for phase in StartupPhase:
            if phase in self._phases:
                metrics = self._phases[phase]
                duration = metrics.duration_ms
                total += duration
                lines.append(f"  {phase.name:20} {duration:8.1f}ms")
        
        lines.append("-" * 40)
        lines.append(f"  {'TOTAL':20} {total:8.1f}ms")
        
        return "\n".join(lines)
    
    def shutdown(self) -> None:
        """Shutdown the optimizer."""
        self._executor.shutdown(wait=False)


class _PhaseContext:
    """Context manager for startup phases."""
    
    def __init__(self, optimizer: StartupOptimizer, phase: StartupPhase):
        self._optimizer = optimizer
        self._phase = phase
    
    def __enter__(self):
        self._optimizer._start_phase(self._phase)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._optimizer._end_phase(self._phase)
        return False


class LazyModule:
    """
    Lazy module loader that defers import until first access.
    
    Usage:
        numpy = LazyModule('numpy')
        # numpy is not imported yet
        
        result = numpy.array([1, 2, 3])  # Now numpy is imported
    """
    
    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module: Optional[Any] = None
    
    def _load(self) -> Any:
        if self._module is None:
            logger.debug(f"Lazy loading module: {self._module_name}")
            self._module = importlib.import_module(self._module_name)
        return self._module
    
    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)
    
    def __repr__(self) -> str:
        loaded = "loaded" if self._module else "not loaded"
        return f"<LazyModule '{self._module_name}' ({loaded})>"


def lazy_import(module_name: str) -> LazyModule:
    """
    Create a lazy module import.
    
    Usage:
        np = lazy_import('numpy')
    """
    return LazyModule(module_name)


def deferred_init(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator to defer initialization until first use.
    
    Usage:
        @deferred_init
        def get_heavy_resource():
            return load_heavy_resource()
    """
    result: list = []
    lock = threading.Lock()
    
    @wraps(func)
    def wrapper(*args, **kwargs) -> T:
        if not result:
            with lock:
                if not result:
                    logger.debug(f"Deferred init: {func.__name__}")
                    result.append(func(*args, **kwargs))
        return result[0]
    
    return wrapper


class LibraryIndexCache:
    """
    Cache for library index to speed up startup.
    
    Stores a serialized index of the library that can be loaded
    quickly on startup instead of scanning all files.
    """
    
    def __init__(self, cache_path):
        self._cache_path = cache_path
        self._index: Optional[dict] = None
    
    def load(self) -> Optional[dict]:
        """Load cached library index."""
        import json
        
        if not self._cache_path.exists():
            return None
        
        try:
            with open(self._cache_path, 'r', encoding='utf-8') as f:
                self._index = json.load(f)
            
            logger.info(f"Loaded library index: {len(self._index.get('files', []))} files")
            return self._index
            
        except Exception as e:
            logger.warning(f"Failed to load library index: {e}")
            return None
    
    def save(self, index: dict) -> None:
        """Save library index to cache."""
        import json
        
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self._cache_path, 'w', encoding='utf-8') as f:
                json.dump(index, f)
            
            self._index = index
            logger.info(f"Saved library index: {len(index.get('files', []))} files")
            
        except Exception as e:
            logger.warning(f"Failed to save library index: {e}")
    
    def is_valid(self, library_paths: list[str]) -> bool:
        """Check if cached index is still valid."""
        if self._index is None:
            return False
        
        cached_paths = set(self._index.get('library_paths', []))
        current_paths = set(library_paths)
        
        if cached_paths != current_paths:
            return False
        
        # Check if any library path was modified
        cached_mtime = self._index.get('mtime', 0)
        import os
        
        for path in library_paths:
            try:
                if os.path.getmtime(path) > cached_mtime:
                    return False
            except OSError:
                return False
        
        return True
    
    def invalidate(self) -> None:
        """Invalidate the cached index."""
        self._index = None
        if self._cache_path.exists():
            try:
                self._cache_path.unlink()
            except OSError:
                pass


# Global startup optimizer
_optimizer: Optional[StartupOptimizer] = None


def get_startup_optimizer() -> StartupOptimizer:
    """Get the global startup optimizer."""
    global _optimizer
    if _optimizer is None:
        _optimizer = StartupOptimizer()
    return _optimizer
