"""
Background worker utilities for Qt threading.
Provides base classes and helper functions for managing QThread workers.
"""

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional, Any, Callable

from PySide6.QtCore import QThread, QObject, Signal

logger = logging.getLogger(__name__)

# SQLite 单条 SQL 变量数上限约 999，IN 查询需分批
SQLITE_IN_BATCH = 500


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
    
    def __init__(
        self,
        paths_only: Optional[bool] = None,
        paths_only_threshold: int = 200000,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self._paths_only = paths_only
        self._paths_only_threshold = max(1, int(paths_only_threshold))
    
    def run(self) -> None:
        """Load audio files from database."""
        try:
            # 使用 session_scope 保证每个线程拥有自己独立、安全的 Session
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile, LibraryPath
            from transcriptionist_v3.domain.models.metadata import AudioMetadata
            from pathlib import Path
            from sqlalchemy.orm import joinedload
            
            results = []
            
            with session_scope() as session:
                total = session.query(AudioFile.id).count()
                if self._paths_only is None:
                    paths_only = total >= self._paths_only_threshold
                else:
                    paths_only = bool(self._paths_only)

                if paths_only:
                    # 只加载路径，用于构建文件夹树与懒加载
                    query = session.query(AudioFile.file_path).yield_per(2000)
                    for i, row in enumerate(query, start=1):
                        if self.is_cancelled:
                            return
                        results.append(Path(row.file_path))
                        if i % 2000 == 0 or i == total:
                            self.progress.emit(i, total, f"加载路径中 ({i}/{total})")
                else:
                    # Query all audio files with tags eagerly loaded
                    audio_files = (
                        session.query(AudioFile)
                        .options(joinedload(AudioFile.tags))
                        .all()
                    )
                    
                    if not audio_files:
                        logger.info("No audio files in database")
                        lib_paths = session.query(LibraryPath).filter_by(enabled=True).all()
                        root_paths = [Path(lp.path) for lp in lib_paths]
                        self.finished.emit({
                            "paths_only": paths_only,
                            "results": [],
                            "root_paths": root_paths,
                            "total": 0,
                        })
                        return
                    
                    total = len(audio_files)
                    
                    for i, db_file in enumerate(audio_files):
                        if self.is_cancelled:
                            return
                        
                        file_path = Path(db_file.file_path)
                        
                        metadata = AudioMetadata(
                            id=db_file.id,
                            duration=db_file.duration,
                            sample_rate=db_file.sample_rate,
                            bit_depth=db_file.bit_depth,
                            channels=db_file.channels,
                            format=db_file.format,
                            comment=getattr(db_file, 'description', '')
                        )
                        
                        metadata.original_filename = getattr(db_file, 'original_filename', file_path.name)
                        metadata.translated_name = getattr(db_file, 'translated_name', None)
                        metadata.tags = [t.tag for t in db_file.tags]
                        
                        results.append((file_path, metadata))
                        
                        if (i + 1) % 100 == 0 or i == total - 1:
                            self.progress.emit(i + 1, total, f"加载中 ({i+1}/{total})")
                
                # Fetch library paths (roots) at the end
                lib_paths = session.query(LibraryPath).filter_by(enabled=True).all()
                root_paths = [Path(lp.path) for lp in lib_paths]
            
            # 在 with 块外发射 finished，确保 Session 已正确关闭
            self.finished.emit({
                "paths_only": paths_only,
                "results": results,
                "root_paths": root_paths,
                "total": total,
            })
                
        except Exception as e:
            logger.error(f"Failed to load from database: {e}")
            self.error.emit(str(e))


def _build_translation_prompt(source_lang: str, target_lang: str, template_id: str) -> str:
    """构建翻译提示词（统一入口）。"""
    from transcriptionist_v3.application.ai_engine.providers.openai_compatible import (
        BASIC_TRANSLATION_PROMPT,
        EXPERT_UCS_PROMPT,
        LANGUAGE_ENFORCEMENT_TEMPLATES,
        TARGET_LANG_EXAMPLES,
    )

    # 语言映射（界面显示 -> AI 理解）
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
        "繁体中文": "Traditional Chinese",
    }

    source = lang_map.get(source_lang, "auto-detect")
    target = lang_map.get(target_lang, "Simplified Chinese")

    # 获取目标语言示例
    target_example = TARGET_LANG_EXAMPLES.get(target, "Translation")

    # 1. 填充源语言（自动检测时不写死）
    if source == "auto-detect":
        source_lang_text = ""  # 不指定，让 AI 自动检测
    else:
        source_lang_text = f"{source} "

    # 2. 填充语言强制指令
    language_enforcement = LANGUAGE_ENFORCEMENT_TEMPLATES.get(target, "")

    # 3. 选择并构建最终提示词
    if template_id == "ucs_standard":
        prompt = EXPERT_UCS_PROMPT
    else:
        prompt = BASIC_TRANSLATION_PROMPT

    # 4. 替换通用占位符
    prompt = prompt.replace("{{SOURCE_LANG}}", source_lang_text)
    prompt = prompt.replace("{{TARGET_LANG}}", target)
    prompt = prompt.replace("{{TARGET_LANG_EXAMPLE}}", target_example)
    prompt = prompt.replace("{{LANGUAGE_ENFORCEMENT}}", language_enforcement)

    return prompt

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
        
        # 本地模型时，即使没有 API Key 也可以尝试翻译
        # 其他模型需要 API Key
        is_local_model = (self.model_config.get("provider") == "local")
        if is_local_model or self.api_key:
            logger.info(f"Attempting AI translation (local={is_local_model}, api_key={'yes' if self.api_key else 'no'})...")
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
        """兼容旧接口：根据模板与语言构建提示词。"""
        template_id = "ucs_standard" if needs_ucs else self.template_id
        return _build_translation_prompt(self.source_lang, self.target_lang, template_id)

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
    Worker for downloading CLAP model (larger_clap_general) from Hugging Face Mirror.
    下载统一的 model.onnx （音频+文本编码器合一）及根目录 json/txt。
    """
    
    BASE_URL = "https://hf-mirror.com/Xenova/larger_clap_general/resolve/main"
    
    # larger_clap_general：根目录配置与 tokenizer + 统一的 model.onnx
    FILES_TO_DOWNLOAD = [
        "config.json",
        "merges.txt",
        "preprocessor_config.json",
        "quantize_config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "onnx/model.onnx",  # 统一模型（音频+文本编码器，783MB）
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
                                    if "model.onnx" in filename:
                                        # 统一模型下载进度
                                        self.progress.emit(percent, 100, f"正在下载 CLAP 模型 ({percent}%, {downloaded_size // 1024 // 1024}MB)...")
                    
                    logger.info(f"Downloaded {filename}")
                    
                except Exception as e:
                    logger.error(f"Failed to download {filename}: {e}")
                    self.error.emit(f"下载失败: {filename} - {str(e)}")
                    return
            
            self.finished.emit(str(self.save_dir))
            
        except Exception as e:
            logger.error(f"Download process error: {e}")
            self.error.emit(str(e))


class IndexLoadWorker(BaseWorker):
    """后台加载 AI 索引。若存在分片 manifest 则只加载 manifest（按需检索时再读分片）；否则加载单文件。"""
    def __init__(self, index_path: Path, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._index_path = Path(index_path)

    def run(self) -> None:
        import numpy as np
        try:
            index_dir = self._index_path.parent
            base_name = self._index_path.stem
            meta_path = index_dir / f"{base_name}_meta.npy"
            # 分片格式：只加载 manifest，不加载各分片（检索时按需加载）
            if meta_path.exists():
                self.progress.emit(0, 1, "正在加载索引信息...")
                data = np.load(str(meta_path), allow_pickle=True)
                meta = data.item() if data.ndim == 0 else {}
                if isinstance(meta, dict) and "chunk_files" in meta:
                    out = {
                        "_chunked": True,
                        "chunk_files": meta["chunk_files"],
                        "index_dir": str(index_dir),
                        "total_count": int(meta.get("total_count", 0)),
                    }
                    self.finished.emit(out)
                    return
            if not self._index_path.exists():
                self.finished.emit({})
                return
            self.progress.emit(0, 1, "正在加载 AI 索引...")
            data = np.load(str(self._index_path), allow_pickle=True)
            if data.ndim == 0:
                emb = data.item()
                if isinstance(emb, dict):
                    self.finished.emit(emb)
                else:
                    self.finished.emit({})
            else:
                self.finished.emit({})
        except Exception as e:
            logger.error(f"Index load error: {e}")
            self.error.emit(str(e))


# 索引分片：单文件超过此条数则拆成多文件 + manifest，便于按需加载与检索
INDEX_CHUNK_SIZE = 20000


class IndexSaveWorker(BaseWorker):
    """后台保存 AI 索引。超阈值时分片保存（manifest + 多文件）；支持 append 增量追加到分片索引。"""
    def __init__(self, index_path: Path, embeddings: dict, append: bool = False, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._index_path = Path(index_path)
        self._embeddings = embeddings
        self._append = append

    def run(self) -> None:
        import numpy as np
        try:
            n = len(self._embeddings)
            index_dir = self._index_path.parent
            base_name = self._index_path.stem
            meta_path = index_dir / f"{base_name}_meta.npy"
            # 增量追加到已有分片索引
            if self._append and meta_path.exists():
                data = np.load(str(meta_path), allow_pickle=True)
                meta = data.item() if data.ndim == 0 else {}
                chunk_files = list(meta.get("chunk_files", []))
                next_idx = len(chunk_files)
                chunk_path = index_dir / f"{base_name}_{next_idx}.npy"
                np.save(str(chunk_path), self._embeddings)
                chunk_files.append(chunk_path.name)
                meta["chunk_files"] = chunk_files
                meta["total_count"] = int(meta.get("total_count", 0)) + n
                np.save(str(meta_path), meta)
                self.finished.emit(None)
                return
            if n <= INDEX_CHUNK_SIZE:
                self.progress.emit(0, 1, f"正在保存索引 ({n} 条)...")
                np.save(str(self._index_path), self._embeddings)
                _remove_chunked_index_files(index_dir, base_name)
                self.finished.emit(None)
                return
            self.progress.emit(0, 1, f"正在分片保存索引 ({n} 条)...")
            items = list(self._embeddings.items())
            chunk_files = []
            for i in range(0, n, INDEX_CHUNK_SIZE):
                chunk = dict(items[i : i + INDEX_CHUNK_SIZE])
                chunk_path = index_dir / f"{base_name}_{len(chunk_files)}.npy"
                np.save(str(chunk_path), chunk)
                chunk_files.append(chunk_path.name)
                self.progress.emit(i + len(chunk), n, f"已保存 {min(i + INDEX_CHUNK_SIZE, n)}/{n} 条...")
            meta = {"version": 1, "chunk_files": chunk_files, "total_count": n}
            np.save(str(meta_path), meta)
            if self._index_path.exists():
                try:
                    self._index_path.unlink()
                except Exception:
                    pass
            self.finished.emit(None)
        except Exception as e:
            logger.error(f"Index save error: {e}")
            self.error.emit(str(e))


def _remove_chunked_index_files(index_dir: Path, base_name: str) -> None:
    """删除分片索引相关文件（manifest + 所有分片）。"""
    import numpy as np
    meta_path = index_dir / f"{base_name}_meta.npy"
    if meta_path.exists():
        try:
            data = np.load(str(meta_path), allow_pickle=True)
            meta = data.item() if data.ndim == 0 else {}
            for f in meta.get("chunk_files", []):
                p = index_dir / f
                if p.exists():
                    p.unlink()
            meta_path.unlink()
        except Exception:
            pass


class SearchWorker(BaseWorker):
    """后台计算语义检索相似度，支持万级/十万级条目不卡 UI。"""
    def __init__(
        self,
        text_embed,
        audio_embeddings: dict,
        only_selected: bool,
        selected_set: set,
        selection: Optional[dict] = None,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        from transcriptionist_v3.application.ai_jobs.selection import SelectionFilter
        self._text_embed = text_embed
        self._audio_embeddings = audio_embeddings
        self._only_selected = only_selected
        self._selected_set = selected_set
        self._selection_filter = SelectionFilter(selection) if selection else None

    def run(self) -> None:
        import numpy as np
        try:
            results = []
            norm_text = float(np.linalg.norm(self._text_embed))
            for path_key, audio_embed in self._audio_embeddings.items():
                if self.is_cancelled:
                    return
                path_str = str(path_key)
                if self._only_selected:
                    if self._selection_filter is not None:
                        if not self._selection_filter.matches(path_str):
                            continue
                    elif path_str not in self._selected_set:
                        continue
                norm_audio = np.linalg.norm(audio_embed)
                if norm_audio == 0 or norm_text == 0:
                    sim = 0.0
                else:
                    sim = float(np.dot(self._text_embed, audio_embed) / (norm_text * norm_audio))
                results.append((path_str, sim))
            results.sort(key=lambda x: x[1], reverse=True)
            self.finished.emit(results)
        except Exception as e:
            logger.error(f"Search error: {e}")
            self.error.emit(str(e))


class ChunkedSearchWorker(BaseWorker):
    """分片索引检索：按块加载、计算相似度、合并 top-k，避免几十万条一次性进内存。"""
    def __init__(
        self,
        index_dir: str,
        chunk_files: list,
        text_embed,
        only_selected: bool,
        selected_set: set,
        selection: Optional[dict] = None,
        top_per_chunk: int = 300,
        max_results: int = 500,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        from transcriptionist_v3.application.ai_jobs.selection import SelectionFilter
        self._index_dir = index_dir
        self._chunk_files = chunk_files
        self._text_embed = text_embed
        self._only_selected = only_selected
        self._selected_set = selected_set
        self._selection_filter = SelectionFilter(selection) if selection else None
        self._top_per_chunk = top_per_chunk
        self._max_results = max(1, int(max_results))

    def run(self) -> None:
        import numpy as np
        from pathlib import Path
        try:
            index_dir = Path(self._index_dir)
            norm_text = float(np.linalg.norm(self._text_embed))
            if norm_text == 0:
                self.finished.emit([])
                return
            merged = []
            for chunk_name in self._chunk_files:
                if self.is_cancelled:
                    return
                chunk_path = index_dir / chunk_name
                if not chunk_path.exists():
                    continue
                data = np.load(str(chunk_path), allow_pickle=True)
                chunk = data.item() if data.ndim == 0 else {}
                if not isinstance(chunk, dict):
                    continue
                chunk_results = []
                for path_key, audio_embed in chunk.items():
                    path_str = str(path_key)
                    if self._only_selected:
                        if self._selection_filter is not None:
                            if not self._selection_filter.matches(path_str):
                                continue
                        elif path_str not in self._selected_set:
                            continue
                    norm_audio = np.linalg.norm(audio_embed)
                    if norm_audio == 0:
                        sim = 0.0
                    else:
                        sim = float(np.dot(self._text_embed, audio_embed) / (norm_text * norm_audio))
                    chunk_results.append((path_str, sim))
                chunk_results.sort(key=lambda x: x[1], reverse=True)
                merged.extend(chunk_results[: self._top_per_chunk])
            # 同路径可能出现在多分片（增量重复），按路径取最大相似度后排序
            by_path = {}
            for path_str, sim in merged:
                if path_str not in by_path or sim > by_path[path_str]:
                    by_path[path_str] = sim
            merged = sorted(by_path.items(), key=lambda x: x[1], reverse=True)
            self.finished.emit(merged[: self._max_results])
        except Exception as e:
            logger.error(f"Chunked search error: {e}")
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
            total = len(self.file_paths)
            if total == 0:
                self.finished.emit({})
                return

            # Disable Numba debug logging to avoid控制台刷屏
            import os
            os.environ['NUMBA_DISABLE_JIT'] = '0'  # Keep JIT enabled
            os.environ['NUMBA_DEBUG'] = '0'
            os.environ['NUMBA_DEBUGINFO'] = '0'

            # 初始化模型
            self.progress.emit(0, total, "正在初始化 AI 模型...")
            if not self.engine.initialize():
                self.error.emit("CLAP 模型初始化失败，请在设置中检查模型是否下载")
                return

            # 从配置读取 batch_size（仅用于 GPU 批量推理，由引擎内部负责分批）
            from transcriptionist_v3.core.config import AppConfig
            batch_size = AppConfig.get("ai.batch_size", 4)
            logger.info(f"CLAPIndexingWorker: using GPU batch_size={batch_size} for {total} files")

            # 单次调用引擎的批量接口，让引擎内部统一负责：
            # 1) 多进程 CPU 预处理
            # 2) 按 batch_size 分批送入 GPU
            # 按块回调进度，避免长时间无更新导致“卡住”的错觉
            last_update_time = [0.0]  # 定义在 on_progress 前，闭包可正确引用
            def on_progress(progress_ratio: float, msg: str) -> None:
                """流式进度回调，progress_ratio 范围 0.0-1.0"""
                current_time = time.time()
                # 节流：最多每 100ms 更新一次，或最后一次更新（progress_ratio >= 1.0）
                if current_time - last_update_time[0] >= 0.1 or progress_ratio >= 1.0:
                    last_update_time[0] = current_time
                    percent = int(progress_ratio * 100)
                    self.progress.emit(percent, 100, msg)

            self.progress.emit(0, 100, "正在批量预处理与建立索引（首次可能需要 10–30 秒）...")
            start_time = time.time()
            results = self.engine.get_audio_embeddings_batch(
                self.file_paths,
                batch_size=batch_size,
                progress_callback=on_progress,
            )
            elapsed = time.time() - start_time

            processed = len(results)
            logger.info(f"CLAPIndexingWorker: finished embeddings for {processed}/{total} files in {elapsed:.1f}s")

            # 进度更新
            self.progress.emit(100, 100, f"索引完成：共 {processed} 条，耗时 {elapsed:.1f} 秒")
            self.finished.emit(results)

        except Exception as e:
            logger.error(f"Indexing error: {e}")
            self.error.emit(str(e))


class IndexingJobWorker(BaseWorker):
    """任务化索引构建：分批生成 embedding + 分片持久化 + 可断点恢复。"""
    def __init__(
        self,
        engine,
        selection: dict,
        index_dir: Path,
        model_version: str,
        batch_size: int = 2000,
        chunk_size: int = 2000,
        job_id: Optional[int] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.engine = engine
        self.selection = selection or {}
        self.index_dir = Path(index_dir)
        self.model_version = model_version or ""
        self.batch_size = max(1, int(batch_size))
        self.chunk_size = max(1, int(chunk_size))
        self.job_id = job_id

    def run(self) -> None:
        from sqlalchemy import or_
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import AudioFile, Job, IndexShard
        from transcriptionist_v3.core.config import AppConfig
        from transcriptionist_v3.application.ai_jobs.selection import apply_selection_filters
        from transcriptionist_v3.application.ai_jobs.index_writer import ChunkedIndexWriter
        from transcriptionist_v3.application.ai_jobs.job_constants import (
            JOB_TYPE_INDEX,
            JOB_STATUS_RUNNING,
            JOB_STATUS_PAUSED,
            JOB_STATUS_FAILED,
            JOB_STATUS_DONE,
            FILE_STATUS_DONE,
            FILE_STATUS_FAILED,
        )
        from transcriptionist_v3.application.ai_jobs.job_store import (
            create_job,
            start_job,
            update_job_progress,
            mark_job_paused,
            mark_job_failed,
            mark_job_done,
        )

        try:
            if not self.engine.initialize():
                self.error.emit("CLAP 模型初始化失败")
                return

            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job is None:
                    job = create_job(session, JOB_TYPE_INDEX, self.selection, params={"model_version": self.model_version})
                self.job_id = job.id

                base_query = session.query(AudioFile)
                base_query = apply_selection_filters(base_query, self.selection)
                base_query = base_query.filter(
                    or_(
                        AudioFile.index_status != FILE_STATUS_DONE,
                        AudioFile.index_version != self.model_version
                    )
                )
                try:
                    total = base_query.count()
                except Exception:
                    total = int(self.selection.get("count", 0) or 0)
                start_job(session, job, total=total)
                session.commit()

            writer = ChunkedIndexWriter(self.index_dir, base_name="clap_embeddings", chunk_size=self.chunk_size)
            processed = 0
            failed = 0
            last_id = 0

            while True:
                if self.is_cancelled:
                    with session_scope() as session:
                        job = session.get(Job, self.job_id)
                        if job:
                            job.checkpoint = {"last_id": last_id}
                            mark_job_paused(session, job)
                    return

                with session_scope() as session:
                    job = session.get(Job, self.job_id)
                    if job and job.checkpoint:
                        last_id = int(job.checkpoint.get("last_id", last_id) or last_id)

                    query = session.query(AudioFile)
                    query = apply_selection_filters(query, self.selection)
                    query = query.filter(AudioFile.id > last_id)
                    query = query.filter(
                        or_(
                            AudioFile.index_status != FILE_STATUS_DONE,
                            AudioFile.index_version != self.model_version
                        )
                    )
                    batch = query.order_by(AudioFile.id).limit(self.batch_size).all()

                if not batch:
                    break

                file_paths = [str(f.file_path) for f in batch]

                # 为索引任务接入 CLAP 内部的分阶段进度（预处理 / GPU 推理），避免长时间无反馈导致“卡死”错觉。
                # progress_ratio 为当前 batch 内 0.0–1.0 的进度，这里转换为全局文件数进度后通过 BaseWorker.progress 向 UI 汇报。
                batch_total = len(file_paths)
                def on_batch_progress(progress_ratio: float, msg: str) -> None:
                    try:
                        # 估算当前 batch 已完成的文件数，并折算到全局 processed/total
                        local_done = int(progress_ratio * batch_total)
                        current_global = processed + local_done
                        self.progress.emit(current_global, total, msg)
                    except Exception:
                        # 进度更新失败不影响主流程
                        pass

                results = self.engine.get_audio_embeddings_batch(
                    file_paths,
                    batch_size=AppConfig.get("ai.batch_size", 4),
                    progress_callback=on_batch_progress,
                )

                shard_path = writer.append(results)

                with session_scope() as session:
                    job = session.get(Job, self.job_id)
                    for f in batch:
                        path_str = str(f.file_path)
                        if path_str in results:
                            f.index_status = FILE_STATUS_DONE
                            f.index_version = self.model_version
                        else:
                            f.index_status = FILE_STATUS_FAILED
                            f.index_version = self.model_version
                            failed += 1
                    processed += len(batch)
                    last_id = batch[-1].id

                    if shard_path:
                        shard = IndexShard(
                            job_id=self.job_id,
                            shard_path=shard_path,
                            count=len(results),
                            start_id=batch[0].id,
                            end_id=batch[-1].id,
                            model_version=self.model_version,
                        )
                        session.add(shard)

                    if job:
                        update_job_progress(
                            session,
                            job,
                            processed=processed,
                            failed=failed,
                            checkpoint={"last_id": last_id},
                        )

                total = int(self.selection.get("count", 0) or 0)
                self.progress.emit(processed, total, f"已处理 {processed}")

            with session_scope() as session:
                job = session.get(Job, self.job_id)
                if job:
                    mark_job_done(session, job)

            self.finished.emit({"job_id": self.job_id, "processed": processed, "failed": failed})

        except Exception as e:
            logger.error(f"Indexing job error: {e}", exc_info=True)
            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job:
                    mark_job_failed(session, job, str(e))
            self.error.emit(str(e))


class ClearTagsJobWorker(BaseWorker):
    """任务化清理标签：分批删除标签并重置状态。"""
    def __init__(
        self,
        selection: dict,
        batch_size: int = 1000,
        job_id: Optional[int] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.selection = selection or {}
        self.batch_size = max(1, int(batch_size))
        self.job_id = job_id

    def run(self) -> None:
        from sqlalchemy import or_
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import AudioFile, AudioFileTag, Job
        from transcriptionist_v3.application.ai_jobs.selection import apply_selection_filters
        from transcriptionist_v3.application.ai_jobs.job_constants import (
            JOB_TYPE_CLEAR_TAGS,
            JOB_STATUS_PAUSED,
            JOB_STATUS_FAILED,
            JOB_STATUS_DONE,
        )
        from transcriptionist_v3.application.ai_jobs.job_store import (
            create_job,
            start_job,
            update_job_progress,
            mark_job_paused,
            mark_job_failed,
            mark_job_done,
        )

        try:
            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job is None:
                    job = create_job(session, JOB_TYPE_CLEAR_TAGS, self.selection, params=None)
                self.job_id = job.id

                base_query = session.query(AudioFile)
                base_query = apply_selection_filters(base_query, self.selection)
                try:
                    total = base_query.count()
                except Exception:
                    total = int(self.selection.get("count", 0) or 0)
                start_job(session, job, total=total)
                session.commit()

            processed = 0
            last_id = 0

            while True:
                if self.is_cancelled:
                    with session_scope() as session:
                        job = session.get(Job, self.job_id)
                        if job:
                            job.checkpoint = {"last_id": last_id}
                            mark_job_paused(session, job)
                    return

                with session_scope() as session:
                    job = session.get(Job, self.job_id)
                    if job and job.checkpoint:
                        last_id = int(job.checkpoint.get("last_id", last_id) or last_id)

                    query = session.query(AudioFile.id).order_by(AudioFile.id)
                    query = apply_selection_filters(query, self.selection)
                    query = query.filter(AudioFile.id > last_id)
                    ids = [row.id for row in query.limit(self.batch_size).all()]

                    if not ids:
                        break

                    session.query(AudioFileTag).filter(AudioFileTag.audio_file_id.in_(ids)).delete(synchronize_session=False)
                    session.query(AudioFile).filter(AudioFile.id.in_(ids)).update(
                        {"tag_status": 0, "tag_version": ""}, synchronize_session=False
                    )

                    processed += len(ids)
                    last_id = ids[-1]

                    if job:
                        update_job_progress(
                            session,
                            job,
                            processed=processed,
                            checkpoint={"last_id": last_id},
                        )

                total = int(self.selection.get("count", 0) or 0)
                self.progress.emit(processed, total, f"已处理 {processed}")

            with session_scope() as session:
                job = session.get(Job, self.job_id)
                if job:
                    mark_job_done(session, job)

            self.finished.emit({"job_id": self.job_id, "processed": processed})

        except Exception as e:
            logger.error(f"Clear tags job error: {e}", exc_info=True)
            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job:
                    mark_job_failed(session, job, str(e))
            self.error.emit(str(e))


class TranslateJobWorker(BaseWorker):
    """任务化翻译：按 selection 分批翻译文件名并写入数据库。"""
    def __init__(
        self,
        selection: dict,
        api_key: str,
        model_config: dict,
        template_id: str,
        source_lang: str,
        target_lang: str,
        batch_size: int = 200,
        job_id: Optional[int] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.selection = selection or {}
        self.api_key = api_key
        self.model_config = model_config or {}
        self.template_id = template_id or "translated_only"
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.batch_size = max(1, int(batch_size))
        self.job_id = job_id

    def run(self) -> None:
        import asyncio
        from pathlib import Path
        from transcriptionist_v3.core.config import AppConfig
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import AudioFile, Job
        from transcriptionist_v3.application.ai_jobs.selection import apply_selection_filters
        from transcriptionist_v3.application.ai_jobs.job_constants import (
            JOB_TYPE_TRANSLATE,
            FILE_STATUS_DONE,
            FILE_STATUS_FAILED,
        )
        from transcriptionist_v3.application.ai_jobs.job_store import (
            create_job,
            start_job,
            update_job_progress,
            mark_job_paused,
            mark_job_failed,
            mark_job_done,
        )
        from transcriptionist_v3.application.naming_manager.cleaning import CleaningManager
        from transcriptionist_v3.ui.utils.hierarchical_translate_worker import sanitize_filename
        from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
        from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService

        translation_model_type = AppConfig.get("ai.translation_model_type", "general")
        use_onnx = (translation_model_type == "hy_mt15_onnx")

        if use_onnx:
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
            required = ["model_fp16.onnx", "model_fp16.onnx_data", "model_fp16.onnx_data_1"]
            if not all((model_dir / f).exists() for f in required):
                logger.warning("HY-MT1.5 ONNX model not available, falling back to general model")
                use_onnx = False

        if not use_onnx and not self.api_key and self.model_config.get("provider") != "local":
            self.error.emit("未配置 API Key，无法进行翻译")
            return

        loop = None
        service = None

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            if use_onnx:
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
                prompt = _build_translation_prompt(self.source_lang, self.target_lang, self.template_id)
                service_config = AIServiceConfig(
                    provider_id=self.model_config.get("provider", ""),
                    api_key=self.api_key,
                    base_url=self.model_config.get("base_url", ""),
                    model_name=self.model_config.get("model", ""),
                    system_prompt=prompt,
                    timeout=180,
                    max_tokens=4096,
                    temperature=0.3,
                )
                service = OpenAICompatibleService(service_config)

            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job is None:
                    job = create_job(
                        session,
                        JOB_TYPE_TRANSLATE,
                        self.selection,
                        params={
                            "template_id": self.template_id,
                            "source_lang": self.source_lang,
                            "target_lang": self.target_lang,
                            "provider": self.model_config.get("provider", ""),
                        },
                    )
                self.job_id = job.id

                base_query = session.query(AudioFile)
                base_query = apply_selection_filters(base_query, self.selection)
                base_query = base_query.filter(AudioFile.translation_status != FILE_STATUS_DONE)
                try:
                    total = base_query.count()
                except Exception:
                    total = int(self.selection.get("count", 0) or 0)
                start_job(session, job, total=total)
                session.commit()

            cleaning_manager = CleaningManager.instance()
            processed = 0
            failed = 0
            last_id = 0

            while True:
                if self.is_cancelled:
                    with session_scope() as session:
                        job = session.get(Job, self.job_id)
                        if job:
                            job.checkpoint = {"last_id": last_id}
                            mark_job_paused(session, job)
                    return

                with session_scope() as session:
                    job = session.get(Job, self.job_id)
                    if job and job.checkpoint:
                        last_id = int(job.checkpoint.get("last_id", last_id) or last_id)

                    query = session.query(AudioFile.id, AudioFile.file_path, AudioFile.filename)
                    query = apply_selection_filters(query, self.selection)
                    query = query.filter(AudioFile.id > last_id)
                    query = query.filter(AudioFile.translation_status != FILE_STATUS_DONE)
                    batch = query.order_by(AudioFile.id).limit(self.batch_size).all()

                if not batch:
                    break

                cleaned_names = []
                meta_rows = []
                for row in batch:
                    path_obj = Path(row.file_path)
                    cleaned_stem = cleaning_manager.apply_all(path_obj.stem)
                    cleaned_names.append(cleaned_stem)
                    meta_rows.append((row.id, row.file_path, path_obj.suffix, path_obj.name))

                if not cleaned_names:
                    break

                result = loop.run_until_complete(
                    service.translate_batch(cleaned_names, self.source_lang, self.target_lang)
                )

                if not result.success:
                    raise RuntimeError(result.error or "翻译失败")

                translations = result.data or []
                batch_failed = 0

                with session_scope() as session:
                    for idx, row in enumerate(batch):
                        if idx >= len(translations):
                            batch_failed += 1
                            session.query(AudioFile).filter_by(id=row.id).update(
                                {"translation_status": FILE_STATUS_FAILED},
                                synchronize_session=False,
                            )
                            continue
                        translated = translations[idx].translated.strip() if translations[idx].translated else ""
                        suffix = meta_rows[idx][2] or ""
                        if translated.lower().endswith(suffix.lower()):
                            translated = translated[:-len(suffix)].strip()
                        translated = sanitize_filename(translated)
                        if not translated:
                            batch_failed += 1
                            session.query(AudioFile).filter_by(id=row.id).update(
                                {"translation_status": FILE_STATUS_FAILED},
                                synchronize_session=False,
                            )
                            continue
                        final_name = f"{translated}{suffix}"
                        session.query(AudioFile).filter_by(id=row.id).update(
                            {"translated_name": final_name, "translation_status": FILE_STATUS_DONE},
                            synchronize_session=False,
                        )

                    processed += len(batch)
                    failed += batch_failed
                    last_id = batch[-1].id

                    job = session.get(Job, self.job_id)
                    if job:
                        update_job_progress(
                            session,
                            job,
                            processed=processed,
                            failed=failed,
                            checkpoint={"last_id": last_id},
                        )

                total = int(self.selection.get("count", 0) or 0)
                self.progress.emit(processed, total, f"??? {processed}")

            with session_scope() as session:
                job = session.get(Job, self.job_id)
                if job:
                    mark_job_done(session, job)

            self.finished.emit({"job_id": self.job_id, "processed": processed, "failed": failed})

        except Exception as e:
            logger.error(f"Translate job error: {e}", exc_info=True)
            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job:
                    mark_job_failed(session, job, str(e))
            self.error.emit(str(e))
        finally:
            try:
                if service is not None and hasattr(service, "cleanup"):
                    loop.run_until_complete(service.cleanup())
            except Exception:
                pass
            try:
                if loop is not None:
                    loop.close()
            except Exception:
                pass


class ApplyTranslationJobWorker(BaseWorker):
    """任务化应用翻译结果：按 selection 分批重命名并写库。"""
    def __init__(
        self,
        selection: dict,
        batch_size: int = 200,
        job_id: Optional[int] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.selection = selection or {}
        self.batch_size = max(1, int(batch_size))
        self.job_id = job_id

    def run(self) -> None:
        from pathlib import Path
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import AudioFile, Job
        from transcriptionist_v3.application.ai_jobs.selection import apply_selection_filters
        from transcriptionist_v3.application.ai_jobs.job_constants import (
            JOB_TYPE_APPLY_TRANSLATION,
        )
        from transcriptionist_v3.application.ai_jobs.job_store import (
            create_job,
            start_job,
            update_job_progress,
            mark_job_paused,
            mark_job_failed,
            mark_job_done,
        )
        from transcriptionist_v3.application.library_manager.renaming_service import RenamingService

        try:
            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job is None:
                    job = create_job(session, JOB_TYPE_APPLY_TRANSLATION, self.selection, params=None)
                self.job_id = job.id

                base_query = session.query(AudioFile)
                base_query = apply_selection_filters(base_query, self.selection)
                base_query = base_query.filter(AudioFile.translated_name.isnot(None))
                try:
                    total = base_query.count()
                except Exception:
                    total = int(self.selection.get("count", 0) or 0)
                start_job(session, job, total=total)
                session.commit()

            processed = 0
            failed = 0
            last_id = 0

            while True:
                if self.is_cancelled:
                    with session_scope() as session:
                        job = session.get(Job, self.job_id)
                        if job:
                            job.checkpoint = {"last_id": last_id}
                            mark_job_paused(session, job)
                    return

                with session_scope() as session:
                    job = session.get(Job, self.job_id)
                    if job and job.checkpoint:
                        last_id = int(job.checkpoint.get("last_id", last_id) or last_id)

                    query = session.query(AudioFile.id, AudioFile.file_path, AudioFile.filename, AudioFile.translated_name)
                    query = apply_selection_filters(query, self.selection)
                    query = query.filter(AudioFile.id > last_id)
                    query = query.filter(AudioFile.translated_name.isnot(None))
                    rows = query.order_by(AudioFile.id).limit(self.batch_size).all()

                if not rows:
                    break

                for row in rows:
                    if self.is_cancelled:
                        break
                    old_path = Path(row.file_path)
                    new_name = (row.translated_name or "").strip()
                    if not new_name:
                        failed += 1
                        last_id = row.id
                        continue
                    if new_name == row.filename:
                        processed += 1
                        last_id = row.id
                        continue
                    try:
                        success, _, _ = RenamingService.rename_sync(str(old_path), new_name)
                        if success:
                            processed += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
                    last_id = row.id

                with session_scope() as session:
                    job = session.get(Job, self.job_id)
                    if job:
                        update_job_progress(
                            session,
                            job,
                            processed=processed,
                            failed=failed,
                            checkpoint={"last_id": last_id},
                        )

                total = int(self.selection.get("count", 0) or 0)
                self.progress.emit(processed, total, f"已应用 {processed}")

            with session_scope() as session:
                job = session.get(Job, self.job_id)
                if job:
                    mark_job_done(session, job)

            self.finished.emit({"job_id": self.job_id, "processed": processed, "failed": failed})

        except Exception as e:
            logger.error(f"Apply translation job error: {e}", exc_info=True)
            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job:
                    mark_job_failed(session, job, str(e))
            self.error.emit(str(e))

class TaggingJobWorker(BaseWorker):
    """
    任务化 AI 打标：基于分片索引逐块处理，支持断点与选择规则。
    """
    log_message = Signal(str)
    batch_completed = Signal(list)

    def __init__(
        self,
        engine,
        selection: dict,
        chunked_index: Optional[dict],
        audio_embeddings: Optional[dict],
        tag_list: list,
        tag_matrix,
        tag_translations: dict,
        min_confidence: float = 0.35,
        tag_version: str = "",
        job_id: Optional[int] = None,
        parent: Optional[QObject] = None
    ):
        super().__init__(parent)
        self.engine = engine
        self.selection = selection or {}
        self.chunked_index = chunked_index
        self.audio_embeddings = audio_embeddings or {}
        self.tag_list = tag_list
        self.tag_matrix = tag_matrix
        self.tag_translations = tag_translations
        self.min_confidence = min_confidence
        self.tag_version = tag_version
        self.job_id = job_id

    def run(self) -> None:
        import numpy as np
        from pathlib import Path
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import AudioFile, AudioFileTag, Job
        from transcriptionist_v3.application.ai_jobs.selection import SelectionFilter, normalize_path
        from transcriptionist_v3.application.ai_jobs.job_constants import (
            JOB_TYPE_TAG,
            FILE_STATUS_DONE,
            FILE_STATUS_FAILED,
        )
        from transcriptionist_v3.application.ai_jobs.job_store import (
            create_job,
            start_job,
            update_job_progress,
            mark_job_paused,
            mark_job_failed,
            mark_job_done,
        )

        try:
            if not self.engine:
                self.error.emit("CLAP 引擎未初始化")
                return

            selection_filter = SelectionFilter(self.selection)

            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job is None:
                    job = create_job(session, JOB_TYPE_TAG, self.selection, params={"tag_version": self.tag_version})
                self.job_id = job.id
                total = int(self.selection.get("count", 0) or 0)
                start_job(session, job, total=total)
                session.commit()

            processed = 0
            failed = 0
            total_count = int(self.selection.get("count", 0) or 0)
            last_logged_at = [0]  # 每 200 个文件向实时分析发一次日志

            def process_chunk(chunk: dict, batch_updates: list) -> None:
                nonlocal processed, failed
                if not chunk:
                    return

                # 先按 selection 过滤；numpy 加载的 key 可能是 np.str_，统一转成 str 避免 DB 查询不匹配
                filtered = {}
                for path_str, emb in chunk.items():
                    path_str = str(path_str).strip()
                    if not path_str or not selection_filter.matches(path_str):
                        continue
                    filtered[path_str] = emb
                if not filtered:
                    return

                # 查询 DB 获取 id 与状态（索引与 DB 可能一种用 / 一种用 \，两种形式都查；分批避免 too many SQL variables）
                raw_paths = list(filtered.keys())
                normalized_map = {normalize_path(p): p for p in raw_paths}
                query_paths = set(raw_paths)
                for p in raw_paths:
                    query_paths.add(p.replace("\\", "/"))
                    query_paths.add(p.replace("/", "\\"))
                query_path_list = list(query_paths)

                with session_scope() as session:
                    id_map = {}
                    for i in range(0, len(query_path_list), SQLITE_IN_BATCH):
                        batch = query_path_list[i : i + SQLITE_IN_BATCH]
                        rows = (
                            session.query(AudioFile.id, AudioFile.file_path, AudioFile.tag_status, AudioFile.tag_version)
                            .filter(AudioFile.file_path.in_(batch))
                            .all()
                        )
                        for row in rows:
                            id_map[normalize_path(row.file_path)] = row

                    # 第一遍：收集本 chunk 内所有 (row, top_tags)，以及需要翻译的标签集合（走「设置 -> AI 批量翻译性能」的批次与并发）
                    pending: list = []
                    unique_to_translate: set = set()
                    for norm_path, raw_path in normalized_map.items():
                        row = id_map.get(norm_path)
                        if not row:
                            continue
                        if row.tag_status == FILE_STATUS_DONE and row.tag_version == self.tag_version:
                            continue
                        embedding = filtered.get(raw_path)
                        if embedding is None:
                            failed += 1
                            continue
                        norm_audio = np.linalg.norm(embedding)
                        embedding_norm = embedding / norm_audio if norm_audio > 0 else embedding
                        scores = np.dot(self.tag_matrix, embedding_norm)
                        above = np.where(scores >= self.min_confidence)[0]
                        order = np.argsort(scores[above])[::-1] if len(above) else np.array([], dtype=int)
                        top_indices = above[order][:10]
                        top_tags = [self.tag_list[idx] for idx in top_indices]
                        for tag_en in top_tags:
                            cached = self.tag_translations.get(tag_en)
                            # 检测无效缓存：如果缓存的翻译 == 原文，说明之前失败，需要重新翻译
                            if cached is None or cached == tag_en:
                                if cached == tag_en:
                                    del self.tag_translations[tag_en]  # 清除无效缓存
                                unique_to_translate.add(tag_en)
                        pending.append((row, top_tags))

                    # 批量翻译本 chunk 缺失的标签（使用设置中的批次与并发、当前选中的模型）
                    if unique_to_translate:
                        batch_result = self._translate_tags_batch_sync(list(unique_to_translate))
                        for k, v in batch_result.items():
                            if v and v != k:
                                self.tag_translations[k] = v

                    # 第二遍：写库并更新进度
                    for row, top_tags in pending:
                        final_tags = [
                            self.tag_translations.get(tag_en, tag_en) for tag_en in top_tags
                        ]
                        session.query(AudioFileTag).filter_by(audio_file_id=row.id).delete()
                        for tag in final_tags:
                            session.add(AudioFileTag(audio_file_id=row.id, tag=tag))
                        session.query(AudioFile).filter_by(id=row.id).update(
                            {"tag_status": FILE_STATUS_DONE, "tag_version": self.tag_version},
                            synchronize_session=False
                        )
                        batch_updates.append({"file_path": row.file_path, "tags": final_tags})
                        processed += 1
                        if total_count > 0 and processed - last_logged_at[0] >= 200:
                            last_logged_at[0] = processed
                            self.log_message.emit(f"已处理 {processed}/{total_count} 个文件…")
                            self.progress.emit(processed, total_count, f"正在打标… {processed}/{total_count}")
                            if batch_updates:
                                self.batch_completed.emit(batch_updates.copy())

                    session.commit()

            if self.chunked_index and self.chunked_index.get("_chunked"):
                index_dir = Path(self.chunked_index.get("index_dir", ""))
                chunk_files = self.chunked_index.get("chunk_files", [])
                self.log_message.emit(f"开始打标，共 {total_count} 个文件（每 200 个更新一次实时分析）")
                for chunk_name in chunk_files:
                    if self.is_cancelled:
                        with session_scope() as session:
                            job = session.get(Job, self.job_id)
                            if job:
                                mark_job_paused(session, job)
                        return
                    chunk_path = index_dir / chunk_name
                    if not chunk_path.exists():
                        continue
                    data = np.load(str(chunk_path), allow_pickle=True)
                    chunk = data.item() if data.ndim == 0 else {}
                    batch_updates: list = []
                    process_chunk(chunk, batch_updates)
                    if batch_updates:
                        self.batch_completed.emit(batch_updates)
                        self.log_message.emit(f"已更新 {len(batch_updates)} 个文件的标签")
                    # 每 200 个文件向实时分析页发一次进度，避免“卡住”错觉
                    if total_count > 0 and processed - last_logged_at[0] >= 200:
                        last_logged_at[0] = processed
                        self.log_message.emit(f"已处理 {processed}/{total_count} 个文件…")
                    self.progress.emit(processed, total_count, f"正在打标… {processed}/{total_count}")
            else:
                # 非分片索引：小规模直接处理
                self.log_message.emit(f"开始打标，共 {total_count} 个文件")
                batch_updates: list = []
                process_chunk(self.audio_embeddings, batch_updates)
                if batch_updates:
                    self.batch_completed.emit(batch_updates)
                self.progress.emit(processed, total_count, f"已处理 {processed}/{total_count}")

            with session_scope() as session:
                job = session.get(Job, self.job_id)
                if job:
                    mark_job_done(session, job)

            if processed == 0 and total_count > 0:
                self.log_message.emit(
                    "⚠️ 打标成功 0 项。可能原因：① 索引中的路径与当前音效库路径不一致（请先重新「建立索引」）；② 所有文件已用当前标签集打标过。"
                )
            self.log_message.emit(f"✅ 打标完成：成功 {processed} 项")
            self.finished.emit({"job_id": self.job_id, "processed": processed, "failed": failed})

        except Exception as e:
            logger.error(f"Tagging job error: {e}", exc_info=True)
            with session_scope() as session:
                job = session.get(Job, self.job_id) if self.job_id else None
                if job:
                    mark_job_failed(session, job, str(e))
            self.error.emit(str(e))

    def _get_tag_translation_system_prompt(self) -> str:
        """影视音效行业专用提示：批量标签翻译，返回 JSON 格式。"""
        return """你是一位专业的影视音效标签翻译专家。

### 任务
将给定的英文音效标签列表翻译为极短的中文标签（2~6 个字），用于影视/游戏音效分类。

### 翻译规则
1. 每个标签翻译为 2~6 个汉字的短词组
2. 若英文有多义，只取与声音、乐器、动作声、环境声相关的含义
3. 不要输出解释、科普或完整句子

### 输出格式
必须返回 JSON 对象：{"translations": [{"original": "英文", "translated": "中文"}, ...]}

### 示例
输入: ["Truck", "Rain"]
输出: {"translations": [{"original": "Truck", "translated": "卡车声"}, {"original": "Rain", "translated": "雨声"}]}"""

    def _translate_tags_batch_sync(self, tags: list) -> dict:
        """
        批量翻译标签，走「设置 -> AI 批量翻译性能」的批次与并发。
        使用「设置 -> AI 服务商配置」选中的模型（含本地 Ollama/LM Studio），非 DeepSeek 硬编码。
        返回 { 英文标签: 中文翻译 }，未翻出的保留英文。
        """
        if not tags:
            return {}
        from transcriptionist_v3.application.ai_engine.translation_manager import (
            get_translation_config_from_app,
            TranslationManager,
        )
        import asyncio

        sys_prompt = self._get_tag_translation_system_prompt()
        config, err = get_translation_config_from_app(system_prompt=sys_prompt)
        if err or not config:
            return {t: t for t in tags}

        # 批量翻译标签时需要足够的输出空间：
        # - 每个标签的 JSON 对象约 {"original": "xxx", "translated": "yyy"} ≈ 50 字符 ≈ 15 tokens
        # - 40 个标签 ≈ 600 tokens，加上 JSON 结构开销，至少需要 1000+ tokens
        # - 设置 2048 确保不会被截断导致 JSON 解析失败
        config.max_tokens = 2048
        config.temperature = 0.2

        if not TranslationManager.instance().configure(config):
            return {t: t for t in tags}

        async def _run():
            result = await TranslationManager.instance().translate_batch(
                list(tags), use_cache=True, progress_callback=None
            )
            if not result.success or not result.data:
                return {t: t for t in tags}
            out = {}
            for r in result.data:
                orig = getattr(r, "original", None)
                raw = getattr(r, "translated", None)
                if orig is None:
                    continue
                tr = (str(raw or "").strip().split("\n")[0].strip().strip("。，、；："))[:12] if raw else ""
                out[orig] = tr if tr else orig
            return out

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_run())
        except Exception as e:
            logger.debug(f"Tag batch translate error: {e}")
            return {t: t for t in tags}
        finally:
            try:
                loop.close()
            except Exception:
                pass

    def _translate_text_sync(self, text: str, target_lang: str = "en") -> str:
        """影视音效场景：单条英文标签 → 简短中文。配置来自「设置 -> AI 服务商」，支持本地 Ollama/LM Studio。"""
        from transcriptionist_v3.application.ai_engine.translation_manager import get_translation_config_from_app
        from transcriptionist_v3.application.ai_engine.service_factory import AIServiceFactory
        import asyncio

        sys_prompt = self._get_tag_translation_system_prompt()
        config, err = get_translation_config_from_app(system_prompt=sys_prompt)
        if err or not config:
            return text
        config.max_tokens = 32
        config.temperature = 0.2

        service = AIServiceFactory.create_service(config)
        if not service or not hasattr(service, "translate_single"):
            return text

        async def _run():
            res = await service.translate_single(text)
            if res and getattr(res, "success", False) and getattr(res, "data", None):
                return str(res.data).strip()
            return ""

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_run())
        finally:
            try:
                if hasattr(service, "cleanup"):
                    loop.run_until_complete(service.cleanup())
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass

        if not result:
            return text
        first_line = result.split("\n")[0].strip().strip("。，、；：")
        if len(first_line) > 12:
            first_line = first_line[:12]
        return first_line if first_line else text


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
        min_confidence: float = 0.35,
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
        self.min_confidence = min_confidence
        
    def run(self) -> None:
        """Execute the tagging task."""
        import numpy as np
        from pathlib import Path
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import AudioFile, AudioFileTag
        
        DB_COMMIT_BATCH = 500  # 每 500 条提交一次数据库，避免几十万条时事务过多/卡死
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
                    # CRITICAL: embedding应该已经在clap_service中归一化，这里再次确保
                    norm_audio = np.linalg.norm(embedding)
                    if norm_audio > 0:
                        embedding_norm = embedding / norm_audio
                    else:
                        embedding_norm = embedding
                    
                    # Dot product (Cosine Similarity)
                    # tag_matrix中的每个标签embedding也应该已归一化
                    scores = np.dot(self.tag_matrix, embedding_norm)
                    
                    # 只保留相似度 ≥ 阈值的标签，不强制打满几个（打标是为了方便定位，不为打而打）
                    above = np.where(scores >= self.min_confidence)[0]
                    
                    # DEBUG: 记录相似度分布，帮助用户调整阈值
                    if len(above) == 0 and (i + 1) % 100 == 0:
                        max_score = np.max(scores) if len(scores) > 0 else 0.0
                        self.log_message.emit(f"⚠️ 文件 {path_obj.name} 无达标标签（最高相似度: {max_score:.3f}，阈值: {self.min_confidence:.3f}）")
                    
                    order = np.argsort(scores[above])[::-1] if len(above) else np.array([], dtype=int)
                    top_indices = above[order]  # 按分数从高到低，个数不定
                    
                    # 限制最多返回前10个标签，避免标签过多
                    top_indices = top_indices[:10]
                    top_tags = [self.tag_list[idx] for idx in top_indices]
                    
                    # 3. Process Tags (LLM Translation)，无达标标签则 final_tags 为空
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
                    
                    # 4. Save to DB（用 DB 中存储的 file_path 作为 key，确保与 _file_metadata 一致）
                    path_str = str(path_obj)
                    db_file = session.query(AudioFile).filter_by(file_path=path_str).first()
                    if not db_file and path_str != path_obj.as_posix():
                        db_file = session.query(AudioFile).filter_by(file_path=path_obj.as_posix()).first()
                    if db_file:
                        session.query(AudioFileTag).filter_by(audio_file_id=db_file.id).delete()
                        for tag in final_tags:
                            new_tag = AudioFileTag(audio_file_id=db_file.id, tag=tag)
                            session.add(new_tag)
                        # 使用 DB 中的 file_path，保证库页 _file_metadata 能匹配到
                        batch_updates.append({
                            'file_path': db_file.file_path,
                            'tags': final_tags
                        })
                    
                    processed += 1
                    
                    # 5. 每 LOG_INTERVAL 个文件更新一次日志
                    if (i + 1) % LOG_INTERVAL == 0 or i == 0:
                        self.log_message.emit(f"已处理 {i+1}/{total} 个文件")
                    
                    # 6. 每 DB_COMMIT_BATCH 条提交一次数据库，避免几十万条时大事务卡死
                    if (i + 1) % DB_COMMIT_BATCH == 0 or (i + 1) == total:
                        session.commit()
                        
                        # 7. 每 UI_UPDATE_INTERVAL 个文件发送一次批次信号
                        if (i + 1) % UI_UPDATE_INTERVAL == 0 or (i + 1) == total:
                            # 发送批量刷新信号
                            self.batch_completed.emit(batch_updates.copy())
                            self.log_message.emit(f"💾 已保存 {len(batch_updates)} 个文件的标签")
                            # 清空批次缓存
                            batch_updates.clear()
                    
                    # 8. 更新进度（节流：每 100 个文件或首/尾才 emit，避免十万级时信号过多卡 UI）
                    if (i + 1) % 100 == 0 or i == 0 or (i + 1) == total:
                        self.progress.emit(i + 1, total, f"正在处理: {path_obj.name}")
                
                # 在 session 外再 emit finished，确保主线程 refresh 时一定能读到已提交的数据
                result = {'processed': processed, 'total': total}
            
            self.log_message.emit(f"\n🎉 任务完成！成功处理 {processed} 个文件。")
            self.finished.emit(result)
                
        except Exception as e:
            logger.error(f"Tagging error: {e}", exc_info=True)
            self.error.emit(str(e))
    
    def _translate_text_sync(self, text: str, target_lang: str = "en") -> str:
        """Synchronously translate text"""
        from transcriptionist_v3.core.config import AppConfig
        from transcriptionist_v3.application.ai_engine.providers.openai_compatible import OpenAICompatibleService
        from transcriptionist_v3.application.ai_engine.base import AIServiceConfig
        import asyncio

        # 优先使用 HY-MT1.5 ONNX（如果用户开启且模型已下载）- 已注释（模型加载慢且翻译质量不稳定）
        # try:
        #     translation_model_type = AppConfig.get("ai.translation_model_type", "general")
        #     if translation_model_type == "hy_mt15_onnx":
        #         from transcriptionist_v3.runtime.runtime_config import get_data_dir
        #         model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
        #         required = ["model_fp16.onnx", "model_fp16.onnx_data", "model_fp16.onnx_data_1"]
        #         has_model = all((model_dir / f).exists() for f in required) and (
        #             (model_dir / "tokenizer.json").exists() or (model_dir / "tokenizer_config.json").exists()
        #         )
        #         if has_model:
        #             from transcriptionist_v3.application.ai_engine.providers.hy_mt15_onnx import HyMT15OnnxService
        #             cfg = AIServiceConfig(provider_id="hy_mt15_onnx", model_name="hy-mt1.5-onnx")
        #             svc = HyMT15OnnxService(cfg)
        #             loop = asyncio.new_event_loop()
        #             asyncio.set_event_loop(loop)
        #             try:
        #                 loop.run_until_complete(svc.initialize())
        #                 # 这里的 source_lang/target_lang 只是方向提示；HY-MT 实际可能根据前缀决定
        #                 src = "en" if target_lang == "zh" else "zh"
        #                 r = loop.run_until_complete(svc.translate(text, source_lang=src, target_lang=target_lang))
        #                 if r and r.success and r.data:
        #                     return r.data.translated.strip()
        #             finally:
        #                 try:
        #                     loop.run_until_complete(svc.cleanup())
        #                 except Exception:
        #                     pass
        #                 loop.close()
        # except Exception as e:
        #     logger.debug(f"HY-MT1.5 ONNX translate failed, fallback to general: {e}")
        
        api_key = AppConfig.get("ai.api_key", "").strip()
        if not api_key:
            return None
        
        model_idx = AppConfig.get("ai.model_index", 0)
        model_configs = {
            0: {"provider": "deepseek", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
            1: {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
            2: {"provider": "doubao", "model": "doubao-pro-4k", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
            3: {  # 本地模型
                "provider": "local",
                "model": AppConfig.get("ai.local_model_name", ""),
                "base_url": AppConfig.get("ai.local_base_url", "http://localhost:1234/v1"),
            },
        }
        config = model_configs.get(model_idx, model_configs[0])
        
        # 本地模型时，API Key 可以为空
        if model_idx == 3:
            api_key = ""  # 本地模型通常不需要 API Key
        else:
            api_key = AppConfig.get("ai.api_key", "").strip()
            if not api_key:
                return None
        
        if target_lang == "zh":
            sys_prompt = """你是一位专业的影视音效标签翻译专家。

### 任务
将给定的**英文音效标签短语**翻译为**简短、符合中文阅读习惯的中文标签**。

### 说明
这些标签可能来自影视音效行业的专业术语与命名规范（如 UCS 等），请按行业惯例译为更符合中文阅读与使用习惯的表述：简洁、口语化、符合影视后期/声音设计常用说法，避免生硬直译或生僻书面语。

### 翻译原则
1. **极度简洁**：优先使用 2~4 个字的短词，例如「爆炸」「关门」「玻璃碎」「汽车发动」。
2. **不要脑补**：只翻译标签字面含义，不要加入场景、情绪或句子，例如不要翻成「紧张的爆炸场景」。
3. **行业习惯**：使用影视后期/声音设计常见说法，避免生僻书面语。

### 输出要求
只输出一个中文词组，不要加标点、解释、编号或任何额外内容。"""
        else:
            # CLAP 模型期望自然语言描述格式，如 "The sound of X" 或 "A sound of X"
            sys_prompt = """You are a professional audio description translator for CLAP model queries.

### Task
Translate the Chinese audio description into a natural English sentence that describes the sound.

### Format Requirements
- Use "The sound of..." or "A sound of..." format
- Write a complete, natural English sentence (not just keywords)
- Be specific and descriptive

### Examples
- 重击声 → The sound of a heavy impact
- 脚步声 → The sound of footsteps walking
- 玻璃破碎 → The sound of glass shattering
- 关门声 → The sound of a door closing
- 狗叫 → The sound of a dog barking
- 雨声 → The sound of rain falling
- 爆炸 → The sound of an explosion
- 汽车引擎 → The sound of a car engine running

### Output
Only output the English sentence, nothing else."""
        
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


class HyMT15DownloadWorker(BaseWorker):
    """
    Worker for downloading HY-MT1.5 ONNX translation model.
    Downloads from ModelScope (魔塔社区).
    """
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
    
    def run(self) -> None:
        """Download HY-MT1.5 ONNX model files"""
        try:
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            from pathlib import Path
            import requests
            import hashlib
            import os
            
            model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
            model_dir.mkdir(parents=True, exist_ok=True)
            
            # 模型文件列表（从魔塔社区）
            # 注意：这里需要根据实际的魔塔社区 API 调整
            # 仅下载必要文件（不要全仓库下载）
            # 文件列表参考：`https://modelscope.cn/models/onnx-community/HY-MT1.5-1.8B-ONNX/files`
            # 说明：
            # - 三个模型文件：model_fp16.onnx + 两个外部 data 分片（必须）
            # - tokenizer.json + tokenizer_config.json（必须）
            # - config.json / configuration.json（小文件，建议一并下载，便于后续读取配置）
            repo_base = "https://modelscope.cn/api/v1/models/onnx-community/HY-MT1.5-1.8B-ONNX/repo?Revision=master&FilePath="
            # 说明：
            # - 之前这里对外部 data 分片使用了「硬编码文件大小」做严格校验，
            #   但 ModelScope 后续更新后实际大小发生变化，导致本地下载成功却被误判为失败。
            # - 为了兼容后续模型更新，这里不再对精确字节数做强校验，只要下载成功且文件非空即可。
            files_to_get = [
                ("model_fp16.onnx", None),         # 主模型，可选做轻量校验
                ("model_fp16.onnx_data", None),    # 大分片，不做固定大小校验
                ("model_fp16.onnx_data_1", None),  # 大分片，不做固定大小校验
                ("tokenizer.json", None),
                ("tokenizer_config.json", None),
                ("config.json", None),
                ("configuration.json", None),
            ]

            def build_candidates(file_path: str) -> list[str]:
                # 有些仓库会把文件放在 onnx/ 子目录中；做双路径兼容
                if file_path.startswith("onnx/"):
                    return [file_path]
                return [file_path, f"onnx/{file_path}"]

            model_files = []
            for fname, fsize in files_to_get:
                # 默认按根目录文件拼 URL；下载时如果 404 会自动尝试 onnx/ 前缀
                model_files.append(
                    {
                        "name": fname,
                        "candidates": build_candidates(fname),
                        "size": fsize,
                        "hash": None,  # TODO: 可在后续加 SHA256
                    }
                )
            
            total_files = len(model_files)
            downloaded = 0
            
            for file_info in model_files:
                if self.is_cancelled:
                    return
                
                file_path = model_dir / file_info["name"]
                
                # 检查文件是否已存在
                if file_path.exists():
                    # 检查文件大小
                    if file_info["size"] and file_path.stat().st_size == file_info["size"]:
                        logger.info(f"File already exists: {file_info['name']}")
                        downloaded += 1
                        self.progress.emit(downloaded, total_files, f"已存在: {file_info['name']}")
                        continue
                
                # 下载文件
                self.progress.emit(downloaded, total_files, f"下载中: {file_info['name']}")
                
                try:
                    # 逐个候选路径尝试下载（根目录 / onnx/）
                    response = None
                    last_err = None
                    for cand in file_info.get("candidates", [file_info["name"]]):
                        url = repo_base + cand
                        try:
                            resp = requests.get(url, stream=True, timeout=30)
                            if resp.status_code == 404:
                                last_err = f"404 Not Found: {cand}"
                                continue
                            resp.raise_for_status()
                            response = resp
                            break
                        except Exception as e:
                            last_err = str(e)
                            continue
                    if response is None:
                        raise RuntimeError(last_err or "下载失败：未找到文件")
                    
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded_size = 0
                    
                    with open(file_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if self.is_cancelled:
                                file_path.unlink(missing_ok=True)
                                return
                            
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            
                            # 实时更新进度（按字节流动，而不是按文件个数跳变）
                            if total_size > 0:
                                file_percent = int((downloaded_size / total_size) * 100)
                                overall_current = downloaded * 100 + file_percent
                                overall_total = total_files * 100
                                self.progress.emit(
                                    overall_current,
                                    overall_total,
                                    f"下载中: {file_info['name']} ({file_percent}%)"
                                )
                            else:
                                # 如果无法获取总大小，只显示当前文件名称
                                self.progress.emit(
                                    downloaded,
                                    total_files,
                                    f"下载中: {file_info['name']}"
                                )
                    
                    # 可选：如果将来提供哈希值，可以在这里做校验
                    if file_info["hash"]:
                        # 计算并验证哈希
                        pass
                    
                    downloaded += 1
                    logger.info(f"Downloaded: {file_info['name']}")
                    
                except Exception as e:
                    logger.error(f"Failed to download {file_info['name']}: {e}")
                    file_path.unlink(missing_ok=True)
                    self.error.emit(f"下载 {file_info['name']} 失败: {str(e)}")
                    return
            
            if not self.is_cancelled:
                self.finished.emit(True)
                
        except Exception as e:
            logger.error(f"HY-MT1.5 download failed: {e}")
            if not self.is_cancelled:
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
