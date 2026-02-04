"""
增强版 TranslateWorker - 支持文件夹层级翻译
"""

import logging
import re
from pathlib import Path
from typing import Optional, List, Dict

from PySide6.QtCore import QObject, Signal

from transcriptionist_v3.ui.utils.translation_items import (
    TranslationItem,
    collect_translation_items
)

logger = logging.getLogger(__name__)


def sanitize_filename(text: str, max_length: int = 255) -> str:
    """
    清理文本以确保可用于 Windows 文件名/文件夹名
    
    Args:
        text: 待清理的文本
        max_length: 最大长度限制（Windows 路径总长度限制 260，文件名部分建议不超过 255）
    
    Returns:
        清理后的安全文件名
    """
    if not text:
        return ""
    
    # 移除所有控制字符
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    
    # 移除 Windows 文件名非法字符
    text = re.sub(r'[<>:"/\\\\|?*]', "", text)
    
    # 移除前后空白和点号（Windows 文件名不能以点开头或结尾）
    text = text.strip('. \t\n\r')
    
    # 压缩连续空格
    text = re.sub(r'\s+', ' ', text)
    
    # 长度限制
    if len(text) > max_length:
        text = text[:max_length].rstrip()
    
    return text.strip()


class HierarchicalTranslateWorker(QObject):
    """
    层级化翻译 Worker
    支持同时翻译文件和文件夹
    """
    
    finished = Signal(list)  # List[TranslationItem]
    error = Signal(str)
    progress = Signal(int, int, str)  # current, total, message
    
    def __init__(
        self,
        files: List[str],
        api_key: str,
        model_config: dict,
        glossary: dict,
        template_id: str = "translated_only",
        source_lang: str = "自动检测",
        target_lang: str = "简体中文",
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.files = files
        self.api_key = api_key
        self.model_config = model_config
        self.glossary = glossary
        self.template_id = template_id
        self.source_lang = source_lang
        self.target_lang = target_lang
        self._cancelled = False
        
        logger.info(f"HierarchicalTranslateWorker initialized with {len(files)} files")
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        """执行层级化翻译"""
        try:
            # 1. 收集所有需要翻译的项（文件 + 文件夹）
            logger.info("Collecting files and folders...")
            items = collect_translation_items(self.files)
            
            total = len(items)
            logger.info(f"Collected {total} items ({sum(1 for i in items if i.item_type == 'file')} files, {sum(1 for i in items if i.item_type == 'folder')} folders)")
            
            # 2. 分离文件和文件夹
            file_items = [item for item in items if item.item_type == 'file']
            folder_items = [item for item in items if item.item_type == 'folder']
            
            # 检查是否使用专用翻译模型（不需要 API Key）
            from transcriptionist_v3.core.config import AppConfig
            translation_model_type = AppConfig.get("ai.translation_model_type", "general")
            use_onnx_model = (translation_model_type == "hy_mt15_onnx")
            
            # 检查专用模型是否可用
            if use_onnx_model:
                from transcriptionist_v3.runtime.runtime_config import get_data_dir
                from pathlib import Path
                model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
                required_files = ["model_fp16.onnx", "model_fp16.onnx_data", "model_fp16.onnx_data_1"]
                if not all((model_dir / f).exists() for f in required_files):
                    logger.warning("HY-MT1.5 ONNX model not available, falling back to general model")
                    use_onnx_model = False
            
            # 3. 翻译文件
            if file_items and (self.api_key or use_onnx_model):
                logger.info(f"Translating {len(file_items)} files...")
                file_items = self._translate_files_batch(file_items)
            
            # 4. 翻译文件夹
            if folder_items and (self.api_key or use_onnx_model):
                logger.info(f"Translating {len(folder_items)} folders...")
                folder_items = self._translate_folders_batch(folder_items)
            
            # 5. 合并结果
            all_items = file_items + folder_items
            
            # 6. 按层级排序（用于树形展示）
            all_items.sort(key=lambda x: (x.level, x.item_type == 'file', x.path))
            
            logger.info(f"Translation complete, emitting {len(all_items)} items")
            self.finished.emit(all_items)
            
        except Exception as e:
            logger.error(f"Translation error: {e}", exc_info=True)
            self.error.emit(str(e))
    
    def _translate_files_batch(self, file_items: List[TranslationItem]) -> List[TranslationItem]:
        """批量翻译文件（复用现有逻辑）"""
        import asyncio
        from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService
        from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
        from transcriptionist_v3.core.config import AppConfig
        from transcriptionist_v3.application.naming_manager.cleaning import CleaningManager
        
        # 清洗文件名
        cleaning_manager = CleaningManager.instance()
        cleaned_names = []
        for item in file_items:
            stem = Path(item.name).stem
            cleaned_stem = cleaning_manager.apply_all(stem)
            cleaned_names.append(cleaned_stem)
        
        # 构建 prompt（仅当使用通用 LLM 时才生效）
        needs_ucs = (self.template_id == "ucs_standard")
        custom_prompt = self._build_dynamic_prompt(needs_ucs, is_folder=False)
        
        # 读取当前翻译模型类型：general / hy_mt15_onnx
        translation_model_type = AppConfig.get("ai.translation_model_type", "general")
        use_onnx_model = (translation_model_type == "hy_mt15_onnx")
        
        # AI 翻译
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            if use_onnx_model:
                # 使用 HY-MT1.5 ONNX 本地专用翻译模型
                from transcriptionist_v3.application.ai_engine.providers.hy_mt15_onnx import HyMT15OnnxService
                
                service_config = AIServiceConfig(
                    provider_id="hy_mt15_onnx",
                    api_key="",
                    base_url="",
                    model_name="hy-mt1.5-onnx",
                    system_prompt="",
                )
                logger.info("HierarchicalTranslateWorker: using HY-MT1.5 ONNX service for file translation")
                service = HyMT15OnnxService(service_config)
                loop.run_until_complete(service.initialize())
            else:
                # 使用通用 OpenAI 兼容服务（如 DeepSeek / OpenAI / 豆包 / 本地 LLM）
                service_config = AIServiceConfig(
                    provider_id=self.model_config["provider"],
                    api_key=self.api_key,
                    base_url=self.model_config["base_url"],
                    model_name=self.model_config["model"],
                    system_prompt=custom_prompt,
                )
                
                service = OpenAICompatibleService(service_config)
            
            def progress_cb(current, total, msg):
                self.progress.emit(current, total, msg)
            
            result = loop.run_until_complete(
                service.translate_batch(
                    cleaned_names,
                    self.source_lang,
                    self.target_lang,
                    progress_cb
                )
            )
            
            if result.success:
                for i, tr in enumerate(result.data):
                    if i < len(file_items):
                        # 清理后缀
                        clean_translated = tr.translated.strip()
                        original_suffix = Path(file_items[i].name).suffix
                        if clean_translated.lower().endswith(original_suffix.lower()):
                            clean_translated = clean_translated[:-len(original_suffix)].strip()
                        
                        # 最终清理：确保文件名安全（防止 WinError 87）
                        clean_translated = sanitize_filename(clean_translated, max_length=200)
                        
                        file_items[i].translated = clean_translated
                        file_items[i].category = tr.category or ""
                        file_items[i].subcategory = tr.subcategory or ""
                        file_items[i].descriptor = tr.descriptor or ""
                        file_items[i].variation = tr.variation or ""
            
            loop.run_until_complete(service.cleanup())
            loop.close()
            
        except Exception as e:
            logger.error(f"File translation error: {e}")
            # Fallback: keep original names
            for item in file_items:
                item.translated = item.name
        
        return file_items
    
    def _translate_folders_batch(self, folder_items: List[TranslationItem]) -> List[TranslationItem]:
        """批量翻译文件夹"""
        import asyncio
        from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService
        from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
        
        # 提取文件夹名
        folder_names = [item.name for item in folder_items]
        
        # 构建文件夹专用 prompt
        custom_prompt = self._build_dynamic_prompt(needs_ucs=False, is_folder=True)
        
        # AI 翻译
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # 检查是否使用专用翻译模型
            from transcriptionist_v3.core.config import AppConfig
            translation_model_type = AppConfig.get("ai.translation_model_type", "general")
            
            if translation_model_type == "hy_mt15_onnx":
                # 使用 HY-MT1.5 ONNX 专用翻译模型
                from transcriptionist_v3.application.ai_engine.providers.hy_mt15_onnx import HyMT15OnnxService
                
                service_config = AIServiceConfig(
                    provider_id="hy_mt15_onnx",
                    api_key="",
                    base_url="",
                    model_name="hy-mt1.5-onnx",
                    system_prompt="",
                )
                
                service = HyMT15OnnxService(service_config)
                loop.run_until_complete(service.initialize())
            else:
                # 使用通用模型
                service_config = AIServiceConfig(
                    provider_id=self.model_config["provider"],
                    api_key=self.api_key,
                    base_url=self.model_config["base_url"],
                    model_name=self.model_config["model"],
                    system_prompt=custom_prompt,
                )
                
                service = OpenAICompatibleService(service_config)
            
            def progress_cb(current, total, msg):
                # 文件夹翻译的进度更新（相对于总文件数）
                # 注意：文件夹翻译完成后，进度应该更新到文件翻译部分
                # 这里暂时不更新进度，因为文件夹数量通常很少
                logger.debug(f"Folder translation progress: {current}/{total} - {msg}")
            
            result = loop.run_until_complete(
                service.translate_batch(
                    folder_names,
                    self.source_lang,
                    self.target_lang,
                    progress_cb
                )
            )
            
            if result.success:
                for i, tr in enumerate(result.data):
                    if i < len(folder_items):
                        # 清理文件夹名：确保文件夹名安全（防止 WinError 87）
                        clean_translated = sanitize_filename(tr.translated.strip(), max_length=200)
                        folder_items[i].translated = clean_translated
            
            loop.run_until_complete(service.cleanup())
            loop.close()
            
        except Exception as e:
            logger.error(f"Folder translation error: {e}")
            # Fallback: keep original names
            for item in folder_items:
                item.translated = item.name
        
        return folder_items
    
    def _build_dynamic_prompt(self, needs_ucs: bool, is_folder: bool = False) -> str:
        """构建动态提示词"""
        from transcriptionist_v3.application.ai_engine.providers.openai_compatible import (
            BASIC_TRANSLATION_PROMPT,
            EXPERT_UCS_PROMPT,
            FOLDER_TRANSLATION_PROMPT,
            LANGUAGE_ENFORCEMENT_TEMPLATES,
            TARGET_LANG_EXAMPLES,
        )
        
        # 语言映射
        lang_map = {
            "自动检测": "auto-detect",
            "英语": "English",
            "日语": "Japanese",
            "韩语": "Korean",
            "俄语": "Russian",
            "德语": "German",
            "法语": "French",
            "西班牙语": "Spanish",
            "简体中文": "Simplified Chinese",
            "繁体中文": "Traditional Chinese"
        }
        
        source = lang_map.get(self.source_lang, "auto-detect")
        target = lang_map.get(self.target_lang, "Simplified Chinese")
        
        target_example = TARGET_LANG_EXAMPLES.get(target, "Translation")
        
        # 选择提示词模板
        if is_folder:
            prompt = FOLDER_TRANSLATION_PROMPT
        elif needs_ucs:
            prompt = EXPERT_UCS_PROMPT
        else:
            prompt = BASIC_TRANSLATION_PROMPT
        
        # 填充占位符
        source_lang_text = "" if source == "auto-detect" else f"{source} "
        language_enforcement = LANGUAGE_ENFORCEMENT_TEMPLATES.get(target, "")
        
        prompt = prompt.replace("{{SOURCE_LANG}}", source_lang_text)
        prompt = prompt.replace("{{TARGET_LANG}}", target)
        prompt = prompt.replace("{{TARGET_LANG_EXAMPLE}}", target_example)
        prompt = prompt.replace("{{LANGUAGE_ENFORCEMENT}}", language_enforcement)
        
        return prompt
