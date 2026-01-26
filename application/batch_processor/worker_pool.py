"""
Worker Pool

Parallel processing with worker pool for batch operations.
Inspired by Quod Libet's copool patterns.
"""

import asyncio
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar
from queue import Queue, Empty
import uuid

logger = logging.getLogger(__name__)

T = TypeVar('T')
R = TypeVar('R')


class TaskStatus(Enum):
    """Status of a batch task."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BatchTask(Generic[T, R]):
    """A task in the batch processing queue."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    data: Optional[T] = None
    result: Optional[R] = None
    error: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    
    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    @property
    def duration(self) -> Optional[float]:
        """Get task duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status.value,
            'progress': self.progress,
            'error': self.error,
            'duration': self.duration,
        }


@dataclass
class PoolStats:
    """Statistics for the worker pool."""
    
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    active_workers: int = 0
    queued_tasks: int = 0
    
    @property
    def success_rate(self) -> float:
        """Get success rate as percentage."""
        if self.total_tasks == 0:
            return 0.0
        return (self.completed_tasks / self.total_tasks) * 100


class WorkerPool:
    """
    Worker pool for parallel batch processing.
    
    Features:
    - Configurable number of workers
    - Task queue with priority
    - Progress tracking
    - Cancellation support
    - Statistics
    """
    
    def __init__(
        self,
        max_workers: Optional[int] = None,
        name: str = "BatchWorkerPool",
    ):
        """
        Initialize the worker pool.
        
        Args:
            max_workers: Maximum number of worker threads (default: CPU count)
            name: Name for the pool (for logging)
        """
        self.name = name
        self.max_workers = max_workers or min(os.cpu_count() or 4, 8)
        
        self._executor: Optional[ThreadPoolExecutor] = None
        self._tasks: Dict[str, BatchTask] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._cancelled = False
        
        # Callbacks
        self._on_task_complete: Optional[Callable[[BatchTask], None]] = None
        self._on_progress: Optional[Callable[[str, float], None]] = None
    
    def start(self) -> None:
        """Start the worker pool."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix=self.name,
            )
            self._cancelled = False
            logger.info(f"Started {self.name} with {self.max_workers} workers")
    
    def stop(self, wait: bool = True) -> None:
        """
        Stop the worker pool.
        
        Args:
            wait: Wait for pending tasks to complete
        """
        if self._executor:
            self._cancelled = True
            self._executor.shutdown(wait=wait)
            self._executor = None
            logger.info(f"Stopped {self.name}")
    
    def submit(
        self,
        func: Callable[[T], R],
        data: T,
        name: str = "",
    ) -> BatchTask[T, R]:
        """
        Submit a task to the pool.
        
        Args:
            func: Function to execute
            data: Data to pass to function
            name: Task name
        
        Returns:
            BatchTask
        """
        self.start()  # Ensure pool is running
        
        task: BatchTask[T, R] = BatchTask(
            name=name or f"Task-{len(self._tasks)}",
            data=data,
            status=TaskStatus.QUEUED,
        )
        
        with self._lock:
            self._tasks[task.id] = task
        
        def execute():
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            
            try:
                if self._cancelled:
                    task.status = TaskStatus.CANCELLED
                    return
                
                result = func(data)
                task.result = result
                task.status = TaskStatus.COMPLETED
                task.progress = 1.0
                
            except Exception as e:
                task.error = str(e)
                task.status = TaskStatus.FAILED
                logger.error(f"Task {task.id} failed: {e}")
            
            finally:
                task.completed_at = datetime.now()
                if self._on_task_complete:
                    self._on_task_complete(task)
        
        future = self._executor.submit(execute)
        
        with self._lock:
            self._futures[task.id] = future
        
        return task
    
    async def submit_async(
        self,
        func: Callable[[T], R],
        data: T,
        name: str = "",
    ) -> BatchTask[T, R]:
        """
        Submit a task and wait for completion asynchronously.
        
        Args:
            func: Function to execute
            data: Data to pass to function
            name: Task name
        
        Returns:
            Completed BatchTask
        """
        task = self.submit(func, data, name)
        
        # Wait for completion
        while task.status in (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING):
            await asyncio.sleep(0.1)
        
        return task
    
    def submit_batch(
        self,
        func: Callable[[T], R],
        items: List[T],
        name_func: Optional[Callable[[T], str]] = None,
    ) -> List[BatchTask[T, R]]:
        """
        Submit multiple tasks.
        
        Args:
            func: Function to execute for each item
            items: List of items to process
            name_func: Function to generate task names
        
        Returns:
            List of BatchTasks
        """
        tasks = []
        for i, item in enumerate(items):
            name = name_func(item) if name_func else f"Batch-{i}"
            task = self.submit(func, item, name)
            tasks.append(task)
        return tasks
    
    async def submit_batch_async(
        self,
        func: Callable[[T], R],
        items: List[T],
        name_func: Optional[Callable[[T], str]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> List[BatchTask[T, R]]:
        """
        Submit multiple tasks and wait for all to complete.
        
        Args:
            func: Function to execute for each item
            items: List of items to process
            name_func: Function to generate task names
            progress_callback: Progress callback
        
        Returns:
            List of completed BatchTasks
        """
        tasks = self.submit_batch(func, items, name_func)
        total = len(tasks)
        
        # Wait for all tasks
        while True:
            completed = sum(
                1 for t in tasks
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            )
            
            if progress_callback:
                progress = completed / total if total > 0 else 1.0
                running = [t for t in tasks if t.status == TaskStatus.RUNNING]
                message = running[0].name if running else "Processing..."
                progress_callback(progress, message)
            
            if completed >= total:
                break
            
            await asyncio.sleep(0.1)
        
        return tasks
    
    def cancel_all(self) -> None:
        """Cancel all pending and running tasks."""
        self._cancelled = True
        
        with self._lock:
            for task_id, future in self._futures.items():
                if not future.done():
                    future.cancel()
                task = self._tasks.get(task_id)
                if task and task.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
                    task.status = TaskStatus.CANCELLED
    
    def get_task(self, task_id: str) -> Optional[BatchTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def get_all_tasks(self) -> List[BatchTask]:
        """Get all tasks."""
        return list(self._tasks.values())
    
    def get_stats(self) -> PoolStats:
        """Get pool statistics."""
        with self._lock:
            tasks = list(self._tasks.values())
        
        return PoolStats(
            total_tasks=len(tasks),
            completed_tasks=sum(1 for t in tasks if t.status == TaskStatus.COMPLETED),
            failed_tasks=sum(1 for t in tasks if t.status == TaskStatus.FAILED),
            cancelled_tasks=sum(1 for t in tasks if t.status == TaskStatus.CANCELLED),
            active_workers=sum(1 for t in tasks if t.status == TaskStatus.RUNNING),
            queued_tasks=sum(1 for t in tasks if t.status == TaskStatus.QUEUED),
        )
    
    def clear_completed(self) -> None:
        """Clear completed tasks from history."""
        with self._lock:
            completed_ids = [
                task_id for task_id, task in self._tasks.items()
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]
            for task_id in completed_ids:
                del self._tasks[task_id]
                if task_id in self._futures:
                    del self._futures[task_id]
    
    def set_on_task_complete(self, callback: Callable[[BatchTask], None]) -> None:
        """Set callback for task completion."""
        self._on_task_complete = callback
    
    def set_on_progress(self, callback: Callable[[str, float], None]) -> None:
        """Set callback for progress updates."""
        self._on_progress = callback
    
    def update_task_progress(self, task_id: str, progress: float) -> None:
        """Update progress for a task."""
        task = self._tasks.get(task_id)
        if task:
            task.progress = progress
            if self._on_progress:
                self._on_progress(task_id, progress)
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False
