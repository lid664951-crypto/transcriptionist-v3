"""
Provider Registry

AI服务提供者注册表，管理所有可用的AI服务提供者。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type

from .base import AIService, AIServiceType

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """服务提供者配置"""
    id: str
    name: str
    description: str
    default_base_url: str = ""
    help_url: str = ""
    model_placeholder: str = ""
    is_custom: bool = False
    logo_path: Optional[str] = None
    supported_types: List[AIServiceType] = field(default_factory=lambda: [AIServiceType.TRANSLATION])
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "default_base_url": self.default_base_url,
            "help_url": self.help_url,
            "model_placeholder": self.model_placeholder,
            "is_custom": self.is_custom,
            "logo_path": self.logo_path,
            "supported_types": [t.value for t in self.supported_types],
        }


# 预定义的服务提供者（精简版：DeepSeek、豆包、ChatGPT、本地模型）
BUILTIN_PROVIDERS: List[ProviderConfig] = [
    ProviderConfig(
        id="deepseek",
        name="DeepSeek",
        description="深度求索 - 性价比之选",
        default_base_url="https://api.deepseek.com",
        help_url="https://platform.deepseek.com/api_keys",
        model_placeholder="deepseek-chat",
    ),
    ProviderConfig(
        id="doubao",
        name="豆包 (Doubao)",
        description="字节跳动 - 火山方舟",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        help_url="https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
        model_placeholder="doubao-seed-1-6-251015",
    ),
    ProviderConfig(
        id="openai",
        name="ChatGPT (OpenAI)",
        description="GPT-3.5 / GPT-4",
        default_base_url="https://api.openai.com/v1",
        help_url="https://platform.openai.com/api-keys",
        model_placeholder="gpt-3.5-turbo",
    ),
    ProviderConfig(
        id="local",
        name="本地模型 / 自定义",
        description="LM Studio / Ollama 或其他兼容服务",
        default_base_url="http://localhost:1234/v1",
        is_custom=True,
    ),
]


class ProviderRegistry:
    """
    服务提供者注册表
    
    管理所有可用的AI服务提供者，支持动态注册和查询。
    """
    
    _instance: Optional['ProviderRegistry'] = None
    
    def __init__(self):
        self._providers: Dict[str, ProviderConfig] = {}
        self._service_classes: Dict[str, Type[AIService]] = {}
        
        # 注册内置提供者
        for provider in BUILTIN_PROVIDERS:
            self.register_provider(provider)
    
    @classmethod
    def instance(cls) -> 'ProviderRegistry':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register_provider(self, config: ProviderConfig) -> None:
        """注册服务提供者"""
        self._providers[config.id] = config
        logger.debug(f"Registered provider: {config.id}")
    
    def unregister_provider(self, provider_id: str) -> None:
        """注销服务提供者"""
        if provider_id in self._providers:
            del self._providers[provider_id]
            logger.debug(f"Unregistered provider: {provider_id}")
    
    def register_service_class(
        self,
        provider_id: str,
        service_class: Type[AIService],
    ) -> None:
        """注册服务实现类"""
        self._service_classes[provider_id] = service_class
        logger.debug(f"Registered service class for: {provider_id}")
    
    def get_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        """获取提供者配置"""
        return self._providers.get(provider_id)
    
    def get_service_class(self, provider_id: str) -> Optional[Type[AIService]]:
        """获取服务实现类"""
        return self._service_classes.get(provider_id)
    
    def get_all_providers(self) -> List[ProviderConfig]:
        """获取所有提供者"""
        return list(self._providers.values())
    
    def get_providers_by_type(self, service_type: AIServiceType) -> List[ProviderConfig]:
        """按服务类型获取提供者"""
        return [
            p for p in self._providers.values()
            if service_type in p.supported_types
        ]
    
    def has_provider(self, provider_id: str) -> bool:
        """检查提供者是否存在"""
        return provider_id in self._providers
