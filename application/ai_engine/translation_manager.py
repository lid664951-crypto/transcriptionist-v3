"""
Translation Manager

翻译管理器，整合翻译服务和缓存。
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Callable, Tuple
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


def get_translation_config_from_app(system_prompt: str = "") -> Tuple[Optional[AIServiceConfig], Optional[str]]:
    """
    从「设置 -> AI 服务商配置」读取当前翻译模型配置，供标签翻译、批量翻译等统一使用。
    支持 DeepSeek / OpenAI / 豆包 / 本地模型（Ollama、LM Studio 等），无 DeepSeek 硬编码。
    返回 (AIServiceConfig, None) 或 (None, error_message)。
    """
    try:
        from transcriptionist_v3.core.config import AppConfig
    except Exception as e:
        logger.debug(f"get_translation_config_from_app: AppConfig failed: {e}")
        return None, "无法读取配置"

    model_index = int(AppConfig.get("ai.model_index", 0))
    api_key = (AppConfig.get("ai.api_key", "") or "").strip()

    # 与设置页一致：0=DeepSeek, 1=OpenAI, 2=豆包, 3=本地模型（Ollama / LM Studio）
    provider_model_map = {
        0: ("deepseek", "deepseek-chat", "https://api.deepseek.com/v1"),
        1: ("openai", "gpt-4o-mini", "https://api.openai.com/v1"),
        2: ("doubao", "doubao-pro-4k", "https://ark.cn-beijing.volces.com/api/v3"),
        3: ("local", None, None),  # 使用 ai.local_model_name / ai.local_base_url
    }
    t = provider_model_map.get(model_index, provider_model_map[0])
    provider_id, default_model, default_base = t

    if provider_id == "local":
        base_url = (AppConfig.get("ai.local_base_url", "") or "").strip()
        model_name = (AppConfig.get("ai.local_model_name", "") or "").strip()
        if not base_url:
            base_url = "http://localhost:1234/v1"
        if not model_name:
            model_name = "local"
        api_key = ""
        if not base_url or not model_name:
            return None, "请在设置中配置本地模型的 Base URL 和模型名称（Ollama / LM Studio）"
    else:
        base_url = default_base or ""
        model_name = default_model or ""
        if not api_key:
            return None, "请在设置 -> AI 配置 中配置 API 密钥"

    config = AIServiceConfig(
        provider_id=provider_id,
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        system_prompt=system_prompt,
        timeout=30,
        max_tokens=256,
        temperature=0.3,
    )
    return config, None


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
        """配置翻译服务
        
        优先级：
        1. 如果全局设置中启用了 HY-MT1.5 ONNX 专用翻译模型，且本地模型文件完整可用，
           则强制使用 HyMT15OnnxService 作为翻译服务（忽略传入的 provider_id）。
        2. 否则，按照传入的配置和 ProviderRegistry 正常创建服务实例。
        """
        # 1. 检查是否启用 HY-MT1.5 ONNX 专用翻译模型
        try:
            from transcriptionist_v3.core.config import AppConfig
            translation_model_type = AppConfig.get("ai.translation_model_type", "general")
        except Exception as e:
            logger.debug(f"Failed to read translation model type from AppConfig: {e}")
            translation_model_type = "general"
        
        # 1.1 如果启用了 HY-MT1.5 ONNX，并且本地模型就绪，则强制使用本地 ONNX 模型 - 已注释（模型加载慢且翻译质量不稳定）
        # if translation_model_type == "hy_mt15_onnx":
        #     try:
        #         from transcriptionist_v3.runtime.runtime_config import get_data_dir
        #         from pathlib import Path
        #         
        #         model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
        #         required_files = ["model_fp16.onnx", "model_fp16.onnx_data", "model_fp16.onnx_data_1"]
        #         has_required = all((model_dir / f).exists() for f in required_files)
        #         has_tokenizer = (model_dir / "tokenizer.json").exists() or (model_dir / "tokenizer_config.json").exists()
        #         
        #         if has_required and has_tokenizer:
        #             # 导入 HY-MT1.5 ONNX 服务实现
        #             from transcriptionist_v3.application.ai_engine.providers.hy_mt15_onnx import HyMT15OnnxService
        #             
        #             # 为本地模型构建一个最小配置（不需要 API Key / Base URL）
        #             service_config = AIServiceConfig(
        #                 provider_id="hy_mt15_onnx",
        #                 api_key="",
        #                 base_url="",
        #                 model_name="hy-mt1.5-onnx",
        #                 system_prompt=getattr(config, "system_prompt", "") if config else "",
        #             )
        #             
        #             service = HyMT15OnnxService(service_config)
        #             
        #             if not isinstance(service, TranslationService):
        #                 logger.error("HY-MT1.5 ONNX service is not a TranslationService")
        #             else:
        #                 # 成功使用专用翻译模型
        #                 self._service = service
        #                 self._config = service_config
        #                 logger.info("TranslationManager configured with HY-MT1.5 ONNX translation service")
        #                 return True
        #         else:
        #             logger.warning("HY-MT1.5 ONNX model not fully available, falling back to general provider")
        #     except Exception as e:
        #         # 出现任何异常时，回退到通用 provider 流程
        #         logger.warning(f"Failed to configure HY-MT1.5 ONNX translation service, fallback to general: {e}", exc_info=True)
        
        # 如果配置了 hy_mt15_onnx，强制回退到通用模型
        if translation_model_type == "hy_mt15_onnx":
            logger.info("HY-MT1.5 ONNX model is disabled, falling back to general provider")
            translation_model_type = "general"
        
        # 2. 正常根据 provider 配置创建服务实例
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
