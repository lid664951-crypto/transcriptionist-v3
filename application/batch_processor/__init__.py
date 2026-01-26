"""
Batch Processor Module

Provides batch processing functionality for audio files.
Inspired by Quod Libet's copool patterns for background processing.

Features:
- Format conversion using ffmpeg
- Loudness normalization using pyloudnorm
- Batch metadata editing
- Parallel processing with worker pool
- Progress tracking and cancellation
- Undo support for metadata operations
"""

from .converter import FormatConverter, ConversionOptions, ConversionResult, AudioFormat, AudioCodec
from .normalizer import LoudnessNormalizer, NormalizationOptions, NormalizationResult, NormalizationStandard
from .metadata_editor import BatchMetadataEditor, MetadataOperation, MetadataEditResult, OperationType, MetadataField
from .worker_pool import WorkerPool, BatchTask, TaskStatus
from .processor import BatchProcessor, BatchOperation, BatchResult, BatchOperationType, BatchProgress

__all__ = [
    # Converter
    'FormatConverter',
    'ConversionOptions',
    'ConversionResult',
    'AudioFormat',
    'AudioCodec',
    # Normalizer
    'LoudnessNormalizer',
    'NormalizationOptions',
    'NormalizationResult',
    'NormalizationStandard',
    # Metadata editor
    'BatchMetadataEditor',
    'MetadataOperation',
    'MetadataEditResult',
    'OperationType',
    'MetadataField',
    # Worker pool
    'WorkerPool',
    'BatchTask',
    'TaskStatus',
    # Main processor
    'BatchProcessor',
    'BatchOperation',
    'BatchResult',
    'BatchOperationType',
    'BatchProgress',
]
