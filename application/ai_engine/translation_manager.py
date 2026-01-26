"""
Translation Manager

翻译管理器，整合翻译服务和缓存。
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Callable
from dataclasses import dataclass

from .base import (
    AIResult,
    AIResultStatus,
    AIServiceConfig,
    ProgressCallback,
    TranslationResult,
    TranslationService,
)
from .service_factory import AIServiceFactory
from .translation_cache import TranslationCache

logger = logging.getLogger(__name__)


@dataclass
class TranslationTask:
    """翻译任务"""
    texts: List[str]
    source_lang: str = "en"
    target_lang: str = "zh"
    use_cache: bool = True


class TranslationManager:
    """
    翻译管理器
    
    功能：
    - 管理翻译服务实例
    - 整合缓存
    - 批量翻译优化
    - 进度回调
    """
    
    _instance: Optional['TranslationManager'] = None
    
    def __init__(self):
        self._service: Optional[TranslationService] = None
        self._config: Optional[AIServiceConfig] = None
        self._cache = TranslationCache.instance()
    
    @classmethod
    def instance(cls) -> 'TranslationManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def configure(self, config: AIServiceConfig) -> bool:
        """配置翻译服务"""
        service = AIServiceFactory.create_service(config)
        if service is None:
            return False
        
        if not isinstance(service, TranslationService):
            logger.error(f"Service {config.provider_id} is not a translation service")
            return False
        
        self._service = service
        self._config = config
        return True
    
    @property
    def is_configured(self) -> bool:
        """是否已配置"""
        return self._service is not None
    
    @property
    def current_provider(self) -> Optional[str]:
        """当前提供者ID"""
        return self._config.provider_id if self._config else None
    
    async def test_connection(self) -> AIResult[bool]:
        """测试连接"""
        if not self._service:
            return AIResult(
                status=AIResultStatus.ERROR,
                error="未配置翻译服务",
            )
        
        return await self._service.test_connection()
    
    async def translate(
        self,
        text: str,
        use_cache: bool = True,
    ) -> AIResult[TranslationResult]:
        """翻译单个文本"""
        result = await self.translate_batch([text], use_cache=use_cache)
        
        if result.success and result.data:
            return AIResult(
                status=result.status,
                data=result.data[0],
                cached=result.cached,
            )
        
        return AIResult(status=result.status, error=result.error)
    
    async def translate_batch(
        self,
        texts: List[str],
        use_cache: bool = True,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AIResult[List[TranslationResult]]:
        """批量翻译"""
        if not self._service:
            return AIResult(
                status=AIResultStatus.ERROR,
                error="未配置翻译服务",
            )
        
        if not texts:
            return AIResult(status=AIResultStatus.SUCCESS, data=[])
        
        provider_id = self._config.provider_id if self._config else ""
        results: List[TranslationResult] = []
        texts_to_translate: List[str] = []
        cache_hits = 0
        
        # 1. 检查缓存
        if use_cache:
            for text in texts:
                cached = self._cache.get(text, provider_id)
                if cached:
                    results.append(TranslationResult(
                        original=text,
                        translated=cached,
                    ))
                    cache_hits += 1
                else:
                    texts_to_translate.append(text)
        else:
            texts_to_translate = texts.copy()
        
        # 全部命中缓存
        if not texts_to_translate:
            if progress_callback:
                progress_callback(len(texts), len(texts), "全部来自缓存")
            return AIResult(
                status=AIResultStatus.CACHED,
                data=results,
                cached=True,
            )
        
        # 2. 调用翻译服务
        def wrapped_callback(current: int, total: int, msg: str):
            if progress_callback:
                actual_current = cache_hits + current
                actual_total = len(texts)
                progress_callback(actual_current, actual_total, msg)
        
        api_result = await self._service.translate_batch(
            texts_to_translate,
            progress_callback=wrapped_callback if progress_callback else None,
        )
        
        if not api_result.success:
            return api_result
        
        # 3. 更新缓存并合并结果
        if api_result.data:
            for tr in api_result.data:
                if use_cache:
                    self._cache.set(tr.original, tr.translated, provider_id)
                results.append(tr)
        
        # 保存缓存
        self._cache.save()
        
        # 按原始顺序排序
        result_map = {r.original: r for r in results}
        ordered_results = [result_map.get(t, TranslationResult(t, t)) for t in texts]
        
        return AIResult(
            status=AIResultStatus.SUCCESS,
            data=ordered_results,
            usage=api_result.usage,
            cached=cache_hits > 0,
        )
    
    async def translate_files(
        self,
        filenames: List[str],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AIResult[List[TranslationResult]]:
        """翻译文件名列表"""
        return await self.translate_batch(
            filenames,
            use_cache=True,
            progress_callback=progress_callback,
        )
    
    def clear_cache(self) -> None:
        """清空缓存"""
        self._cache.clear()
        self._cache.save()
    
    def get_cache_stats(self) -> dict:
        """获取缓存统计"""
        return self._cache.get_stats()
    
    async def cleanup(self) -> None:
        """清理资源"""
        if self._service:
            await self._service.cleanup()
        self._cache.save()
