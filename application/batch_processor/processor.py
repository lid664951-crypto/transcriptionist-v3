"""
Batch Processor

Main batch processor combining all batch operations with progress tracking.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .converter import FormatConverter, ConversionOptions, ConversionResult
from .normalizer import LoudnessNormalizer, NormalizationOptions, NormalizationResult
from .metadata_editor import BatchMetadataEditor, MetadataOperation, MetadataEditResult
from .worker_pool import WorkerPool, BatchTask, TaskStatus

logger = logging.getLogger(__name__)


class BatchOperationType(Enum):
    """Types of batch operations."""
    CONVERT = "convert"
    NORMALIZE = "normalize"
    EDIT_METADATA = "edit_metadata"


@dataclass
class BatchOperation:
    """A batch operation configuration."""
    
    operation_type: BatchOperationType = BatchOperationType.CONVERT
    
    # File selection
    input_files: List[Path] = field(default_factory=list)
    
    # Operation-specific options
    conversion_options: Optional[ConversionOptions] = None
    normalization_options: Optional[NormalizationOptions] = None
    metadata_operations: List[MetadataOperation] = field(default_factory=list)
    
    # Processing options
    parallel: bool = True
    max_workers: int = 4


@dataclass
class BatchProgress:
    """Progress information for a batch operation."""
    
    total_files: int = 0
    processed_files: int = 0
    failed_files: int = 0
    current_file: str = ""
    current_progress: float = 0.0
    
    # Timing
    started_at: Optional[datetime] = None
    estimated_remaining: Optional[float] = None
    
    @property
    def overall_progress(self) -> float:
        """Get overall progress as percentage."""
        if self.total_files == 0:
            return 0.0
        return (self.processed_files + self.current_progress) / self.total_files
    
    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time in seconds."""
        if self.started_at:
            return (datetime.now() - self.started_at).total_seconds()
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'total_files': self.total_files,
            'processed_files': self.processed_files,
            'failed_files': self.failed_files,
            'current_file': self.current_file,
            'overall_progress': self.overall_progress,
            'elapsed_seconds': self.elapsed_seconds,
            'estimated_remaining': self.estimated_remaining,
        }


@dataclass
class BatchResult:
    """Result of a batch operation."""
    
    success: bool = False
    operation_type: BatchOperationType = BatchOperationType.CONVERT
    
    # Results
    total_files: int = 0
    successful_files: int = 0
    failed_files: int = 0
    
    # Detailed results
    conversion_results: List[ConversionResult] = field(default_factory=list)
    normalization_results: List[NormalizationResult] = field(default_factory=list)
    metadata_results: List[MetadataEditResult] = field(default_factory=list)
    
    # Errors
    errors: List[str] = field(default_factory=list)
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    @property
    def duration_seconds(self) -> float:
        """Get total duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'operation_type': self.operation_type.value,
            'total_files': self.total_files,
            'successful_files': self.successful_files,
            'failed_files': self.failed_files,
            'errors': self.errors,
            'duration_seconds': self.duration_seconds,
        }


class BatchProcessor:
    """
    Main batch processor for audio file operations.
    
    Features:
    - Format conversion
    - Loudness normalization
    - Metadata editing
    - Parallel processing
    - Progress tracking
    - Cancellation support
    """
    
    def __init__(self, max_workers: int = 4):
        """
        Initialize the batch processor.
        
        Args:
            max_workers: Maximum number of parallel workers
        """
        self.max_workers = max_workers
        
        # Components
        self.converter = FormatConverter()
        self.normalizer = LoudnessNormalizer()
        self.metadata_editor = BatchMetadataEditor()
        self.worker_pool = WorkerPool(max_workers=max_workers)
        
        # State
        self._cancelled = False
        self._progress = BatchProgress()
        self._progress_callback: Optional[Callable[[BatchProgress], None]] = None
    
    def cancel(self) -> None:
        """Cancel the current operation."""
        self._cancelled = True
        self.converter.cancel()
        self.normalizer.cancel()
        self.metadata_editor.cancel()
        self.worker_pool.cancel_all()
    
    def set_progress_callback(
        self,
        callback: Callable[[BatchProgress], None],
    ) -> None:
        """Set the progress callback."""
        self._progress_callback = callback
    
    async def process(
        self,
        operation: BatchOperation,
        progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    ) -> BatchResult:
        """
        Process a batch operation.
        
        Args:
            operation: Batch operation configuration
            progress_callback: Progress callback
        
        Returns:
            BatchResult
        """
        self._cancelled = False
        self._progress = BatchProgress(
            total_files=len(operation.input_files),
            started_at=datetime.now(),
        )
        
        if progress_callback:
            self._progress_callback = progress_callback
        
        result = BatchResult(
            operation_type=operation.operation_type,
            total_files=len(operation.input_files),
            started_at=datetime.now(),
        )
        
        try:
            if operation.operation_type == BatchOperationType.CONVERT:
                result = await self._process_conversion(operation, result)
            
            elif operation.operation_type == BatchOperationType.NORMALIZE:
                result = await self._process_normalization(operation, result)
            
            elif operation.operation_type == BatchOperationType.EDIT_METADATA:
                result = await self._process_metadata(operation, result)
            
            result.success = result.failed_files == 0
            
        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"Batch processing error: {e}")
        
        finally:
            result.completed_at = datetime.now()
        
        return result
    
    async def _process_conversion(
        self,
        operation: BatchOperation,
        result: BatchResult,
    ) -> BatchResult:
        """Process format conversion."""
        if not operation.conversion_options:
            result.errors.append("No conversion options provided")
            return result
        
        def update_progress(progress: float, message: str):
            self._progress.current_progress = progress
            self._progress.current_file = message
            self._update_estimated_remaining()
            self._notify_progress()
        
        results = await self.converter.convert_batch(
            operation.input_files,
            operation.conversion_options,
            update_progress,
        )
        
        result.conversion_results = results
        result.successful_files = sum(1 for r in results if r.success)
        result.failed_files = sum(1 for r in results if not r.success)
        result.errors.extend(r.error for r in results if r.error)
        
        return result
    
    async def _process_normalization(
        self,
        operation: BatchOperation,
        result: BatchResult,
    ) -> BatchResult:
        """Process loudness normalization."""
        if not operation.normalization_options:
            result.errors.append("No normalization options provided")
            return result
        
        def update_progress(progress: float, message: str):
            self._progress.current_progress = progress
            self._progress.current_file = message
            self._update_estimated_remaining()
            self._notify_progress()
        
        results = await self.normalizer.normalize_batch(
            operation.input_files,
            operation.normalization_options,
            update_progress,
        )
        
        result.normalization_results = results
        result.successful_files = sum(1 for r in results if r.success)
        result.failed_files = sum(1 for r in results if not r.success)
        result.errors.extend(r.error for r in results if r.error)
        
        return result
    
    async def _process_metadata(
        self,
        operation: BatchOperation,
        result: BatchResult,
    ) -> BatchResult:
        """Process metadata editing."""
        if not operation.metadata_operations:
            result.errors.append("No metadata operations provided")
            return result
        
        def update_progress(progress: float, message: str):
            self._progress.current_progress = progress
            self._progress.current_file = message
            self._update_estimated_remaining()
            self._notify_progress()
        
        results = await self.metadata_editor.edit_batch(
            operation.input_files,
            operation.metadata_operations,
            update_progress,
        )
        
        result.metadata_results = results
        result.successful_files = sum(1 for r in results if r.success)
        result.failed_files = sum(1 for r in results if not r.success)
        result.errors.extend(r.error for r in results if r.error)
        
        return result
    
    def _update_estimated_remaining(self) -> None:
        """Update estimated remaining time."""
        if self._progress.processed_files > 0:
            elapsed = self._progress.elapsed_seconds
            rate = self._progress.processed_files / elapsed if elapsed > 0 else 0
            remaining = self._progress.total_files - self._progress.processed_files
            if rate > 0:
                self._progress.estimated_remaining = remaining / rate
    
    def _notify_progress(self) -> None:
        """Notify progress callback."""
        if self._progress_callback:
            self._progress_callback(self._progress)
    
    def get_progress(self) -> BatchProgress:
        """Get current progress."""
        return self._progress
    
    # Convenience methods
    
    async def convert_files(
        self,
        files: List[Path],
        options: ConversionOptions,
        progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    ) -> BatchResult:
        """
        Convert multiple files.
        
        Args:
            files: List of input files
            options: Conversion options
            progress_callback: Progress callback
        
        Returns:
            BatchResult
        """
        operation = BatchOperation(
            operation_type=BatchOperationType.CONVERT,
            input_files=files,
            conversion_options=options,
        )
        return await self.process(operation, progress_callback)
    
    async def normalize_files(
        self,
        files: List[Path],
        options: NormalizationOptions,
        progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    ) -> BatchResult:
        """
        Normalize multiple files.
        
        Args:
            files: List of input files
            options: Normalization options
            progress_callback: Progress callback
        
        Returns:
            BatchResult
        """
        operation = BatchOperation(
            operation_type=BatchOperationType.NORMALIZE,
            input_files=files,
            normalization_options=options,
        )
        return await self.process(operation, progress_callback)
    
    async def edit_metadata(
        self,
        files: List[Path],
        operations: List[MetadataOperation],
        progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    ) -> BatchResult:
        """
        Edit metadata of multiple files.
        
        Args:
            files: List of input files
            operations: Metadata operations
            progress_callback: Progress callback
        
        Returns:
            BatchResult
        """
        operation = BatchOperation(
            operation_type=BatchOperationType.EDIT_METADATA,
            input_files=files,
            metadata_operations=operations,
        )
        return await self.process(operation, progress_callback)
    
    def can_undo_metadata(self) -> bool:
        """Check if metadata undo is available."""
        return self.metadata_editor.can_undo()
    
    def can_redo_metadata(self) -> bool:
        """Check if metadata redo is available."""
        return self.metadata_editor.can_redo()
    
    async def undo_metadata(
        self,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        """Undo last metadata operation."""
        return await self.metadata_editor.undo(progress_callback)
    
    async def redo_metadata(
        self,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        """Redo last undone metadata operation."""
        return await self.metadata_editor.redo(progress_callback)
