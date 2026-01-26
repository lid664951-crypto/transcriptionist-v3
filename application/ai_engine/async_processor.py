"""
Async Processor

异步任务处理器，支持批量处理、进度回调和取消操作。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

T = TypeVar('T')
R = TypeVar('R')


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskProgress:
    """任务进度"""
    current: int = 0
    total: int = 0
    message: str = ""
    percentage: float = 0.0
    
    def update(self, current: int, total: int, message: str = "") -> None:
        self.current = current
        self.total = total
        self.message = message
        self.percentage = (current / total * 100) if total > 0 else 0


@dataclass
class TaskResult(Generic[T]):
    """任务结果"""
    task_id: str
    status: TaskStatus
    data: Optional[T] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: TaskProgress = field(default_factory=TaskProgress)
    
    @property
    def duration_ms(self) -> int:
        """任务耗时（毫秒）"""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return 0


# 回调类型
ProgressCallback = Callable[[int, int, str], None]
CompletionCallback = Callable[[TaskResult], None]


class AsyncTask(Generic[T, R]):
    """
    异步任务
    
    封装一个可取消的异步操作。
    """
    
    def __init__(
        self,
        task_id: str,
        func: Callable[..., R],
        *args,
        **kwargs,
    ):
        self.task_id = task_id
        self._func = func
        self._args = args
        self._kwargs = kwargs
        self._status = TaskStatus.PENDING
        self._progress = TaskProgress()
        self._result: Optional[R] = None
        self._error: Optional[str] = None
        self._cancelled = False
        self._task: Optional[asyncio.Task] = None
        
        # 回调
        self._progress_callback: Optional[ProgressCallback] = None
        self._completion_callback: Optional[CompletionCallback] = None
    
    @property
    def status(self) -> TaskStatus:
        return self._status
    
    @property
    def progress(self) -> TaskProgress:
        return self._progress
    
    @property
    def is_running(self) -> bool:
        return self._status == TaskStatus.RUNNING
    
    @property
    def is_completed(self) -> bool:
        return self._status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
    
    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """设置进度回调"""
        self._progress_callback = callback
    
    def set_completion_callback(self, callback: CompletionCallback) -> None:
        """设置完成回调"""
        self._completion_callback = callback
    
    def update_progress(self, current: int, total: int, message: str = "") -> None:
        """更新进度"""
        self._progress.update(current, total, message)
        if self._progress_callback:
            self._progress_callback(current, total, message)
    
    def cancel(self) -> bool:
        """取消任务"""
        if self._status == TaskStatus.RUNNING and self._task:
            self._cancelled = True
            self._task.cancel()
            return True
        return False
    
    async def run(self) -> TaskResult[R]:
        """执行任务"""
        result = TaskResult(
            task_id=self.task_id,
            status=TaskStatus.RUNNING,
            started_at=datetime.now(),
            progress=self._progress,
        )
        
        self._status = TaskStatus.RUNNING
        
        try:
            # 注入进度回调
            if 'progress_callback' in self._kwargs or asyncio.iscoroutinefunction(self._func):
                self._kwargs['progress_callback'] = self.update_progress
            
            # 执行函数
            if asyncio.iscoroutinefunction(self._func):
                self._result = await self._func(*self._args, **self._kwargs)
            else:
                loop = asyncio.get_event_loop()
                self._result = await loop.run_in_executor(
                    None, lambda: self._func(*self._args, **self._kwargs)
                )
            
            self._status = TaskStatus.COMPLETED
            result.status = TaskStatus.COMPLETED
            result.data = self._result
            
        except asyncio.CancelledError:
            self._status = TaskStatus.CANCELLED
            result.status = TaskStatus.CANCELLED
            result.error = "任务已取消"
            
        except Exception as e:
            logger.exception(f"Task {self.task_id} failed")
            self._status = TaskStatus.FAILED
            self._error = str(e)
            result.status = TaskStatus.FAILED
            result.error = str(e)
        
        result.completed_at = datetime.now()
        result.progress = self._progress
        
        # 触发完成回调
        if self._completion_callback:
            self._completion_callback(result)
        
        return result


class BatchProcessor(Generic[T, R]):
    """
    批量处理器
    
    支持并发处理多个项目，带进度跟踪和取消功能。
    """
    
    def __init__(
        self,
        process_func: Callable[[T], R],
        max_concurrency: int = 5,
    ):
        self._process_func = process_func
        self._max_concurrency = max_concurrency
        self._cancelled = False
        self._progress = TaskProgress()
        self._progress_callback: Optional[ProgressCallback] = None
    
    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """设置进度回调"""
        self._progress_callback = callback
    
    def cancel(self) -> None:
        """取消处理"""
        self._cancelled = True
    
    async def process(self, items: List[T]) -> List[R]:
        """
        批量处理
        
        Args:
            items: 待处理项目列表
            
        Returns:
            处理结果列表
        """
        self._cancelled = False
        total = len(items)
        results: List[R] = []
        completed = 0
        
        # 创建信号量控制并发
        semaphore = asyncio.Semaphore(self._max_concurrency)
        
        async def process_item(item: T, index: int) -> Optional[R]:
            nonlocal completed
            
            if self._cancelled:
                return None
            
            async with semaphore:
                if self._cancelled:
                    return None
                
                try:
                    if asyncio.iscoroutinefunction(self._process_func):
                        result = await self._process_func(item)
                    else:
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            None, self._process_func, item
                        )
                    
                    completed += 1
                    self._update_progress(completed, total)
                    return result
                    
                except Exception as e:
                    logger.error(f"Failed to process item {index}: {e}")
                    completed += 1
                    self._update_progress(completed, total)
                    return None
        
        # 并发处理
        tasks = [
            process_item(item, i)
            for i, item in enumerate(items)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # 过滤None结果
        return [r for r in results if r is not None]
    
    def _update_progress(self, current: int, total: int) -> None:
        """更新进度"""
        self._progress.update(current, total, f"处理中 {current}/{total}")
        if self._progress_callback:
            self._progress_callback(current, total, self._progress.message)


class TaskQueue:
    """
    任务队列
    
    管理多个异步任务的执行。
    """
    
    def __init__(self, max_concurrent: int = 3):
        self._max_concurrent = max_concurrent
        self._tasks: Dict[str, AsyncTask] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
    
    def add_task(self, task: AsyncTask) -> str:
        """添加任务到队列"""
        self._tasks[task.task_id] = task
        self._queue.put_nowait(task)
        return task.task_id
    
    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """获取任务"""
        return self._tasks.get(task_id)
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if task:
            return task.cancel()
        return False
    
    def cancel_all(self) -> None:
        """取消所有任务"""
        for task in self._tasks.values():
            task.cancel()
    
    async def start(self) -> None:
        """启动任务队列"""
        if self._running:
            return
        
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
    
    async def stop(self) -> None:
        """停止任务队列"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
    
    async def _worker(self) -> None:
        """工作协程"""
        semaphore = asyncio.Semaphore(self._max_concurrent)
        
        while self._running:
            try:
                task = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )
                
                async with semaphore:
                    await task.run()
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Worker error")
    
    @property
    def pending_count(self) -> int:
        """待处理任务数"""
        return self._queue.qsize()
    
    @property
    def running_count(self) -> int:
        """运行中任务数"""
        return sum(1 for t in self._tasks.values() if t.is_running)


class AITaskManager:
    """
    AI任务管理器
    
    统一管理所有AI相关的异步任务。
    """
    
    _instance: Optional['AITaskManager'] = None
    
    def __init__(self):
        self._queue = TaskQueue(max_concurrent=3)
        self._results: Dict[str, TaskResult] = {}
    
    @classmethod
    def instance(cls) -> 'AITaskManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def start(self) -> None:
        """启动任务管理器"""
        await self._queue.start()
    
    async def stop(self) -> None:
        """停止任务管理器"""
        await self._queue.stop()
    
    def submit_task(
        self,
        func: Callable,
        *args,
        progress_callback: Optional[ProgressCallback] = None,
        completion_callback: Optional[CompletionCallback] = None,
        **kwargs,
    ) -> str:
        """
        提交任务
        
        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        task = AsyncTask(task_id, func, *args, **kwargs)
        
        if progress_callback:
            task.set_progress_callback(progress_callback)
        
        def on_complete(result: TaskResult):
            self._results[task_id] = result
            if completion_callback:
                completion_callback(result)
        
        task.set_completion_callback(on_complete)
        
        self._queue.add_task(task)
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """获取任务状态"""
        task = self._queue.get_task(task_id)
        if task:
            return task.status
        return None
    
    def get_task_progress(self, task_id: str) -> Optional[TaskProgress]:
        """获取任务进度"""
        task = self._queue.get_task(task_id)
        if task:
            return task.progress
        return None
    
    def get_task_result(self, task_id: str) -> Optional[TaskResult]:
        """获取任务结果"""
        return self._results.get(task_id)
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        return self._queue.cancel_task(task_id)
    
    def cancel_all(self) -> None:
        """取消所有任务"""
        self._queue.cancel_all()
