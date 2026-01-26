"""
AI Engine Module

音译家的AI引擎模块，提供翻译、分类、标签生成等AI功能。
采用插件式架构，支持多种AI后端。
"""

from .base import (
    AIService,
    AIServiceConfig,
    AIResult,
    AIResultStatus,
    AIServiceType,
    TranslationResult,
    ClassificationResult,
    TagResult,
    SimilarityResult,
    ProgressCallback,
    TranslationService,
    ClassificationService,
    TagGenerationService,
    SimilarityService,
)
from .provider_registry import ProviderRegistry, ProviderConfig, BUILTIN_PROVIDERS
from .service_factory import AIServiceFactory
from .translation_cache import TranslationCache
from .translation_manager import TranslationManager
from .tag_generator import TagManager, FilenameTagExtractor
from .audio_analyzer import AudioAnalyzer, AudioClassificationService, AudioSimilarityService
from .async_processor import (
    AsyncTask,
    BatchProcessor,
    TaskQueue,
    AITaskManager,
    TaskStatus,
    TaskProgress,
    TaskResult,
)

__all__ = [
    # Base classes
    'AIService',
    'AIServiceConfig',
    'AIResult',
    'AIResultStatus',
    'AIServiceType',
    'TranslationResult',
    'ClassificationResult',
    'TagResult',
    'SimilarityResult',
    'ProgressCallback',
    'TranslationService',
    'ClassificationService',
    'TagGenerationService',
    'SimilarityService',
    # Registry
    'ProviderRegistry',
    'ProviderConfig',
    'BUILTIN_PROVIDERS',
    'AIServiceFactory',
    # Translation
    'TranslationCache',
    'TranslationManager',
    # Tags
    'TagManager',
    'FilenameTagExtractor',
    # Audio Analysis (CLAP预留)
    'AudioAnalyzer',
    'AudioClassificationService',
    'AudioSimilarityService',
    # Async Processing
    'AsyncTask',
    'BatchProcessor',
    'TaskQueue',
    'AITaskManager',
    'TaskStatus',
    'TaskProgress',
    'TaskResult',
]
