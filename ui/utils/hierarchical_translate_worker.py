"""
增强版 TranslateWorker - 支持文件夹层级翻译
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict

from PySide6.QtCore import QObject, Signal

from transcriptionist_v3.ui.utils.translation_items import (
    TranslationItem,
    collect_translation_items
)

logger = logging.getLogger(__name__)


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
            
            # 3. 翻译文件
            if file_items and self.api_key:
                logger.info(f"Translating {len(file_items)} files...")
                file_items = self._translate_files_batch(file_items)
            
            # 4. 翻译文件夹
            if folder_items and self.api_key:
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
        from transcriptionist_v3.application.naming_manager.cleaning import CleaningManager
        
        # 清洗文件名
        cleaning_manager = CleaningManager.instance()
        cleaned_names = []
        for item in file_items:
            stem = Path(item.name).stem
            cleaned_stem = cleaning_manager.apply_all(stem)
            cleaned_names.append(cleaned_stem)
        
        # 构建 prompt
        needs_ucs = (self.template_id == "ucs_standard")
        custom_prompt = self._build_dynamic_prompt(needs_ucs, is_folder=False)
        
        # AI 翻译
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
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
            
            service_config = AIServiceConfig(
                provider_id=self.model_config["provider"],
                api_key=self.api_key,
                base_url=self.model_config["base_url"],
                model_name=self.model_config["model"],
                system_prompt=custom_prompt,
            )
            
            service = OpenAICompatibleService(service_config)
            
            result = loop.run_until_complete(
                service.translate_batch(
                    folder_names,
                    self.source_lang,
                    self.target_lang,
                )
            )
            
            if result.success:
                for i, tr in enumerate(result.data):
                    if i < len(folder_items):
                        folder_items[i].translated = tr.translated.strip()
            
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
