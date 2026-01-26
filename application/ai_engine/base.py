"""
AI Service Base Classes

定义AI服务的基类和通用接口。
参考Quod Libet的插件架构设计。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic
from pathlib import Path

logger = logging.getLogger(__name__)


class AIServiceType(Enum):
    """AI服务类型"""
    TRANSLATION = "translation"
    CLASSIFICATION = "classification"
    TAG_GENERATION = "tag_generation"
    SIMILARITY = "similarity"


class AIResultStatus(Enum):
    """AI结果状态"""
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"
    CACHED = "cached"


@dataclass
class AIServiceConfig:
    """AI服务配置"""
    provider_id: str
    api_key: str = ""
    base_url: str = ""
    model_name: str = ""
    system_prompt: str = ""
    temperature: float = 0.3
    max_tokens: int = 2000
    timeout: int = 30
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "provider_id": self.provider_id,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model_name": self.model_name,
            "system_prompt": self.system_prompt,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "extra": self.extra,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AIServiceConfig':
        """从字典创建"""
        return cls(
            provider_id=data.get("provider_id", ""),
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url", ""),
            model_name=data.get("model_name", ""),
            system_prompt=data.get("system_prompt", ""),
            temperature=data.get("temperature", 0.3),
            max_tokens=data.get("max_tokens", 2000),
            timeout=data.get("timeout", 30),
            extra=data.get("extra", {}),
        )


T = TypeVar('T')


@dataclass
class AIResult(Generic[T]):
    """AI服务结果"""
    status: AIResultStatus
    data: Optional[T] = None
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None  # token使用量
    cached: bool = False
    
    @property
    def success(self) -> bool:
        return self.status in (AIResultStatus.SUCCESS, AIResultStatus.CACHED)


@dataclass
class TranslationResult:
    """翻译结果"""
    original: str
    translated: str
    confidence: float = 1.0
    
    # UCS 组件 (可选)
    category: Optional[str] = None
    subcategory: Optional[str] = None
    descriptor: Optional[str] = None
    variation: Optional[str] = None


@dataclass
class ClassificationResult:
    """分类结果"""
    category: str
    confidence: float
    subcategories: List[str] = field(default_factory=list)


@dataclass
class TagResult:
    """标签生成结果"""
    tags: List[str]
    confidence: float = 1.0


@dataclass
class SimilarityResult:
    """相似度搜索结果"""
    file_id: str
    file_path: Path
    similarity: float
    features: Optional[Dict[str, Any]] = None


# 进度回调类型
ProgressCallback = Callable[[int, int, str], None]  # (current, total, message)


class AIService(ABC):
    """
    AI服务基类
    
    所有AI服务提供者必须继承此类并实现相关方法。
    参考Quod Libet的Plugin架构设计。
    """
    
    # 服务标识（子类必须定义）
    SERVICE_ID: str = ""
    SERVICE_NAME: str = ""
    SERVICE_DESC: str = ""
    SERVICE_TYPE: AIServiceType = AIServiceType.TRANSLATION
    
    def __init__(self, config: AIServiceConfig):
        self._config = config
        self._enabled = True
    
    @property
    def id(self) -> str:
        return self.SERVICE_ID
    
    @property
    def name(self) -> str:
        return self.SERVICE_NAME
    
    @property
    def description(self) -> str:
        return self.SERVICE_DESC
    
    @property
    def service_type(self) -> AIServiceType:
        return self.SERVICE_TYPE
    
    @property
    def config(self) -> AIServiceConfig:
        return self._config
    
    @config.setter
    def config(self, value: AIServiceConfig) -> None:
        self._config = value
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
    
    @abstractmethod
    async def test_connection(self) -> AIResult[bool]:
        """测试连接"""
        pass
    
    async def initialize(self) -> None:
        """初始化服务（可选）"""
        pass
    
    async def cleanup(self) -> None:
        """清理资源（可选）"""
        pass


class TranslationService(AIService):
    """翻译服务基类"""
    
    SERVICE_TYPE = AIServiceType.TRANSLATION
    
    @abstractmethod
    async def translate(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "zh",
    ) -> AIResult[TranslationResult]:
        """翻译单个文本"""
        pass
    
    @abstractmethod
    async def translate_batch(
        self,
        texts: List[str],
        source_lang: str = "en",
        target_lang: str = "zh",
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AIResult[List[TranslationResult]]:
        """批量翻译"""
        pass


class ClassificationService(AIService):
    """分类服务基类（预留接口）"""
    
    SERVICE_TYPE = AIServiceType.CLASSIFICATION
    
    @abstractmethod
    async def classify(
        self,
        file_path: Path,
    ) -> AIResult[ClassificationResult]:
        """分类单个音频文件"""
        pass
    
    @abstractmethod
    async def classify_batch(
        self,
        file_paths: List[Path],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AIResult[List[ClassificationResult]]:
        """批量分类"""
        pass


class TagGenerationService(AIService):
    """标签生成服务基类"""
    
    SERVICE_TYPE = AIServiceType.TAG_GENERATION
    
    @abstractmethod
    async def generate_tags(
        self,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AIResult[TagResult]:
        """从文件名生成标签"""
        pass
    
    @abstractmethod
    async def generate_tags_batch(
        self,
        items: List[Dict[str, Any]],  # [{filename, metadata}, ...]
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AIResult[List[TagResult]]:
        """批量生成标签"""
        pass


class SimilarityService(AIService):
    """相似度搜索服务基类"""
    
    SERVICE_TYPE = AIServiceType.SIMILARITY
    
    @abstractmethod
    async def find_similar(
        self,
        file_path: Path,
        top_k: int = 10,
    ) -> AIResult[List[SimilarityResult]]:
        """查找相似音频"""
        pass
    
    @abstractmethod
    async def extract_features(
        self,
        file_path: Path,
    ) -> AIResult[Dict[str, Any]]:
        """提取音频特征"""
        pass
