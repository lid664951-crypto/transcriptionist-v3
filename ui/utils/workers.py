"""
Background worker utilities for Qt threading.
Provides base classes and helper functions for managing QThread workers.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Any, Callable

from PySide6.QtCore import QThread, QObject, Signal

logger = logging.getLogger(__name__)


class BaseWorker(QObject):
    """
    Base class for background workers.
    Provides common signals and cancellation support.
    
    Signals:
        finished: Emitted when work is completed successfully
        error: Emitted when an error occurs (with error message)
        progress: Emitted to report progress (current, total, message)
    """
    
    finished = Signal(object)  # Result data
    error = Signal(str)  # Error message
    progress = Signal(int, int, str)  # current, total, message
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cancelled = False
    
    def cancel(self) -> None:
        """Request cancellation of the work."""
        self._cancelled = True
    
    @property
    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancelled
    
    def run(self) -> None:
        """
        Override this method to implement the actual work.
        Check self.is_cancelled periodically and return early if True.
        """
        raise NotImplementedError("Subclasses must implement run()")


def cleanup_thread(
    thread: Optional[QThread],
    worker: Optional[QObject] = None,
    timeout_ms: int = 5000
) -> None:
    """
    Safely cleanup a QThread and its worker.
    
    Args:
        thread: The QThread to cleanup
        worker: Optional worker object (will be set to None after cleanup)
        timeout_ms: Timeout in milliseconds to wait for thread to finish
    """
    if thread is None:
        return
    
    try:
        if thread.isRunning():
            thread.quit()
            if not thread.wait(timeout_ms):
                logger.warning(f"Thread did not finish within {timeout_ms}ms, forcing termination")
                thread.terminate()
                thread.wait()
    except RuntimeError:
        # Thread already deleted
        pass


class DatabaseLoadWorker(BaseWorker):
    """
    Worker for loading audio files from database asynchronously.
    Used by LibraryPage to avoid blocking UI on startup.
    """
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
    
    def run(self) -> None:
        """Load audio files from database."""
        try:
            from transcriptionist_v3.infrastructure.database.connection import get_session
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            from transcriptionist_v3.domain.models.metadata import AudioMetadata
            from pathlib import Path
            
            session = get_session()
            try:
                from sqlalchemy.orm import joinedload
                from transcriptionist_v3.infrastructure.database.models import LibraryPath
                
                # Query all audio files with tags eagerly loaded
                audio_files = session.query(AudioFile).options(joinedload(AudioFile.tags)).all()
                
                if not audio_files:
                    logger.info("No audio files in database")
                    # Fetch library paths (roots)
                    lib_paths = session.query(LibraryPath).filter_by(enabled=True).all()
                    root_paths = [Path(lp.path) for lp in lib_paths]
                    
                    self.finished.emit(([], root_paths))
                    return
                
                total = len(audio_files)
                results = []
                
                # OPTIMIZATION: Skip file existence check on startup for performance
                # Files will be validated when actually accessed (play, rename, etc.)
                # This makes startup 10-20x faster for large libraries
                
                for i, db_file in enumerate(audio_files):
                    if self.is_cancelled:
                        return
                    
                    file_path = Path(db_file.file_path)
                    
                    # Create metadata object (no file I/O)
                    metadata = AudioMetadata(
                        id=db_file.id,
                        duration=db_file.duration,
                        sample_rate=db_file.sample_rate,
                        bit_depth=db_file.bit_depth,
                        channels=db_file.channels,
                        format=db_file.format,
                        comment=getattr(db_file, 'description', '')  # Use comment field
                    )
                    
                    # Populate additional metadata
                    metadata.original_filename = getattr(db_file, 'original_filename', file_path.name)
                    metadata.tags = [t.tag for t in db_file.tags]
                    
                    results.append((file_path, metadata))
                    
                    # Report progress every 100 files (less frequent for speed)
                    if (i + 1) % 100 == 0 or i == total - 1:
                        self.progress.emit(i + 1, total, f"加载中 ({i+1}/{total})")
                        
                # Fetch library paths (roots) at the end
                lib_paths = session.query(LibraryPath).filter_by(enabled=True).all()
                root_paths = [Path(lp.path) for lp in lib_paths]
                
                self.finished.emit((results, root_paths))
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Failed to load from database: {e}")
            self.error.emit(str(e))


class TranslateWorker(BaseWorker):
    """
    Worker for AI translation tasks.
    Runs translation in background thread with progress reporting.
    """
    
    def __init__(
        self,
        files: list,
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
        
        logger.info(f"TranslateWorker initialized with {len(self.files)} files, api_key={'yes' if self.api_key else 'no'}, {source_lang} -> {target_lang}")
    
    def run(self) -> None:
        """Execute the translation task."""
        from transcriptionist_v3.application.naming_manager.cleaning import CleaningManager
        
        # 1. 预处理：应用清洗规则
        cleaning_manager = CleaningManager.instance()
        cleaned_files = []
        for fp in self.files:
            p = Path(fp)
            # 清理文件名（不含后缀部分）
            cleaned_stem = cleaning_manager.apply_all(p.stem)
            cleaned_files.append(cleaned_stem + p.suffix)
        
        total = len(self.files)
        results = []
        
        # If API key provided, try AI translation
        if self.api_key:
            logger.info("Attempting AI translation...")
            try:
                from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService
                from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
                
                # 2. 准备动态 System Prompt
                # 只有 UCS 标准命名需要 Expert 模式
                needs_ucs = (self.template_id == "ucs_standard")
                logger.info(f"Building prompt for template='{self.template_id}', needs_ucs={needs_ucs}")
                
                # 构建动态语言提示词 (不再包含术语库)
                custom_prompt = self._build_dynamic_prompt(needs_ucs)
                
                # Create service config
                service_config = AIServiceConfig(
                    provider_id=self.model_config["provider"],
                    api_key=self.api_key,
                    base_url=self.model_config["base_url"],
                    model_name=self.model_config["model"],
                    system_prompt=custom_prompt,
                    timeout=180,
                    max_tokens=4096,
                    temperature=0.3,
                )
                service = OpenAICompatibleService(service_config)
                
                # 使用清洗后的文件名进行翻译
                logger.info(f"Translating {len(cleaned_files)} cleaned filenames")
                
                # Run async translation
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                def progress_cb(current: int, total: int, msg: str) -> None:
                    if not self.is_cancelled:
                        self.progress.emit(current, total, msg)
                
                try:
                    result = loop.run_until_complete(
                        service.translate_batch(cleaned_files, progress_callback=progress_cb)
                    )
                    
                    if result.success and result.data:
                        logger.info(f"AI returned {len(result.data)} results")
                        for i, tr in enumerate(result.data):
                            # CRITICAL FIX: Strip extension immediately from AI result logic
                            # This ensures that 'translated' is always just the name, confirming to template expectations
                            original_name = Path(self.files[i]).name
                            original_suffix = Path(self.files[i]).suffix
                            
                            clean_translated = tr.translated.strip() if tr.translated else ""
                            # Remove extension if AI added it (case-insensitive)
                            if clean_translated.lower().endswith(original_suffix.lower()):
                                clean_translated = clean_translated[:-len(original_suffix)].strip()
                                logger.info(f"Stripped extension: '{tr.translated}' -> '{clean_translated}'")
                            
                            results.append({
                                'original': original_name,
                                'translated': clean_translated,
                                'category': tr.category,
                                'subcategory': tr.subcategory,
                                'descriptor': tr.descriptor,
                                'variation': tr.variation,
                                'file_path': self.files[i],
                                'status': '待应用'
                            })
                        self.finished.emit(results)
                        return
                    else:
                        logger.warning(f"AI translation failed: {result.error}, falling back to local")
                        
                finally:
                    loop.run_until_complete(service.cleanup())
                    loop.close()
                    
            except Exception as e:
                logger.error(f"AI translation error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Fall through to local translation
        
        # Fallback to local glossary translation
        logger.info("Using local glossary translation")
        results = self._local_translate(total)
        logger.info(f"Local translation done, emitting finished with {len(results)} results")
        self.finished.emit(results)
    
    def _build_dynamic_prompt(self, needs_ucs: bool) -> str:
        """
        构建动态提示词，使用统一模板填充所有占位符
        
        Args:
            needs_ucs: 是否需要 UCS 专家模式
        """
        from transcriptionist_v3.application.ai_engine.providers.openai_compatible import (
            BASIC_TRANSLATION_PROMPT,
            EXPERT_UCS_PROMPT,
            LANGUAGE_ENFORCEMENT_TEMPLATES,
            TARGET_LANG_EXAMPLES,
        )
        
        # 语言映射（界面显示 -> AI理解）
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
        
        # 获取目标语言示例
        target_example = TARGET_LANG_EXAMPLES.get(target, "Translation")
        
        # 1. 填充源语言（自动检测时不写死）
        if source == "auto-detect":
            source_lang_text = ""  # 不指定，让 AI 自动检测
        else:
            source_lang_text = f"{source} "  # 例如 "English "
        
        # 2. 填充语言强制指令
        language_enforcement = LANGUAGE_ENFORCEMENT_TEMPLATES.get(target, "")
        
        # 3. 选择并构建最终提示词 (Dual Mode Logic)
        if needs_ucs:
            # Expert UCS Mode
            prompt = EXPERT_UCS_PROMPT
        else:
            # Basic Mode
            prompt = BASIC_TRANSLATION_PROMPT
            
        # 4. 替换通用占位符
        prompt = prompt.replace("{{SOURCE_LANG}}", source_lang_text)
        prompt = prompt.replace("{{TARGET_LANG}}", target)
        prompt = prompt.replace("{{TARGET_LANG_EXAMPLE}}", target_example)
        prompt = prompt.replace("{{LANGUAGE_ENFORCEMENT}}", language_enforcement)
        
        return prompt
    
    def _local_translate(self, total: int) -> list:
        """Fallback to local glossary translation."""
        import re
        from transcriptionist_v3.application.naming_manager.cleaning import CleaningManager
        
        results = []
        
        for i, file_path_str in enumerate(self.files):
            if self.is_cancelled:
                return results
            
            file_path = Path(file_path_str)
            original_name = file_path.name
            
            # 使用清洗后的主文件名
            cleaning_manager = CleaningManager.instance()
            cleaned_stem = cleaning_manager.apply_all(file_path.stem)
            
            # Translate using glossary
            translated = self._translate_with_glossary(cleaned_stem) + file_path.suffix
            
            results.append({
                'original': original_name,
                'translated': translated,
                'file_path': file_path_str,
                'status': '待应用'
            })
            
            # Update progress
            self.progress.emit(i + 1, total, f"翻译中: {original_name}")
            
            # Add a small delay for visual feedback if local translation is too fast
            import time
            time.sleep(0.01)
        
        return results
    
    def _translate_with_glossary(self, text: str) -> str:
        """使用术语库翻译文本，支持CamelCase拆分和单复数匹配。"""
        import re
        
        # 1. 对原始文本进行预处理：拆分 CamelCase 和下划线
        # 例如: ClockTicking -> Clock Ticking, foot_step -> foot step
        parts = self._split_text(text)
        translated_parts = []
        
        for part in parts:
            if not part.strip():
                continue
            
            # 尝试翻译该部分
            translated_part = self._match_term(part)
            translated_parts.append(translated_part)
        
        # 重新组合（中文之间不需要空格，英文和数字保留原样）
        result = "".join(translated_parts)
        
        # 如果翻译结果和原名一样且包含连字符/下划线，尝试直接对全名进行术语替换
        if result == text:
            sorted_terms = sorted(self.glossary.items(), key=lambda x: len(x[0]), reverse=True)
            for en_term, zh_term in sorted_terms:
                pattern = re.compile(re.escape(en_term), re.IGNORECASE)
                result = pattern.sub(zh_term, result)
        
        # 清理多余空格
        result = result.replace('_', ' ').strip()
        return result

    def _split_text(self, text: str) -> list:
        """将文本拆分为单词、数字和符号。支持CamelCase。"""
        import re
        # 匹配大写字母前的空隙进行拆分 (CamelCase)
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\\1 \\2', text)
        s2 = re.sub('([a-z0-9])([A-Z])', r'\\1 \\2', s1)
        # 替换下划线和连字符为空格
        s3 = s2.replace('_', ' ').replace('-', ' ')
        # 按空格拆分
        return s3.split()

    def _match_term(self, word: str) -> str:
        """在术语库中匹配单个单词，包含简单的单复数处理。"""
        import re
        
        word_lower = word.lower()
        
        # 1. 精确匹配（不区分大小写）
        for en_term, zh_term in self.glossary.items():
            if en_term.lower() == word_lower:
                return zh_term
        
        # 2. 简单的复数匹配 (如果 word 是单数，尝试在术语库找复数)
        # 例如: word='Clock', glossary has 'CLOCKS'
        plural_word = word_lower + 's'
        for en_term, zh_term in self.glossary.items():
            if en_term.lower() == plural_word:
                return zh_term
        
        # 3. 如果 word 以 's' 结尾，尝试找单数
        if word_lower.endswith('s') and len(word_lower) > 3:
            singular_word = word_lower[:-1]
            for en_term, zh_term in self.glossary.items():
                if en_term.lower() == singular_word:
                    return zh_term
        
        return word  # 没匹配到返回原词


class ModelDownloadWorker(BaseWorker):
    """
    Worker for downloading AI models (e.g., CLAP) from Hugging Face Mirror.
    """
    
    BASE_URL = "https://hf-mirror.com/Xenova/clap-htsat-unfused/resolve/main"
    
    # Files required for CLAP ONNX inference
    FILES_TO_DOWNLOAD = [
        "onnx/model.onnx",
        "tokenizer.json",
        "vocab.json",
        "config.json",
        "preprocessor_config.json",
        "special_tokens_map.json"
    ]
    
    def __init__(self, save_dir: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.save_dir = Path(save_dir)
    
    def run(self) -> None:
        try:
            import requests
            
            if not self.save_dir.exists():
                self.save_dir.mkdir(parents=True, exist_ok=True)
                
            total_files = len(self.FILES_TO_DOWNLOAD)
            
            # Calculate total size if possible or just count files
            # For better UX, we download sequentially
            
            for i, filename in enumerate(self.FILES_TO_DOWNLOAD):
                if self.is_cancelled:
                    return

                url = f"{self.BASE_URL}/{filename}"
                target_path = self.save_dir / filename
                
                # Ensure subdirectory exists (e.g. onnx/)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                self.progress.emit(0, 100, f"正在下载: {filename}...")
                
                try:
                    response = requests.get(url, stream=True, timeout=30)
                    response.raise_for_status()
                    
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded_size = 0
                    
                    with open(target_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if self.is_cancelled:
                                return
                            if chunk:
                                f.write(chunk)
                                downloaded_size += len(chunk)
                                if total_size > 0:
                                    percent = int((downloaded_size / total_size) * 100)
                                    # Update detailed progress for large files
                                    if "model.onnx" in filename: 
                                         self.progress.emit(percent, 100, f"正在下载模型主体 ({percent}%)...")
                    
                    logger.info(f"Downloaded {filename}")
                    
                except Exception as e:
                    logger.error(f"Failed to download {filename}: {e}")
                    self.error.emit(f"下载失败: {filename} - {str(e)}")
                    return
            
            self.finished.emit(str(self.save_dir))
            
        except Exception as e:
            logger.error(f"Download process error: {e}")
            self.error.emit(str(e))


class CLAPIndexingWorker(BaseWorker):
    """
    Worker for computing CLAP embeddings for a list of files.
    OPTIMIZED: Uses batch processing for better GPU utilization.
    """
    
    def __init__(self, engine, file_paths: list, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.engine = engine
        self.file_paths = file_paths
        
    def run(self) -> None:
        try:
            results = {} # {path: embedding}
            total = len(self.file_paths)
            
            # Disable Numba debug logging to avoid console spam
            import os
            os.environ['NUMBA_DISABLE_JIT'] = '0'  # Keep JIT enabled
            os.environ['NUMBA_DEBUG'] = '0'  # Disable debug output
            os.environ['NUMBA_DEBUGINFO'] = '0'
            
            # Show initialization progress
            self.progress.emit(0, total, "正在初始化 AI 模型...")
            
            # Ensure engine is ready
            if not self.engine.initialize():
                self.error.emit("CLAP 模型初始化失败，请在设置中检查模型是否下载")
                return
            
            # 从配置读取 batch_size
            from transcriptionist_v3.core.config import AppConfig
            batch_size = AppConfig.get("ai.batch_size", 4)
            logger.info(f"Using batch_size from config: {batch_size}")
            
            # First batch takes longer due to Numba JIT compilation
            self.progress.emit(0, total, "正在预热音频处理引擎（首次运行需要10-30秒）...")
            
            # Process in batches
            processed = 0
            for i in range(0, total, batch_size):
                if self.is_cancelled:
                    return
                
                batch_paths = self.file_paths[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (total + batch_size - 1) // batch_size
                
                # Update progress
                if i == 0:
                    self.progress.emit(i, total, f"正在编译音频处理函数（首次批次）...")
                else:
                    self.progress.emit(processed, total, f"正在批量处理 ({batch_num}/{total_batches}): {len(batch_paths)} 个文件...")
                
                try:
                    # Batch processing - much faster!
                    batch_results = self.engine.get_audio_embeddings_batch(batch_paths, batch_size=batch_size)
                    results.update(batch_results)
                    processed += len(batch_results)
                    
                except Exception as e:
                    logger.warning(f"Batch processing failed for batch {batch_num}: {e}")
                    # Fall back to individual processing for this batch
                    for path in batch_paths:
                        try:
                            embedding = self.engine.get_audio_embedding(str(path))
                            if embedding is not None:
                                results[str(path)] = embedding
                                processed += 1
                        except Exception as e2:
                            logger.warning(f"Failed to embed {path}: {e2}")
                    
            self.finished.emit(results)
            
        except Exception as e:
            logger.error(f"Indexing error: {e}")
            self.error.emit(str(e))


class TaggingWorker(BaseWorker):
    """
    Worker for AI tagging tasks.
    Runs tagging in background thread with progress reporting.
    """
    
    log_message = Signal(str)  # 日志消息信号
    batch_completed = Signal(list)  # 批次完成信号
    
    def __init__(
        self,
        engine,
        selected_files: list,
        audio_embeddings: dict,
        tag_embeddings: dict,
        tag_list: list,
        tag_matrix,
        tag_translations: dict,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.engine = engine
        self.selected_files = selected_files
        self.audio_embeddings = audio_embeddings
        self.tag_embeddings = tag_embeddings
        self.tag_list = tag_list
        self.tag_matrix = tag_matrix
        self.tag_translations = tag_translations
        
    def run(self) -> None:
        """Execute the tagging task."""
        import numpy as np
        from pathlib import Path
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import AudioFile, AudioFileTag
        
        BATCH_SIZE = 10  # 每批处理 10 个文件
        LOG_INTERVAL = 50  # 每 50 个文件更新一次日志
        UI_UPDATE_INTERVAL = 50  # 每 50 个文件刷新一次 UI
        
        processed = 0
        batch_updates = []
        total = len(self.selected_files)
        
        try:
            with session_scope() as session:
                for i, file_path_str in enumerate(self.selected_files):
                    if self.is_cancelled:
                        return
                    
                    path_obj = Path(file_path_str)
                    
                    # 1. Get Audio Embedding
                    key_str = str(path_obj)
                    embedding = self.audio_embeddings.get(key_str)
                    
                    if embedding is None:
                        # 如果没有 embedding，跳过
                        self.log_message.emit(f"❌ 跳过（无索引）: {path_obj.name}")
                        continue
                    
                    # 2. Vectorized Classification
                    norm_audio = np.linalg.norm(embedding)
                    if norm_audio > 0:
                        embedding_norm = embedding / norm_audio
                    else:
                        embedding_norm = embedding
                    
                    # Dot product (Cosine Similarity)
                    scores = np.dot(self.tag_matrix, embedding_norm)
                    
                    # Top K
                    top_k_indices = np.argsort(scores)[::-1][:3]
                    top_tags = [self.tag_list[idx] for idx in top_k_indices]
                    
                    # 3. Process Tags (LLM Translation)
                    final_tags = []
                    for tag_en in top_tags:
                        # Check cache
                        if tag_en in self.tag_translations:
                            final_tags.append(self.tag_translations[tag_en])
                            continue
                        
                        # Call LLM (同步，但在后台线程不阻塞 UI)
                        translated = self._translate_text_sync(tag_en, target_lang="zh")
                        if translated:
                            self.tag_translations[tag_en] = translated
                            final_tags.append(translated)
                        else:
                            final_tags.append(tag_en)  # Fallback
                    
                    # 4. Save to DB
                    db_file = session.query(AudioFile).filter_by(file_path=str(path_obj)).first()
                    if db_file:
                        session.query(AudioFileTag).filter_by(audio_file_id=db_file.id).delete()
                        for tag in final_tags:
                            new_tag = AudioFileTag(audio_file_id=db_file.id, tag=tag)
                            session.add(new_tag)
                        
                        # 记录待更新的文件
                        batch_updates.append({
                            'file_path': str(path_obj),
                            'tags': final_tags
                        })
                    
                    processed += 1
                    
                    # 5. 每 LOG_INTERVAL 个文件更新一次日志
                    if (i + 1) % LOG_INTERVAL == 0 or i == 0:
                        self.log_message.emit(f"已处理 {i+1}/{total} 个文件")
                    
                    # 6. 每 BATCH_SIZE 个文件提交一次数据库
                    if (i + 1) % BATCH_SIZE == 0 or (i + 1) == total:
                        # 批量提交到数据库
                        session.commit()
                        
                        # 7. 每 UI_UPDATE_INTERVAL 个文件发送一次批次信号
                        if (i + 1) % UI_UPDATE_INTERVAL == 0 or (i + 1) == total:
                            # 发送批量刷新信号
                            self.batch_completed.emit(batch_updates.copy())
                            self.log_message.emit(f"💾 已保存 {len(batch_updates)} 个文件的标签")
                            # 清空批次缓存
                            batch_updates.clear()
                    
                    # 8. 更新进度
                    self.progress.emit(i + 1, total, f"正在处理: {path_obj.name}")
                
                self.log_message.emit(f"\n🎉 任务完成！成功处理 {processed} 个文件。")
                self.finished.emit({'processed': processed, 'total': total})
                
        except Exception as e:
            logger.error(f"Tagging error: {e}", exc_info=True)
            self.error.emit(str(e))
    
    def _translate_text_sync(self, text: str, target_lang: str = "en") -> str:
        """Synchronously translate text"""
        from transcriptionist_v3.core.config import AppConfig
        from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService
        from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
        import asyncio
        
        api_key = AppConfig.get("ai.api_key", "").strip()
        if not api_key:
            return None
        
        model_idx = AppConfig.get("ai.model_index", 0)
        model_configs = {
            0: {"provider": "deepseek", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
            1: {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
            2: {"provider": "doubao", "model": "doubao-pro-4k", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
        }
        config = model_configs.get(model_idx, model_configs[0])
        
        if target_lang == "zh":
            sys_prompt = """你是一位专业的影视音效标签翻译专家。

### 任务
将以下英文音效标签翻译为简洁、通俗易懂的中文。

### 翻译原则
1. **口语化优先**：使用影视后期制作人员日常使用的说法，避免生硬的直译
2. **简洁明了**：优先使用2-4个字的简短词汇，让用户一眼就能看懂
3. **行业习惯**：遵循中文影视音效行业的常用术语

### 输出要求
仅输出翻译后的中文标签，不要包含任何标点符号、解释或额外说明。"""
        else:
            sys_prompt = "You are a translator. Translate the following Chinese audio description to English. Output ONLY the English translation."
        
        try:
            service_config = AIServiceConfig(
                provider_id=config["provider"],
                api_key=api_key,
                base_url=config["base_url"],
                model_name=config["model"],
                system_prompt=sys_prompt,
                timeout=10,
                max_tokens=64,
                temperature=0.3
            )
            service = OpenAICompatibleService(service_config)
            
            # Run sync
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(service.translate_single(text))
                if result.success:
                    translated_text = result.data.strip()
                    return translated_text
            finally:
                loop.close()
                asyncio.run(service.cleanup())
        except Exception as e:
            logger.error(f"Translation failed: {e}")
        
        return None


class MusicGenDownloadWorker(BaseWorker):
    """
    Worker for downloading MusicGen FP16 models.
    """
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
    
    def run(self) -> None:
        try:
            from transcriptionist_v3.application.ai_engine.musicgen.downloader import MusicGenDownloader
            downloader = MusicGenDownloader()
            
            def progress_cb(filename: str, current: int, total: int):
                if self.is_cancelled:
                    downloader.cancel()
                    return
                    
                msg = f"下载中: {filename}"
                if total > 0:
                    percent = int((current / total) * 100)
                    self.progress.emit(percent, 100, msg)
                else:
                    self.progress.emit(0, 0, msg)
                    
            try:
                downloader.download(progress_cb)
                
                if self.is_cancelled:
                    return
                    
                self.finished.emit(True)
                
            except Exception as e:
                if not self.is_cancelled:
                    logger.error(f"MusicGen download failed: {e}")
                    self.error.emit(str(e))
                
        except Exception as e:
            logger.error(f"Worker setup failed: {e}")
            self.error.emit(str(e))


class MusicGenGenerationWorker(BaseWorker):
    """
    Worker for generating audio using MusicGen.
    """
    
    def __init__(self, inference_engine, prompt: str, duration: int, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.engine = inference_engine
        self.prompt = prompt
        self.duration = duration
        
    def run(self) -> None:
        try:
            def callback(percent, msg):
                if self.is_cancelled:
                    raise InterruptedError("Generation cancelled")
                self.progress.emit(percent, 100, msg)
                
            # Execute generation
            # Returns: (sample_rate, audio_data_numpy)
            result = self.engine.generate(self.prompt, self.duration, callback=callback)
            
            if self.is_cancelled:
                return
                
            self.finished.emit(result)
            
        except Exception as e:
            if not self.is_cancelled:
                logger.error(f"Generation failed: {e}")
                self.error.emit(str(e))
