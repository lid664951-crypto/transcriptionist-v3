"""
DeepSeek Service

DeepSeek专用服务实现，针对DeepSeek API进行优化。
"""

from __future__ import annotations

import logging

from ..base import AIServiceConfig
from .openai_compatible import OpenAICompatibleService

logger = logging.getLogger(__name__)


class DeepSeekService(OpenAICompatibleService):
    """
    DeepSeek翻译服务
    
    基于OpenAI兼容服务，针对DeepSeek进行优化。
    """
    
    SERVICE_ID = "deepseek"
    SERVICE_NAME = "DeepSeek"
    SERVICE_DESC = "深度求索 - 性价比之选"
    
    def __init__(self, config: AIServiceConfig):
        # 设置默认值
        if not config.base_url:
            config.base_url = "https://api.deepseek.com"
        if not config.model_name:
            config.model_name = "deepseek-chat"
        
        super().__init__(config)
