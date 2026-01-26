"""
AI Service Factory

AI服务工厂，根据配置创建对应的服务实例。
"""

from __future__ import annotations

import logging
from typing import Optional, Type

from .base import AIService, AIServiceConfig, AIServiceType
from .provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class AIServiceFactory:
    """
    AI服务工厂
    
    根据配置创建对应的AI服务实例。
    """
    
    @staticmethod
    def create_service(config: AIServiceConfig) -> Optional[AIService]:
        """
        创建AI服务实例
        
        Args:
            config: 服务配置
            
        Returns:
            AI服务实例，如果提供者不存在则返回None
        """
        registry = ProviderRegistry.instance()
        
        # 获取提供者配置
        provider_config = registry.get_provider(config.provider_id)
        if provider_config is None:
            logger.error(f"Unknown provider: {config.provider_id}")
            return None
        
        # 获取服务实现类
        service_class = registry.get_service_class(config.provider_id)
        
        # 如果没有专门的实现类，使用通用OpenAI兼容实现
        if service_class is None:
            from .providers.openai_compatible import OpenAICompatibleService
            service_class = OpenAICompatibleService
        
        # 补充默认配置
        if not config.base_url and provider_config.default_base_url:
            config.base_url = provider_config.default_base_url
        
        if not config.model_name and provider_config.model_placeholder:
            config.model_name = provider_config.model_placeholder
        
        # 创建实例
        try:
            service = service_class(config)
            logger.debug(f"Created service: {config.provider_id}")
            return service
        except Exception as e:
            logger.error(f"Failed to create service: {e}")
            return None
    
    @staticmethod
    def get_available_providers():
        """获取所有可用的提供者"""
        return ProviderRegistry.instance().get_all_providers()
    
    @staticmethod
    def get_translation_providers():
        """获取支持翻译的提供者"""
        return ProviderRegistry.instance().get_providers_by_type(
            AIServiceType.TRANSLATION
        )
    
    @staticmethod
    def get_classification_providers():
        """获取支持分类的提供者"""
        return ProviderRegistry.instance().get_providers_by_type(
            AIServiceType.CLASSIFICATION
        )
