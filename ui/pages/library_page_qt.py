"""
音效库页面 - 完整功能版本
支持：文件夹导入、树形结构、元数据提取、高级搜索、播放、批量操作
集成后端：LibraryScanner, MetadataExtractor
"""

import csv
import json
import logging
import os
import sys
import subprocess
import tempfile
import time
import asyncio
from pathlib import Path
from collections import defaultdict, deque, OrderedDict
from typing import Optional, Dict, List
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QThread, QObject, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidgetItem,
    QFileDialog, QHeaderView, QAbstractItemView, QStackedWidget, QApplication, QSizePolicy
)
from PySide6.QtGui import QFont, QColor

from qfluentwidgets import (
    PushButton, PrimaryPushButton, SearchLineEdit,
    FluentIcon, TreeWidget,
    TitleLabel, CaptionLabel, CardWidget, IconWidget,
    SubtitleLabel, BodyLabel, TransparentToolButton,
    CheckBox, ProgressBar, ComboBox, isDarkTheme
)

# Architecture refactoring: use centralized utilities
from transcriptionist_v3.core.config import AppConfig, get_default_scan_workers
from transcriptionist_v3.core.utils import format_file_size, format_duration, format_sample_rate
from transcriptionist_v3.ui.utils.notifications import NotificationHelper
from transcriptionist_v3.ui.utils.workers import DatabaseLoadWorker, cleanup_thread
from transcriptionist_v3.application.search_engine.search_engine import SearchEngine
from transcriptionist_v3.infrastructure.database.connection import session_scope
from transcriptionist_v3.ui.themes.theme_tokens import get_theme_tokens

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {".wav", ".flac", ".mp3", ".ogg", ".aiff", ".aif", ".m4a", ".mp4"}

# SQLite 单条 SQL 中变量数上限约 999
# IN 查询/更新：每批 500 个占位符安全
SQLITE_IN_BATCH = 500
# INSERT 多行：每行 3 列 → 每批最多 999/3≈333 行，取 300 保险（4–5 万条也安全）
SQLITE_INSERT_BATCH = 300

# 导入队列状态
IMPORT_STATUS_PENDING = 0
IMPORT_STATUS_PROCESSING = 1
IMPORT_STATUS_DONE = 2
IMPORT_STATUS_SKIPPED = 3
IMPORT_STATUS_FAILED = 4


class SaveWorker(QObject):
    """后台保存工作线程"""
    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(int, int)  # saved_count, skipped_count
    error = Signal(str)
    
    def __init__(self, root_folder: str, results: list, parent=None):
        super().__init__(parent)
        self.root_folder = root_folder
        self.results = results
    
    def run(self):
        """执行数据库保存"""
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile, LibraryPath
            
            saved_count = 0
            skipped_count = 0
            
            with session_scope() as session:
                self.progress.emit(0, len(self.results), "正在记录扫描路径...")
                
                # 记录扫描的路径
                lib_path = session.query(LibraryPath).filter_by(path=str(self.root_folder)).first()
                if not lib_path:
                    lib_path = LibraryPath(
                        path=str(self.root_folder),
                        enabled=True,
                        recursive=True
                    )
                    session.add(lib_path)
                
                lib_path.last_scan_at = datetime.now()
                lib_path.file_count = len(self.results)
                
                # 批量查询已存在的文件路径（优化性能，避免 SQLite 变量数量限制）
                file_paths = [str(fp) for fp, _ in self.results]
                existing_paths: set[str] = set()
                BATCH_SIZE = 500
                total_batches = (len(file_paths) + BATCH_SIZE - 1) // BATCH_SIZE
                
                for batch_idx in range(0, len(file_paths), BATCH_SIZE):
                    batch_num = batch_idx // BATCH_SIZE + 1
                    batch = file_paths[batch_idx:batch_idx + BATCH_SIZE]
                    self.progress.emit(
                        batch_idx, 
                        len(file_paths), 
                        f"正在检查已存在的文件 (第 {batch_num}/{total_batches} 批)"
                    )
                    rows = (
                        session.query(AudioFile.file_path)
                        .filter(AudioFile.file_path.in_(batch))
                        .all()
                    )
                    existing_paths.update(row.file_path for row in rows)
                
                self.progress.emit(0, len(self.results), "正在准备新文件...")
                
                # 批量准备新文件
                new_files = []
                for idx, (file_path, metadata) in enumerate(self.results):
                    if (idx + 1) % 100 == 0:
                        self.progress.emit(idx + 1, len(self.results), f"正在准备文件 {idx + 1}/{len(self.results)}")
                    
                    if metadata and str(file_path) not in existing_paths:
                        audio_file = AudioFile(
                            file_path=str(file_path),
                            filename=file_path.name,
                            file_size=file_path.stat().st_size,
                            content_hash="",
                            duration=metadata.duration,
                            sample_rate=metadata.sample_rate,
                            bit_depth=metadata.bit_depth or 16,
                            channels=metadata.channels,
                            format=file_path.suffix.lstrip('.').lower(),
                            description=getattr(metadata, 'description', None) or metadata.comment,
                            original_filename=file_path.name
                        )
                        new_files.append(audio_file)
                    else:
                        skipped_count += 1
                
                # 批量插入
                if new_files:
                    self.progress.emit(0, len(new_files), f"正在保存 {len(new_files)} 个新文件...")
                    session.bulk_save_objects(new_files)
                    saved_count = len(new_files)
                
                session.commit()
                logger.info(f"Saved {saved_count} new files, skipped {skipped_count} existing files")
                self.finished.emit(saved_count, skipped_count)
                
        except Exception as e:
            logger.error(f"Save error: {e}")
            self.error.emit(str(e))


class QueueScanWorker(QObject):
    """扫描并入队：发现文件立即写入导入队列。"""
    progress = Signal(int, int, str)  # scanned, total, current_file
    finished = Signal(dict)  # {"total": int, "enqueued": int, "skipped": int}
    error = Signal(str)

    # 扫描进度间隔
    SCAN_PROGRESS_INTERVAL = 5000
    # 入队批量大小
    ENQUEUE_BATCH_SIZE = 2000

    def __init__(self, folder_path: str, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _scan_dir_stream(self, dir_path: Path):
        """递归流式扫描目录，逐个产出匹配文件路径，避免大列表占用内存峰值。"""
        if self._cancelled:
            return
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if self._cancelled:
                        return
                    if entry.is_file(follow_symlinks=False):
                        file_path = Path(entry.path)
                        if file_path.suffix.lower() in SUPPORTED_FORMATS:
                            yield file_path
                    elif entry.is_dir(follow_symlinks=False):
                        yield from self._scan_dir_stream(Path(entry.path))
        except PermissionError:
            logger.warning(f"Permission denied: {dir_path}")
        except Exception as e:
            logger.warning(f"Error scanning {dir_path}: {e}")

    def _enqueue_paths(self, root_folder: Path, paths: list[str]) -> tuple[int, int]:
        """将路径批量写入导入队列，返回 (enqueued, skipped)。避免 SQLite too many SQL variables。"""
        if not paths:
            return 0, 0
        from sqlalchemy import insert
        from transcriptionist_v3.infrastructure.database.connection import session_scope
        from transcriptionist_v3.infrastructure.database.models import ImportQueue, AudioFile

        existing_audio: set[str] = set()
        existing_queue: set[str] = set()
        with session_scope() as session:
            for i in range(0, len(paths), SQLITE_IN_BATCH):
                batch = paths[i : i + SQLITE_IN_BATCH]
                existing_audio.update(
                    row.file_path for row in session.query(AudioFile.file_path).filter(AudioFile.file_path.in_(batch)).all()
                )
                existing_queue.update(
                    row.file_path for row in session.query(ImportQueue.file_path).filter(ImportQueue.file_path.in_(batch)).all()
                )
            to_insert = [p for p in paths if p not in existing_audio and p not in existing_queue]
            skipped = len(paths) - len(to_insert)

            if to_insert:
                for i in range(0, len(to_insert), SQLITE_INSERT_BATCH):
                    chunk = to_insert[i : i + SQLITE_INSERT_BATCH]
                    values = [
                        {
                            "file_path": p,
                            "root_path": str(root_folder),
                            "status": IMPORT_STATUS_PENDING,
                        }
                        for p in chunk
                    ]
                    stmt = insert(ImportQueue).prefix_with("OR IGNORE")
                    session.execute(stmt, values)
            # session_scope 退出时自动 commit
        return len(to_insert), skipped

    def run(self):
        """扫描目录：发现文件即入队。"""
        try:
            folder = Path(self.folder_path)
            logger.info(f"QueueScanWorker.run 开始：文件夹 {self.folder_path}")
            scanned = 0
            enqueued = 0
            skipped = 0
            buffer: list[str] = []

            def flush():
                nonlocal enqueued, skipped, buffer
                if not buffer:
                    return
                added, sk = self._enqueue_paths(folder, buffer)
                enqueued += added
                skipped += sk
                buffer = []

            self.progress.emit(0, 0, "正在扫描目录，请稍候...")

            # 根目录文件
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if self._cancelled:
                            return
                        if entry.is_file(follow_symlinks=False):
                            file_path = Path(entry.path)
                            if file_path.suffix.lower() in SUPPORTED_FORMATS:
                                buffer.append(str(file_path))
                                scanned += 1
                                if len(buffer) >= self.ENQUEUE_BATCH_SIZE:
                                    flush()
                                if scanned % self.SCAN_PROGRESS_INTERVAL == 0:
                                    self.progress.emit(
                                        scanned,
                                        0,
                                        f"正在扫描目录，已发现 {scanned} 个音频文件..."
                                    )
            except PermissionError:
                logger.warning(f"Permission denied: {folder}")
            except Exception as e:
                logger.warning(f"Error scanning root: {e}")

            # 一级子目录流式扫描（避免 future 一次性返回大列表导致内存峰值）
            subdirs = [Path(entry.path) for entry in os.scandir(folder) if entry.is_dir(follow_symlinks=False)]
            if subdirs:
                max_scan_workers = AppConfig.get("performance.scan_workers") or get_default_scan_workers()
                max_scan_workers = min(max(1, max_scan_workers), 32)
                logger.info(f"QueueScanWorker: scan_workers={max_scan_workers} (stream mode)")
                self.progress.emit(
                    scanned, 0,
                    f"正在扫描 {len(subdirs)} 个子目录（已发现 {scanned} 个）..."
                )
                for subdir in subdirs:
                    if self._cancelled:
                        return
                    try:
                        for file_path in self._scan_dir_stream(subdir):
                            if self._cancelled:
                                return
                            buffer.append(str(file_path))
                            scanned += 1
                            if len(buffer) >= self.ENQUEUE_BATCH_SIZE:
                                flush()
                            if scanned % self.SCAN_PROGRESS_INTERVAL == 0:
                                self.progress.emit(
                                    scanned, 0,
                                    f"正在扫描目录，已发现 {scanned} 个音频文件..."
                                )
                    except Exception as e:
                        logger.warning(f"Subdir scan failed: {e}")

            # 最后入队
            flush()

            # 更新库路径信息
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import LibraryPath
            with session_scope() as session:
                lib_path = session.query(LibraryPath).filter_by(path=str(folder)).first()
                if not lib_path:
                    lib_path = LibraryPath(path=str(folder), enabled=True, recursive=True)
                    session.add(lib_path)
                lib_path.last_scan_at = datetime.now()
                lib_path.file_count = scanned
                session.commit()

            self.finished.emit({"total": scanned, "enqueued": enqueued, "skipped": skipped})

        except Exception as e:
            logger.error(f"Queue scan error: {e}")
            self.error.emit(str(e))


class ImportQueueWorker(QObject):
    """后台处理导入队列：提取元数据并写入 audio_files。"""
    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(int, int)  # saved_count, skipped_count
    error = Signal(str)

    PARALLEL_THRESHOLD = 100

    def __init__(self, root_folder: Optional[str] = None, batch_size: int = 3000, parent=None):
        super().__init__(parent)
        self.root_folder = str(root_folder) if root_folder else None
        self.batch_size = max(1, int(batch_size))
        self._cancelled = False
        self._pool = None  # 复用进程池，避免每次 batch 都创建/销毁

    def cancel(self):
        self._cancelled = True
        if self._pool is not None:
            try:
                self._pool.terminate()
                self._pool.join()
            except Exception:
                pass
            self._pool = None

    def _extract_metadata_batch(self, file_paths: list[str], progress_cb=None) -> list:
        from transcriptionist_v3.application.library_manager.metadata_extractor import MetadataExtractor, extract_one_for_pool
        total = len(file_paths)
        if total == 0:
            return []
        if total < self.PARALLEL_THRESHOLD:
            extractor = MetadataExtractor()
            results = []
            for idx, path_str in enumerate(file_paths, start=1):
                if self._cancelled:
                    return []
                try:
                    meta = extractor.extract(Path(path_str))
                except Exception:
                    meta = None
                results.append(meta)
                if progress_cb and (idx % 50 == 0 or idx == total):
                    progress_cb(idx, total)
            return results

        # 多进程提取（复用进程池，避免每次 batch 都创建/销毁）
        from multiprocessing import Pool
        max_workers = AppConfig.get("performance.scan_workers") or get_default_scan_workers()
        max_workers = max(1, min(max_workers, total))
        
        # 首次调用时创建进程池，后续复用
        if self._pool is None:
            logger.info(f"ImportQueueWorker: 创建进程池 metadata_workers={max_workers}")
            self._pool = Pool(processes=max_workers)
        else:
            logger.info(f"ImportQueueWorker: 复用进程池 metadata_workers={max_workers}")
        
        results = [None] * total
        args_list = [(i, str(fp)) for i, fp in enumerate(file_paths)]
        # 优化 chunksize：增大批次大小，减少进程间通信开销
        chunksize = max(1, min(200, total // max_workers))
        try:
            it = self._pool.imap_unordered(extract_one_for_pool, args_list, chunksize=chunksize)
            done = 0
            for res in it:
                if self._cancelled:
                    return []
                idx, _, meta = res
                results[idx] = meta
                done += 1
                # 减少进度更新频率，避免信号过多影响性能
                if progress_cb and (done % 100 == 0 or done == total):
                    progress_cb(done, total)
        except Exception as e:
            logger.warning(f"Multiprocessing extract failed: {e}")
            # 失败时关闭进程池并退回单线程
            if self._pool is not None:
                try:
                    self._pool.terminate()
                    self._pool.join()
                except Exception:
                    pass
                self._pool = None
            extractor = MetadataExtractor()
            results = []
            for idx, path_str in enumerate(file_paths, start=1):
                if self._cancelled:
                    return []
                try:
                    meta = extractor.extract(Path(path_str))
                except Exception:
                    meta = None
                results.append(meta)
                if progress_cb and (idx % 100 == 0 or idx == total):
                    progress_cb(idx, total)
        return results

    def run(self):
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import ImportQueue, AudioFile

            saved_total = 0
            skipped_total = 0
            processed_total = 0

            with session_scope() as session:
                query = session.query(ImportQueue).filter(ImportQueue.status == IMPORT_STATUS_PENDING)
                if self.root_folder:
                    query = query.filter(ImportQueue.root_path == self.root_folder)
                overall_total = query.count()

            while True:
                if self._cancelled:
                    return

                with session_scope() as session:
                    query = session.query(ImportQueue).filter(ImportQueue.status == IMPORT_STATUS_PENDING)
                    if self.root_folder:
                        query = query.filter(ImportQueue.root_path == self.root_folder)
                    rows = query.order_by(ImportQueue.id).limit(self.batch_size).all()
                    if not rows:
                        break
                    ids = [r.id for r in rows]
                    paths = [r.file_path for r in rows]
                    
                    # 合并查询：已存在的文件路径（分批，避免 too many SQL variables）
                    existing: set[str] = set()
                    for i in range(0, len(paths), SQLITE_IN_BATCH):
                        batch = paths[i : i + SQLITE_IN_BATCH]
                        existing.update(
                            row.file_path for row in session.query(AudioFile.file_path).filter(AudioFile.file_path.in_(batch)).all()
                        )
                    
                    # 更新状态为 PROCESSING（分批）
                    for i in range(0, len(ids), SQLITE_IN_BATCH):
                        id_batch = ids[i : i + SQLITE_IN_BATCH]
                        session.query(ImportQueue).filter(ImportQueue.id.in_(id_batch)).update(
                            {"status": IMPORT_STATUS_PROCESSING}, synchronize_session=False
                        )
                    session.commit()

                pending_rows = [(r, p) for r, p in zip(rows, paths) if p not in existing]
                skipped_ids = [r.id for r, p in zip(rows, paths) if p in existing]

                to_process_paths = [p for _, p in pending_rows]
                def _progress_local(done, _batch_total):
                    self.progress.emit(processed_total + done, overall_total, f"正在提取元数据... {processed_total + done}/{overall_total}")

                # 先发一次进度，避免 UI 看起来“卡住”
                self.progress.emit(processed_total, overall_total, f"正在提取元数据... {processed_total}/{overall_total}")
                metas = self._extract_metadata_batch(to_process_paths, progress_cb=_progress_local)

                new_files = []
                done_ids = []
                failed_ids = []

                for idx, (row, path_str) in enumerate(pending_rows):
                    # 即使元数据提取失败(meta 为 None)，也尽量创建记录，保证文件至少能出现在库中
                    meta = metas[idx] if idx < len(metas) else None
                    try:
                        p = Path(path_str)
                        if not p.exists():
                            failed_ids.append(row.id)
                            continue

                        duration = 0.0
                        sample_rate = 0
                        bit_depth = 16
                        channels = 0
                        description = None

                        if meta is not None:
                            duration = float(getattr(meta, "duration", 0.0) or 0.0)
                            sample_rate = int(getattr(meta, "sample_rate", 0) or 0)
                            bit_depth = int(getattr(meta, "bit_depth", 16) or 16)
                            channels = int(getattr(meta, "channels", 0) or 0)
                            description = getattr(meta, "description", None) or getattr(meta, "comment", None)

                        audio_file = AudioFile(
                            file_path=str(p),
                            filename=p.name,
                            file_size=p.stat().st_size,
                            content_hash="",
                            duration=duration,
                            sample_rate=sample_rate,
                            bit_depth=bit_depth,
                            channels=channels,
                            format=p.suffix.lstrip('.').lower(),
                            description=description,
                            original_filename=p.name,
                        )
                        new_files.append(audio_file)
                        done_ids.append(row.id)
                    except Exception:
                        failed_ids.append(row.id)

                with session_scope() as session:
                    if new_files:
                        session.bulk_save_objects(new_files)
                        saved_total += len(new_files)
                    for i in range(0, len(skipped_ids), SQLITE_IN_BATCH):
                        session.query(ImportQueue).filter(ImportQueue.id.in_(skipped_ids[i : i + SQLITE_IN_BATCH])).update(
                            {"status": IMPORT_STATUS_SKIPPED}, synchronize_session=False
                        )
                    if skipped_ids:
                        skipped_total += len(skipped_ids)
                    for i in range(0, len(done_ids), SQLITE_IN_BATCH):
                        session.query(ImportQueue).filter(ImportQueue.id.in_(done_ids[i : i + SQLITE_IN_BATCH])).update(
                            {"status": IMPORT_STATUS_DONE}, synchronize_session=False
                        )
                    for i in range(0, len(failed_ids), SQLITE_IN_BATCH):
                        session.query(ImportQueue).filter(ImportQueue.id.in_(failed_ids[i : i + SQLITE_IN_BATCH])).update(
                            {"status": IMPORT_STATUS_FAILED, "error": "metadata extract failed"}, synchronize_session=False
                        )
                    if failed_ids:
                        skipped_total += len(failed_ids)
                    session.commit()

                processed_total += len(rows)
                self.progress.emit(processed_total, overall_total, f"正在入库... {processed_total}/{overall_total}")

            # 关闭进程池（线程守卫：确保资源释放）
            if self._pool is not None:
                try:
                    logger.info("ImportQueueWorker: 关闭进程池")
                    self._pool.close()
                    self._pool.join()
                except Exception as e:
                    logger.warning(f"关闭进程池时出错: {e}")
                    try:
                        self._pool.terminate()
                        self._pool.join()
                    except Exception:
                        pass
                finally:
                    self._pool = None

            self.finished.emit(saved_total, skipped_total)

        except Exception as e:
            logger.error(f"Import queue error: {e}")
            # 出错时也要关闭进程池
            if self._pool is not None:
                try:
                    self._pool.terminate()
                    self._pool.join()
                except Exception:
                    pass
                self._pool = None
            self.error.emit(str(e))
_metadata_extractor_local = None


def _extract_metadata_worker(path_str: str):
    """
    供多进程使用的元数据提取函数。
    每个进程内懒加载一个 MetadataExtractor 实例，避免频繁构造。
    """
    global _metadata_extractor_local
    try:
        from pathlib import Path as _Path
        from transcriptionist_v3.application.library_manager.metadata_extractor import MetadataExtractor

        if _metadata_extractor_local is None:
            _metadata_extractor_local = MetadataExtractor()

        file_path = _Path(path_str)
        metadata = _metadata_extractor_local.extract(file_path)
        return path_str, metadata
    except Exception as e:
        # 在子进程中无法直接使用主进程 logger，这里简单返回 None，由主进程处理
        return path_str, None


class ScanWorker(QObject):
    """后台扫描工作线程"""
    progress = Signal(int, int, str)  # scanned, total, current_file
    finished = Signal(list)  # List of (path, metadata) tuples
    error = Signal(str)
    
    # 启用并行元数据提取的文件数阈值
    PARALLEL_THRESHOLD = 100
    # 独立子进程阈值：超过此数量使用独立子进程（subprocess），获得更好的性能和稳定性
    # 1000+ 文件时，独立子进程比进程内多进程更快更稳定（避免 GIL 和内存共享问题）
    SUBPROCESS_THRESHOLD = 1000
    # 超大批量时每批文件数，避免单次 JSON 与内存过大（支持百万级）
    BATCH_SIZE = 25000
    
    def __init__(self, folder_path: str, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self._cancelled = False
        self._subprocess = None
    
    def cancel(self):
        self._cancelled = True
        # 如果有后台进程在运行，终止它
        if self._subprocess is not None:
            try:
                self._subprocess.terminate()
            except Exception:
                pass
    
    # 扫描阶段每发现多少文件发一次进度（避免百万级时长时间无反馈）
    SCAN_PROGRESS_INTERVAL = 5000

    def _scan_dir_into_list(self, dir_path: Path) -> list:
        """递归扫描单个目录并返回路径列表（供并行扫描用，不写共享列表）。"""
        out = []
        if self._cancelled:
            return out
        try:
            with os.scandir(dir_path) as entries:
                for entry in entries:
                    if self._cancelled:
                        return out
                    if entry.is_file(follow_symlinks=False):
                        file_path = Path(entry.path)
                        if file_path.suffix.lower() in SUPPORTED_FORMATS:
                            out.append(file_path)
                    elif entry.is_dir(follow_symlinks=False):
                        out.extend(self._scan_dir_into_list(Path(entry.path)))
        except PermissionError:
            logger.warning(f"Permission denied: {dir_path}")
        except Exception as e:
            logger.warning(f"Error scanning {dir_path}: {e}")
        return out

    def run(self):
        """执行扫描：先收集根目录文件并并行扫描一级子目录，再按批提取元数据。"""
        try:
            folder = Path(self.folder_path)
            logger.info(f"ScanWorker.run 开始：文件夹 {self.folder_path}")
            audio_files = []
            self.progress.emit(0, 0, "正在扫描目录，请稍候...")

            # 根目录下的文件（主线程，带进度）
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if self._cancelled:
                            return
                        if entry.is_file(follow_symlinks=False):
                            file_path = Path(entry.path)
                            if file_path.suffix.lower() in SUPPORTED_FORMATS:
                                audio_files.append(file_path)
                                if len(audio_files) % self.SCAN_PROGRESS_INTERVAL == 0:
                                    self.progress.emit(
                                        len(audio_files), 0,
                                        f"正在扫描目录，已发现 {len(audio_files)} 个音频文件..."
                                    )
            except PermissionError:
                logger.warning(f"Permission denied: {folder}")
            except Exception as e:
                logger.warning(f"Error scanning root: {e}")

            # 一级子目录并行扫描（读「库扫描并行数」，几十万/百万级时显著缩短收集时间）
            subdirs = [Path(entry.path) for entry in os.scandir(folder)
                       if entry.is_dir(follow_symlinks=False)]
            if subdirs:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                max_scan_workers = AppConfig.get("performance.scan_workers") or get_default_scan_workers()
                max_scan_workers = min(max(1, max_scan_workers), 32)  # 扫目录用线程，上限 32
                self.progress.emit(
                    len(audio_files), 0,
                    f"正在并行扫描 {len(subdirs)} 个子目录（已发现 {len(audio_files)} 个）..."
                )
                with ThreadPoolExecutor(max_workers=max_scan_workers) as ex:
                    futures = {ex.submit(self._scan_dir_into_list, d): d for d in subdirs}
                    for future in as_completed(futures):
                        if self._cancelled:
                            return
                        try:
                            paths = future.result()
                            audio_files.extend(paths)
                            self.progress.emit(
                                len(audio_files), 0,
                                f"正在扫描目录，已发现 {len(audio_files)} 个音频文件..."
                            )
                        except Exception as e:
                            logger.warning(f"Subdir scan failed: {e}")
            # 无一级子目录时根目录文件已在上面收集完毕，无需再扫

            total = len(audio_files)
            logger.info(f"扫描完成，共 {total} 个音频文件，开始元数据提取")
            
            if self._cancelled:
                return
            
            # 根据文件数量选择提取方式（日志便于确认是否走对分支）
            if total < self.PARALLEL_THRESHOLD:
                logger.info(f"元数据提取：单线程 (<{self.PARALLEL_THRESHOLD})")
                results = self._extract_single_thread(audio_files)
            elif total < self.SUBPROCESS_THRESHOLD:
                logger.info(f"元数据提取：进程内并行 ({self.PARALLEL_THRESHOLD}~{self.SUBPROCESS_THRESHOLD})")
                results = self._extract_parallel_inprocess(audio_files)
            else:
                logger.info(f"元数据提取：独立子进程 (≥{self.SUBPROCESS_THRESHOLD})")
                results = self._extract_parallel(audio_files)
            
            if not self._cancelled:
                self.finished.emit(results)
            
        except Exception as e:
            logger.error(f"Scan error: {e}")
            self.error.emit(str(e))
    
    def _extract_single_thread(self, audio_files: list) -> list:
        """单线程提取元数据"""
        from transcriptionist_v3.application.library_manager.metadata_extractor import MetadataExtractor
        
        extractor = MetadataExtractor()
        total = len(audio_files)
        results = []
        
        for i, file_path in enumerate(audio_files):
            if self._cancelled:
                return results
            
            self.progress.emit(i + 1, total, str(file_path))
            
            try:
                metadata = extractor.extract(file_path)
                results.append((file_path, metadata))
            except Exception as e:
                logger.warning(f"Failed to extract metadata from {file_path}: {e}")
                results.append((file_path, None))
        
        return results
    
    def _extract_parallel_inprocess(self, audio_files: list) -> list:
        """进程内多进程提取元数据（multiprocessing.Pool），读「库扫描并行数」，真正多核并行。适用于 100~2.5 万文件。"""
        from multiprocessing import Pool
        from transcriptionist_v3.application.library_manager.metadata_extractor import extract_one_for_pool
        
        total = len(audio_files)
        max_workers = AppConfig.get("performance.scan_workers") or get_default_scan_workers()
        max_workers = max(1, min(max_workers, total))
        
        logger.info(f"元数据提取：进程内多进程，workers={max_workers}（库扫描并行数）")
        self.progress.emit(0, total, "正在多进程提取元数据...")
        
        results = [None] * total
        completed = 0
        args_list = [(i, str(fp)) for i, fp in enumerate(audio_files)]
        chunksize = max(1, min(50, total // (max_workers * 4)))
        
        try:
            with Pool(processes=max_workers) as pool:
                it = pool.imap_unordered(extract_one_for_pool, args_list, chunksize=chunksize)
                for res in it:
                    if self._cancelled:
                        pool.terminate()
                        pool.join()
                        return []
                    idx, path_str, meta = res
                    results[idx] = meta
                    completed += 1
                    if completed % 100 == 0 or completed == total:
                        self.progress.emit(completed, total, path_str)
        except Exception as e:
            logger.warning(f"Multiprocessing extract failed: {e}")
            return self._extract_single_thread(audio_files)
        
        return [(audio_files[i], results[i]) for i in range(total)]
    
    def _extract_parallel(self, audio_files: list) -> list:
        """使用独立后台进程并行提取元数据；超大批量时按批处理并流式输出，避免百万级内存与 JSON 瓶颈。"""
        from transcriptionist_v3.domain.models import AudioMetadata
        
        total = len(audio_files)
        self.progress.emit(0, total, "准备并行提取元数据...")
        
        # 根据配置或 CPU 检测得到并行进程上限（不硬编码）
        max_workers = AppConfig.get("performance.scan_workers") or get_default_scan_workers()
        
        if getattr(sys, 'frozen', False):
            worker_exe = Path(sys.executable).parent / "metadata_worker.exe"
            if not worker_exe.exists():
                logger.warning("metadata_worker.exe not found (frozen), falling back to single-thread")
                return self._extract_single_thread(audio_files)
            cmd_worker = str(worker_exe)
        else:
            script_path = self._get_worker_script_path()
            if script_path is None:
                logger.warning("Parallel worker script not found, falling back to single-thread")
                return self._extract_single_thread(audio_files)
            cmd_worker = [sys.executable, script_path]
        
        temp_dir = tempfile.gettempdir()
        timestamp = int(time.time() * 1000)
        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        
        # 超大批量分批：每批 BATCH_SIZE 条，避免单次 JSON 与输出过大（支持百万级）
        batch_size = self.BATCH_SIZE
        batches = [
            audio_files[i:i + batch_size]
            for i in range(0, total, batch_size)
        ]
        result_map = {}
        temp_files_to_clean = []
        
        try:
            for batch_idx, batch in enumerate(batches):
                if self._cancelled:
                    return []
                
                batch_offset = batch_idx * batch_size
                batch_total = len(batch)
                input_file = os.path.join(temp_dir, f"meta_input_{timestamp}_b{batch_idx}.json")
                output_file = os.path.join(temp_dir, f"meta_output_{timestamp}_b{batch_idx}.json")
                progress_file = os.path.join(temp_dir, f"meta_progress_{timestamp}_b{batch_idx}.json")
                temp_files_to_clean.extend([input_file, output_file, progress_file])
                
                # 进度间隔由 worker 按 total 自动；也可传入，此处不传即自动
                input_data = {
                    "files": [str(fp) for fp in batch],
                    "progress_file": progress_file,
                    "max_workers": max_workers,
                }
                with open(input_file, 'w', encoding='utf-8') as f:
                    json.dump(input_data, f, ensure_ascii=False)
                
                if getattr(sys, 'frozen', False):
                    cmd = [cmd_worker, '--input', input_file, '--output', output_file]
                else:
                    cmd = cmd_worker + ['--input', input_file, '--output', output_file]
                
                self.progress.emit(batch_offset, total, f"第 {batch_idx + 1}/{len(batches)} 批，共 {batch_total} 个文件...")
                logger.info(f"Starting parallel metadata extraction batch {batch_idx + 1}/{len(batches)} ({batch_total} files)")
                
                self._subprocess = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    startupinfo=startupinfo,
                    creationflags=creationflags
                )
                
                last_processed = 0
                while self._subprocess.poll() is None:
                    if self._cancelled:
                        self._subprocess.terminate()
                        return []
                    try:
                        if os.path.exists(progress_file):
                            with open(progress_file, 'r', encoding='utf-8') as f:
                                progress_data = json.load(f)
                            processed = progress_data.get('processed', 0)
                            current_file = progress_data.get('current_file', '')
                            global_processed = batch_offset + processed
                            if global_processed != last_processed:
                                self.progress.emit(global_processed, total, current_file)
                                last_processed = global_processed
                    except Exception:
                        pass
                    time.sleep(0.1)
                
                ret = self._subprocess.returncode if self._subprocess is not None else -1
                self._subprocess = None
                if ret != 0:
                    logger.error(f"Parallel extraction batch failed with code {ret}")
                    return self._extract_single_thread(audio_files)
                
                if not os.path.exists(output_file):
                    logger.error("Output file not found after parallel extraction")
                    return self._extract_single_thread(audio_files)
                
                with open(output_file, 'r', encoding='utf-8') as f:
                    output_data = json.load(f)
                if 'error' in output_data:
                    logger.error(f"Parallel extraction error: {output_data['error']}")
                    return self._extract_single_thread(audio_files)
                for r in output_data.get('results', []):
                    result_map[r['path']] = r['metadata']
            
            # 按 audio_files 顺序组装结果
            results = []
            for file_path in audio_files:
                path_str = str(file_path)
                meta_dict = result_map.get(path_str)
                if meta_dict is not None:
                    metadata = AudioMetadata()
                    metadata.duration = meta_dict.get('duration')
                    metadata.sample_rate = meta_dict.get('sample_rate')
                    metadata.bit_depth = meta_dict.get('bit_depth')
                    metadata.channels = meta_dict.get('channels')
                    metadata.bitrate = meta_dict.get('bitrate')
                    metadata.format = meta_dict.get('format')
                    metadata.comment = meta_dict.get('comment')
                    metadata.original_filename = meta_dict.get('original_filename')
                    results.append((file_path, metadata))
                else:
                    results.append((file_path, None))
            
            logger.info(f"Parallel extraction completed: {total} files in {len(batches)} batch(es)")
            return results
            
        except Exception as e:
            logger.error(f"Parallel extraction error: {e}")
            return self._extract_single_thread(audio_files)
        finally:
            self._subprocess = None
            for temp_file in temp_files_to_clean:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception:
                    pass
    
    def _get_worker_script_path(self) -> str:
        """获取后台工作脚本路径"""
        # 尝试多种可能的路径
        possible_paths = []
        
        # 1. 相对于当前模块
        current_dir = Path(__file__).parent
        possible_paths.append(current_dir.parent.parent / 'scripts' / 'metadata_worker.py')
        
        # 2. 相对于工作目录
        possible_paths.append(Path.cwd() / 'scripts' / 'metadata_worker.py')
        
        # 3. 相对于包根目录
        try:
            import transcriptionist_v3
            pkg_dir = Path(transcriptionist_v3.__file__).parent
            possible_paths.append(pkg_dir / 'scripts' / 'metadata_worker.py')
            possible_paths.append(pkg_dir.parent / 'scripts' / 'metadata_worker.py')
        except Exception:
            pass
        
        for path in possible_paths:
            if path.exists():
                return str(path)
        
        return None
    
    def _get_python_executable(self) -> str:
        """获取 Python 解释器路径"""
        import sys
        return sys.executable


class EmptyStateWidget(QWidget):
    """空状态组件"""
    
    import_clicked = Signal()
    folder_dropped = Signal(list)  # 新增：拖入文件夹导入
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # 允许拖放操作
        self.setAcceptDrops(True)
        self._init_ui()
    
    def _init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        outer_layout.setContentsMargins(12, 18, 12, 0)
        outer_layout.setSpacing(0)

        self._drop_card = CardWidget(self)
        self._drop_card.setObjectName("libraryEmptyDropCard")
        self._drop_card.setProperty("dragActive", False)
        self._drop_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._drop_card.setMaximumWidth(640)
        self._drop_card.setMinimumHeight(220)

        drop_layout = QVBoxLayout(self._drop_card)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.setContentsMargins(20, 18, 20, 18)
        drop_layout.setSpacing(8)

        icon_wrap = QWidget(self._drop_card)
        icon_wrap.setObjectName("libraryEmptyDropIconWrap")
        icon_wrap.setFixedSize(68, 68)
        icon_layout = QVBoxLayout(icon_wrap)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(0)

        icon = IconWidget(FluentIcon.MUSIC_FOLDER)
        icon.setFixedSize(38, 38)
        icon_layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(icon_wrap, alignment=Qt.AlignmentFlag.AlignCenter)

        title = SubtitleLabel("开始管理您的音效")
        title.setObjectName("libraryEmptyDropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(title)

        desc = CaptionLabel("将音效目录拖放到此处")
        desc.setObjectName("libraryEmptyDropDesc")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        drop_layout.addWidget(desc)

        outer_layout.addWidget(self._drop_card, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._update_drop_card_width()

    def _update_drop_card_width(self):
        card = getattr(self, "_drop_card", None)
        if card is None:
            return
        available = max(280, self.width() - 24)
        target = min(640, available)
        card.setFixedWidth(target)

    def _set_drag_active(self, active: bool):
        card = getattr(self, "_drop_card", None)
        if card is None:
            return
        if bool(card.property("dragActive")) == active:
            return
        card.setProperty("dragActive", active)
        card.style().unpolish(card)
        card.style().polish(card)
        card.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_drop_card_width()

    # ---- 拖放支持：拖入文件夹以导入 ----
    def dragEnterEvent(self, event):
        """拖入时检查是否包含文件夹 URL。"""
        mime = event.mimeData()
        if mime.hasUrls():
            urls = mime.urls()
            for url in urls:
                local = url.toLocalFile()
                if local:
                    try:
                        if os.path.isdir(local):
                            self._set_drag_active(True)
                            event.acceptProposedAction()
                            return
                    except Exception:
                        continue
        self._set_drag_active(False)
        event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag_active(False)
        event.accept()

    def dropEvent(self, event):
        """放下文件夹时触发导入信号。"""
        self._set_drag_active(False)
        mime = event.mimeData()
        folders = []
        if mime.hasUrls():
            for url in mime.urls():
                local = url.toLocalFile()
                if local:
                    try:
                        if os.path.isdir(local):
                            folders.append(local)
                    except Exception:
                        continue
        if folders:
            logger.info(f"EmptyStateWidget: folders dropped: {folders}")
            self.folder_dropped.emit(folders)
            event.acceptProposedAction()
        else:
            event.ignore()


class LoadingStateWidget(QWidget):
    """加载状态组件 - 显示数据库加载进度"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)
        
        icon = IconWidget(FluentIcon.SYNC)
        icon.setFixedSize(64, 64)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.title_label = SubtitleLabel("正在加载音效库...")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedWidth(300)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.status_label = CaptionLabel("正在从数据库读取文件信息...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
    
    def update_progress(self, current: int, total: int, message: str):
        """更新加载进度"""
        if total > 0:
            percent = int(current / total * 100)
            self.progress_bar.setValue(percent)
            self.status_label.setText(f"加载中 {current}/{total} ({percent}%)")
        else:
            self.progress_bar.setValue(0)
            self.status_label.setText(message)


class ScanProgressWidget(QWidget):
    """扫描进度组件"""
    
    cancel_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_time = None
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)
        
        icon = IconWidget(FluentIcon.SYNC)
        icon.setFixedSize(64, 64)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.title_label = SubtitleLabel("正在扫描文件夹...")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedWidth(300)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.status_label = CaptionLabel("准备中...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        # 新增：速度和预计时间标签
        self.speed_label = CaptionLabel("")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.speed_label)
        
        cancel_btn = PushButton(FluentIcon.CLOSE, "取消")
        cancel_btn.clicked.connect(self.cancel_clicked.emit)
        layout.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)
    
    def update_progress(self, scanned: int, total: int, current_file: str):
        if self._start_time is None:
            self._start_time = datetime.now()
        
        if total > 0:
            percent = int(scanned / total * 100)
            self.progress_bar.setValue(percent)
            self.status_label.setText(f"已扫描 {scanned}/{total} - {Path(current_file).name}")
            
            # 计算速度和预计时间
            elapsed = (datetime.now() - self._start_time).total_seconds()
            if elapsed > 0 and scanned > 0:
                speed = scanned / elapsed
                remaining = total - scanned
                eta_seconds = remaining / speed if speed > 0 else 0
                
                # 格式化速度和预计时间
                speed_text = f"{speed:.1f} 文件/秒"
                if eta_seconds < 60:
                    eta_text = f"{int(eta_seconds)} 秒"
                elif eta_seconds < 3600:
                    eta_text = f"{int(eta_seconds / 60)} 分钟"
                else:
                    eta_text = f"{int(eta_seconds / 3600)} 小时"
                
                self.speed_label.setText(f"速度: {speed_text} | 预计剩余: {eta_text}")
        else:
            # total==0 表示「正在扫描目录」阶段，只显示已发现数量（无总进度）
            self.progress_bar.setValue(0)
            self.status_label.setText(current_file if current_file else "准备中...")
            self.speed_label.setText("")


class FileInfoCard(CardWidget):
    """文件信息卡片 - 显示选中文件的详细信息"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(280)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # 标题
        title = SubtitleLabel("文件信息")
        layout.addWidget(title)
        
        # 文件名
        self.name_label = BodyLabel("未选择文件")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        
        # 分隔线
        layout.addSpacing(8)
        
        # 元数据信息
        self.info_layout = QVBoxLayout()
        self.info_layout.setSpacing(6)
        layout.addLayout(self.info_layout)
        
        # 创建信息行
        self._info_labels = {}
        info_items = [
            ("original_name", "原文件名", FluentIcon.INFO), # Changed to INFO
            ("duration", "时长", FluentIcon.HISTORY),
            ("format", "格式", FluentIcon.DOCUMENT),
            ("sample_rate", "采样率", FluentIcon.SETTING),
            ("channels", "声道", FluentIcon.SPEAKERS),
            ("bit_depth", "位深", FluentIcon.ALBUM),
            ("size", "大小", FluentIcon.FOLDER),
        ]
        
        for key, label, icon in info_items:
            row = QHBoxLayout()
            row.setSpacing(8)
            
            icon_widget = IconWidget(icon)
            icon_widget.setFixedSize(16, 16)
            row.addWidget(icon_widget)
            
            name_lbl = CaptionLabel(f"{label}:")
            name_lbl.setFixedWidth(60) # Increased width for "原文件名"
            row.addWidget(name_lbl)
            
            value_lbl = BodyLabel("-")
            value_lbl.setWordWrap(True) # Allow wrapping for long filenames
            self._info_labels[key] = value_lbl
            row.addWidget(value_lbl, 1)
            
            self.info_layout.addLayout(row)
        
        layout.addStretch()

    def update_info(self, file_path: str, metadata):
        """更新文件信息"""
        path = Path(file_path)
        self.name_label.setText(path.name)
        
        if metadata:
            # 原文件名：优先使用精简提取已填充的 original_filename，无则从 raw 回退
            orig_name = "-"
            if getattr(metadata, "original_filename", ""):
                orig_name = metadata.original_filename
            elif hasattr(metadata, "raw") and metadata.raw:
                keys_to_check = [
                    "ORIGINAL_FILENAME",
                    "original_filename",
                    "TXXX:ORIGINAL_FILENAME",
                    "----:com.apple.iTunes:ORIGINAL_FILENAME",
                ]
                for k in keys_to_check:
                    if k in metadata.raw:
                        val = metadata.raw[k]
                        if isinstance(val, list) and val:
                            orig_name = str(val[0])
                        else:
                            orig_name = str(val)
                        break
            self._info_labels["original_name"].setText(orig_name)

            # 时长
            duration = metadata.duration if hasattr(metadata, 'duration') else 0
            if duration > 0:
                mins = int(duration // 60)
                secs = int(duration % 60)
                self._info_labels["duration"].setText(f"{mins:02d}:{secs:02d}")
            else:
                self._info_labels["duration"].setText("-")
            
            # 格式
            fmt = metadata.format if hasattr(metadata, 'format') else path.suffix[1:].upper()
            self._info_labels["format"].setText(fmt.upper())
            
            # 采样率
            sr = metadata.sample_rate if hasattr(metadata, 'sample_rate') else 0
            if sr > 0:
                self._info_labels["sample_rate"].setText(f"{sr / 1000:.1f} kHz")
            else:
                self._info_labels["sample_rate"].setText("-")
            
            # 声道
            ch = metadata.channels if hasattr(metadata, 'channels') else 0
            if ch == 1:
                self._info_labels["channels"].setText("单声道")
            elif ch == 2:
                self._info_labels["channels"].setText("立体声")
            elif ch > 0:
                self._info_labels["channels"].setText(f"{ch} 声道")
            else:
                self._info_labels["channels"].setText("-")
            
            # 位深
            bd = metadata.bit_depth if hasattr(metadata, 'bit_depth') else 0
            if bd > 0:
                self._info_labels["bit_depth"].setText(f"{bd} bit")
            else:
                self._info_labels["bit_depth"].setText("-")
        else:
            for key in self._info_labels:
                if key != "size":
                    self._info_labels[key].setText("-")
        
        # 文件大小
        try:
            size = path.stat().st_size
            self._info_labels["size"].setText(self._format_size(size))
        except:
            self._info_labels["size"].setText("-")

    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"
    
    def clear_info(self):
        """清空信息"""
        self.name_label.setText("未选择文件")
        for key in self._info_labels:
            self._info_labels[key].setText("-")


class LibraryPage(QWidget):
    """音效库页面 - 完整功能"""
    
    file_selected = Signal(str)
    files_checked = Signal(list)  # [file_path]
    # v2: 面向超大库的轻量选择通道（不传完整路径列表）
    # payload:
    #   {
    #     "mode": "none" | "files" | "folders" | "all",
    #     "count": int,
    #     "files": [str],          # mode == "files"
    #     "folders": [str],        # mode == "folders"
    #     "total": int             # mode == "all"
    #   }
    selection_changed = Signal(dict)
    files_deleted = Signal(list)  # [file_path]
    play_file = Signal(str)       # file_path
    request_ai_translate = Signal(list) # [file_path]
    request_ai_search = Signal(list) # [file_path]
    folder_clicked = Signal(str, list)  # folder_path, file_indices (List[int])
    library_cleared = Signal()
    realtime_index_status_changed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("libraryPage")
        
        self._audio_files: List[Path] = []
        self._library_roots: List[Path] = []  # Changed: Support multiple roots
        self._file_metadata: Dict[str, object] = {}  # path -> metadata
        self._file_info_cache: OrderedDict[str, dict] = OrderedDict()
        self._file_info_cache_limit: int = 5000
        self._folder_structure = defaultdict(list)
        # self._root_folder removed/deprecated logic, but keeping for scan context if needed?
        # Better to just use local var in scan, or temporary property.
        # But actually _root_folder was used to determine "current" view context.
        # We will keep it for compatibility if other methods use it, but initialized to None.
        self._root_folder: Optional[Path] = None 
        
        self._selected_files = set()
        self._selected_folders = set()  # 新增：跟踪选中的文件夹
        self._file_items: Dict[str, QTreeWidgetItem] = {}
        
        # 文件路径到数据库 ID 的映射（用于搜索）
        self._file_path_to_id: Dict[str, int] = {}
        
        # 懒加载相关
        self._all_file_data = []  # 所有文件数据 [(path, metadata), ...]
        self._loaded_count = 0    # 已加载数量
        self._batch_size = 100    # 每批加载数量
        self._is_loading = False  # 是否正在加载
        self._lazy_load_enabled = True  # 懒加载开关（搜索时禁用）
        self._folder_items = {}   # 文件夹节点缓存 {folder_path_str: QTreeWidgetItem}
        self._is_all_selected = False  # 全选状态标记
        
        self._scan_thread: Optional[QThread] = None
        self._scan_worker: Optional[ScanWorker] = None
        
        # Database loading thread (async to avoid blocking UI)
        self._db_load_thread: Optional[QThread] = None
        self._db_load_worker: Optional[DatabaseLoadWorker] = None
        
        # Initialize backend search engine
        self._search_engine = SearchEngine(lambda: session_scope())
        
        # 搜索防抖计时器，避免频繁触发全库搜索导致卡顿
        self._search_timer = QTimer(self)
        self._search_timer.setInterval(250)  # 250ms 防抖
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._execute_search)
        
        self._init_ui()
        self._load_from_database_async()  # 异步从数据库加载已有数据

    def _on_db_load_finished(self, data):
        """数据库加载完成"""
        self._cleanup_db_load_thread()
        
        if isinstance(data, dict):
            results = data.get("results") or []
            root_paths = data.get("root_paths") or []
            paths_only = bool(data.get("paths_only"))
        else:
            results, root_paths = data
            paths_only = False
        
        if not results and not root_paths:
            logger.info("No audio files loaded from database")
            self.stack.setCurrentWidget(self.empty_state)
            return
        
        # 保存所有文件数据（不立即显示）
        if paths_only:
            self._all_file_data = [(Path(p), None) for p in results]
            self._audio_files = [Path(p) for p in results]
            self._file_metadata = {}
        else:
            self._all_file_data = results
            self._audio_files = [path for path, _ in results]
            self._file_metadata = {str(path): metadata for path, metadata in results}
        
        # 清理缓存
        self._file_info_cache.clear()
        
        # 构建文件路径到数据库 ID 的映射（用于搜索）
        self._file_path_to_id = {}
        if not paths_only:
            try:
                from transcriptionist_v3.infrastructure.database.models import AudioFile
                with session_scope() as session:
                    for path, _ in results:
                        audio_file = session.query(AudioFile).filter_by(file_path=str(path)).first()
                        if audio_file:
                            self._file_path_to_id[str(path)] = audio_file.id
            except Exception as e:
                logger.error(f"Failed to build file path to ID mapping: {e}")
        
        self._library_roots = root_paths
        
        logger.info(f"Loaded {len(results)} audio files from database, roots: {len(root_paths)}, paths_only={paths_only}")
        
        # 切换到文件列表视图
        self.stack.setCurrentWidget(self.file_list_widget)
        
        # 懒加载：只加载初始批次
        self._loaded_count = 0
        self._lazy_load_enabled = True
        self._update_tree_lazy()
        
        # 连接滚动信号
        scrollbar = self.tree.verticalScrollBar()
        try:
            scrollbar.valueChanged.disconnect(self._on_scroll)
        except Exception:
            pass
        scrollbar.valueChanged.connect(self._on_scroll)
        
        # 更新统计
        self._update_stats()

    def _update_tree(self):
        """更新文件树 - 支持多根目录"""
        self.tree.clear()
        self._file_items.clear()
        
        if not self._library_roots and not self._audio_files:
            self.stack.setCurrentWidget(self.empty_state)
            # Disable buttons logic here...
            return
        
        # 统计
        total_folders = sum(len(subdict) for subdict in self._folder_structure.values())
        self.stats_label.setText(f"共 {len(self._audio_files)} 个音效，{total_folders} 个子文件夹")
        
        # 阻止信号
        self.tree.blockSignals(True)
        
        for root_path in self._library_roots:
            # Create Root Item
            root_name = root_path.name
            root_item = QTreeWidgetItem([root_name, "", "", "", "", ""])
            root_item.setIcon(0, FluentIcon.FOLDER.icon())
            root_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(root_path)})
            root_item.setFont(0, QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
            root_item.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(root_item)
            
            # Populate children for this root
            root_structure = self._folder_structure.get(root_path, {})
            folder_items = {".": root_item}
            
            sorted_folders = sorted(root_structure.keys(), key=lambda p: (p.count('/'), p.lower()))
            
            for folder_rel_path in sorted_folders:
                files = root_structure[folder_rel_path]
                
                if folder_rel_path == ".":
                    parent_item = root_item
                else:
                    parts = folder_rel_path.split('/')
                    current_path = ""
                    parent_item = root_item
                    
                    for part in parts:
                        current_path = f"{current_path}/{part}" if current_path else part
                        
                        if current_path not in folder_items:
                            folder_item = QTreeWidgetItem([part, "", "", "", "", ""])
                            folder_item.setIcon(0, FluentIcon.FOLDER.icon())
                            # Full path reconstruction
                            full_folder_path = root_path / current_path
                            folder_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(full_folder_path)})
                            folder_item.setCheckState(0, Qt.CheckState.Unchecked)
                            parent_item.addChild(folder_item)
                            folder_items[current_path] = folder_item
                        
                        parent_item = folder_items[current_path]
                
                # 不再显示文件，只显示文件夹
                # for file_path in sorted(files, key=lambda f: f.name.lower()):
                #     self._create_file_item(parent_item, file_path)
            
            root_item.setExpanded(True)
            
        self.tree.blockSignals(False)
        self._update_selected_count()

    def _create_file_item(self, parent_item, file_path):
        """Helper to create file item node - optimized for large libraries"""
        file_path_str = str(file_path)
        metadata = self._file_metadata.get(file_path_str)
        
        # 时长
        duration_str = "-"
        if metadata and hasattr(metadata, 'duration') and metadata.duration > 0:
            mins = int(metadata.duration // 60)
            secs = int(metadata.duration % 60)
            duration_str = f"{mins:02d}:{secs:02d}"
        
        # 格式
        ext = file_path.suffix.upper()[1:]
        
        # 创建文件项（只有3列：名称、时长、格式）
        file_item = QTreeWidgetItem([file_path.name, duration_str, ext])
        file_item.setIcon(0, FluentIcon.MUSIC.icon())
        file_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "file", "path": file_path_str})
        file_item.setCheckState(0, Qt.CheckState.Unchecked)
        
        # 完整的 tooltip 信息
        orig_name = getattr(metadata, 'original_filename', file_path.name) if metadata else file_path.name
        tags = getattr(metadata, 'tags', []) if metadata else []
        tags_str = ", ".join(tags[:3]) + ("..." if len(tags) > 3 else "") if tags else "未打标"
        
        # 获取详细信息
        if metadata:
            duration_str = format_duration(metadata.duration) if metadata.duration else "未知"
            sample_rate_str = format_sample_rate(metadata.sample_rate) if metadata.sample_rate else "未知"
            format_str = metadata.format.upper() if metadata.format else file_path.suffix.lstrip('.').upper()
        else:
            duration_str = "未知"
            sample_rate_str = "未知"
            format_str = file_path.suffix.lstrip('.').upper()
        
        tooltip = f"{file_path.name}\n源文件: {orig_name}\n标签: {tags_str}\n时长: {duration_str} | 采样率: {sample_rate_str} | 格式: {format_str}"
        file_item.setToolTip(0, tooltip)
        
        parent_item.addChild(file_item)
        
        # Use normalized path for robust lookup
        self._file_items[os.path.normpath(file_path_str)] = file_item
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 顶部工具栏
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        
        # 内容区域 - 使用 QStackedWidget 切换状态
        self.stack = QStackedWidget()
        
        # 状态0: 加载状态（新增）
        self.loading_state = LoadingStateWidget()
        self.stack.addWidget(self.loading_state)
        
        # 状态1: 空状态
        self.empty_state = EmptyStateWidget()
        self.empty_state.import_clicked.connect(self._on_import_folder)
        # 支持从空状态面板拖入文件夹导入
        self.empty_state.folder_dropped.connect(self._on_import_folders_dropped)
        self.stack.addWidget(self.empty_state)
        
        # 状态2: 扫描进度
        self.scan_progress = ScanProgressWidget()
        self.scan_progress.cancel_clicked.connect(self._on_cancel_scan)
        self.stack.addWidget(self.scan_progress)
        
        # 状态3: 文件列表
        self.file_list_widget = self._create_file_list()
        self.stack.addWidget(self.file_list_widget)
        
        layout.addWidget(self.stack, 1)
        
        # 初始显示加载状态
        self.stack.setCurrentWidget(self.loading_state)
    
    def _create_toolbar(self) -> QWidget:
        """创建紧凑型工具栏 - 统一单行布局"""
        toolbar_container = QWidget()
        toolbar_container.setObjectName("libraryToolbarContainer")
        main_layout = QVBoxLayout(toolbar_container)
        main_layout.setContentsMargins(10, 8, 10, 6)
        main_layout.setSpacing(8)
        
        # 第一行：主工具栏
        from PySide6.QtWidgets import QSizePolicy
        
        self.toolbar_row_main = QWidget()
        layout = QHBoxLayout(self.toolbar_row_main)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        # 1. 导入按钮 (Primary Action)
        self.import_btn = PrimaryPushButton(FluentIcon.FOLDER_ADD, "导入")
        self.import_btn.clicked.connect(self._on_import_folder)
        self.import_btn.setMinimumWidth(82)
        self.import_btn.setFixedHeight(34)
        self.import_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.import_btn)
        
        # 清空库按钮
        self.clear_lib_btn = TransparentToolButton(FluentIcon.DELETE)
        self.clear_lib_btn.setToolTip("清空音效库")
        self.clear_lib_btn.setFixedSize(34, 34)
        layout.addWidget(self.clear_lib_btn)
        self.clear_lib_btn.clicked.connect(self._on_clear_library)

        self.clear_lib_btn_mobile = TransparentToolButton(FluentIcon.DELETE)
        self.clear_lib_btn_mobile.setToolTip("清空音效库")
        self.clear_lib_btn_mobile.setFixedSize(34, 34)
        self.clear_lib_btn_mobile.clicked.connect(self._on_clear_library)
        
        # 2. 搜索框 (Expanding) - 作用于左侧整个音效库
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索音效库... (支持: exp* / tags:脚步声 / duration:>10)")
        self.search_edit.setMinimumWidth(180)
        self.search_edit.setFixedHeight(34)
        self.search_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # 连接搜索信号：点击搜索按钮（searchSignal 会传递文本参数）
        self.search_edit.searchSignal.connect(lambda text: self._on_search())
        # 连接文本变化：实时搜索（textChanged 会传递文本参数）
        self.search_edit.textChanged.connect(lambda text: self._on_search())
        # 连接回车键：按下回车也触发搜索（returnPressed 不传递参数）
        self.search_edit.returnPressed.connect(self._on_search)

        layout.addWidget(self.search_edit, 1)
        
        main_layout.addWidget(self.toolbar_row_main)
        
        # 第二行：搜索提示（可折叠）
        self.search_hint = CaptionLabel("💡 高级搜索: exp* | tags:脚步声 | duration:>10")
        self.search_hint.setTextColor(QColor(150, 150, 150), QColor(150, 150, 150))
        self.search_hint.setVisible(False)  # 默认隐藏
        main_layout.addWidget(self.search_hint)

        self._toolbar_compact_mode = False
        
        # 搜索框获得焦点时显示提示 - 使用 installEventFilter 代替直接覆盖
        self.search_edit.installEventFilter(self)
        self._apply_toolbar_layout_mode()

        return toolbar_container

    def _apply_toolbar_layout_mode(self):
        # 筛选下拉已移除，保留自适应入口以兼容现有调用
        self._toolbar_compact_mode = self.width() < 1320

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_toolbar_layout_mode()

    def _create_file_list(self) -> QWidget:
        """创建简化的文件列表 - 适用于侧边栏"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 选择操作栏
        select_bar = QHBoxLayout()
        select_bar.setSpacing(8)
        
        self.select_all_cb = CheckBox("全选")
        self.select_all_cb.stateChanged.connect(self._on_select_all)
        select_bar.addWidget(self.select_all_cb)
        
        self.stats_label = CaptionLabel("")
        select_bar.addWidget(self.stats_label)
        
        select_bar.addStretch()
        
        self.selected_label = CaptionLabel("已选 0")
        select_bar.addWidget(self.selected_label)
        
        layout.addLayout(select_bar)
        
        # 文件树 - 简化列显示（只显示3列）
        self.tree = TreeWidget()
        self.tree.setHeaderLabels(["名称", "时长", "格式"])  # 只显示关键列
        self.tree.setColumnCount(3)  # 明确设置列数
        
        # 列宽设置
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 50)
        self.tree.setColumnWidth(2, 45)
        
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(False)
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True)
        
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemClicked.connect(self._on_item_clicked)
        
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        
        layout.addWidget(self.tree, 1)
        
        # 创建一个隐藏的 FileInfoCard 以保持 API 兼容性
        self.info_card = FileInfoCard()
        self.info_card.hide()
        
        return container

    def on_file_renamed(self, old_path: str, new_path: str):
        """文件重命名后的回调，同步更新库中的路径"""
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            from transcriptionist_v3.application.library_manager.metadata_extractor import MetadataExtractor
            
            # 1. 更新数据库
            with session_scope() as session:
                audio_file = session.query(AudioFile).filter(AudioFile.file_path == old_path).first()
                if audio_file:
                    audio_file.file_path = new_path
                    audio_file.filename = Path(new_path).name
                    logger.info(f"Database synchronized: {old_path} -> {new_path}")
            
            # 2. 更新内存数据结构 (Audio Files List)
            # Note: _audio_files is List[Path], not List[Tuple[Path, metadata]]
            new_path_obj = Path(new_path)
            for i, path in enumerate(self._audio_files):
                if str(path) == old_path:
                    self._audio_files[i] = new_path_obj
                    break
            
            # Update metadata mapping key AND re-extract metadata to capture ORIGINAL_FILENAME
            if old_path in self._file_metadata:
                self._file_metadata.pop(old_path)
            
            # Re-extract metadata to get the newly written ORIGINAL_FILENAME tag
            try:
                extractor = MetadataExtractor()
                new_metadata = extractor.extract(str(new_path_obj))
                self._file_metadata[new_path] = new_metadata
                logger.info(f"Re-extracted metadata for {new_path_obj.name}")
            except Exception as e:
                logger.warning(f"Failed to re-extract metadata: {e}")
            
            # 3. 更新 UI 树 (O(1) Access using _file_items map)
            norm_old_path = os.path.normpath(old_path)
            norm_new_path = os.path.normpath(new_path)
            
            if norm_old_path in self._file_items:
                item = self._file_items.pop(norm_old_path)
                # Update item appearance
                item.setText(0, new_path_obj.name)
                
                # Update item data
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data:
                    data["path"] = new_path
                    item.setData(0, Qt.ItemDataRole.UserRole, data)
                
                # Update map with new key
                self._file_items[norm_new_path] = item
                
                # Highlight the item to show feedback
                self.tree.scrollToItem(item)
                item.setSelected(True)
                
                # Refresh FileInfoCard if this file is currently selected
                if hasattr(self, 'info_card'):
                    new_metadata = self._file_metadata.get(new_path)
                    self.info_card.update_info(new_path, new_metadata)
                
                logger.info(f"UI Tree synchronized directly: {new_path_obj.name}")
            else:
                # 缓存未命中 - 尝试重建缓存
                logger.debug(f"Cache miss for {norm_old_path}, rebuilding cache...")
                self._rebuild_file_items_cache()
                
                # 重试一次
                if norm_old_path in self._file_items:
                    item = self._file_items.pop(norm_old_path)
                    item.setText(0, new_path_obj.name)
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data:
                        data["path"] = new_path
                        item.setData(0, Qt.ItemDataRole.UserRole, data)
                    self._file_items[norm_new_path] = item
                    logger.info(f"UI Tree synchronized after cache rebuild: {new_path_obj.name}")
                else:
                    # 最后的降级方案：递归查找
                    # 注意：这里降级为 debug，因为文件系统重命名和数据库同步已成功
                    # 树项查找失败仅影响 UI 即时反馈，不影响核心功能
                    logger.debug(f"Tree item not found for {norm_old_path}, using recursive update")
                    root = self.tree.invisibleRootItem()
                    self._update_node_path_recursive(root, old_path, new_path)
                
            # 4. 更新选中集合 (如果在选区中)
            if old_path in self._selected_files:
                self._selected_files.discard(old_path)
                self._selected_files.add(new_path)
                    
        except Exception as e:
            logger.error(f"Failed to update database for renamed file: {e}")

    def _update_node_path_recursive(self, parent_item: QTreeWidgetItem, old_path: str, new_path: str):
        """递归查找并更新节点路径"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("path") == old_path:
                data["path"] = new_path
                child.setData(0, Qt.ItemDataRole.UserRole, data)
                child.setText(0, Path(new_path).name)
                logger.info(f"UI Tree synchronized: {old_path} -> {new_path}")
                return True
            if self._update_node_path_recursive(child, old_path, new_path):
                return True
        return False
    
    def _rebuild_file_items_cache(self):
        """重建文件项缓存 - 遍历树并重新建立映射"""
        self._file_items.clear()
        root = self.tree.invisibleRootItem()
        self._rebuild_cache_recursive(root)
        logger.debug(f"Cache rebuilt with {len(self._file_items)} items")
    
    def _rebuild_cache_recursive(self, parent_item: QTreeWidgetItem):
        """递归重建缓存"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            
            # 如果是文件节点，添加到缓存
            if data and data.get("type") == "file":
                file_path = data.get("path")
                if file_path:
                    norm_path = os.path.normpath(file_path)
                    self._file_items[norm_path] = child
            
            # 递归处理子节点
            self._rebuild_cache_recursive(child)
        
    def _collect_files_recursive(self, item: QTreeWidgetItem) -> List[str]:
        """递归收集节点下的所有文件路径"""
        paths = []
        data = item.data(0, Qt.ItemDataRole.UserRole)
        
        # 如果自己是文件
        if data and data.get("type") == "file":
             path = data.get("path")
             if path:
                 paths.append(path)
        
        # 递归不仅要查子节点，还要注意文件夹节点本身不包含路径信息（除了作为容器）
        # 遍历子节点
        for i in range(item.childCount()):
            child = item.child(i)
            paths.extend(self._collect_files_recursive(child))
            
        return paths

    def on_delete_selected(self):
        """删除库中选中的音效 (仅从数据库移除)"""
        selected_items = self.tree.selectedItems()
        
        if not selected_items:
            # Try to get the item under cursor if context menu invoked it
            # But context menu usually is modal, so we rely on selection.
            # If right click didn't select, we might have 0 items.
            # logger.warning("No items selected for deletion.")
            return
            
        # 收集所有涉及的文件路径（支持文件夹递归）
        paths_to_delete = set()
        
        for item in selected_items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            # 1) 如果是文件夹节点：通过 _collect_files_in_folder 从 _all_file_data 中收集该文件夹（及子文件夹）下的所有文件
            if data and data.get("type") == "folder":
                folder_files = self._collect_files_in_folder(item)
                for info in folder_files:
                    fp = info.get("file_path")
                    if fp:
                        paths_to_delete.add(fp)
            # 2) 兼容旧模式：如果树中存在文件节点，继续使用递归收集
            found_paths = self._collect_files_recursive(item)
            paths_to_delete.update(found_paths)
        
        file_items_count = len(paths_to_delete)
        logger.info(f"Deletion request: {file_items_count} files found in selection")

        if file_items_count == 0:
            NotificationHelper.warning(self, "未选中文件", "所选项目中不包含任何音频文件")
            return
            
        from qfluentwidgets import MessageDialog
        dialog = MessageDialog("确认移除", f"确定从音效库中移除这 {file_items_count} 个音效吗？\n(注意：这仅会从软件中移除记录，不会删除您的物理文件)", self)
        if not dialog.exec():
            return
            
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            
            # Convert set to list for query
            target_paths = list(paths_to_delete)

            with session_scope() as session:
                BATCH_SIZE = 500
                for i in range(0, len(target_paths), BATCH_SIZE):
                    batch = target_paths[i:i + BATCH_SIZE]
                    session.query(AudioFile).filter(AudioFile.file_path.in_(batch)).delete(synchronize_session=False)
                
            logger.info(f"Deleted {len(target_paths)} files from database")
            
            self._selected_files.clear()
            self._selected_folders.clear()  # 清空文件夹选中状态
            self._update_selected_count()
            
            NotificationHelper.success(self, "移除成功", f"已从库中移除 {len(target_paths)} 个文件")
            
            # Emit signal for deleted files
            self.files_deleted.emit(target_paths)

            # 为了与文件夹模式保持一致，删除后重新从数据库加载库结构，避免缓存不一致
            self._load_from_database_async()
            
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            NotificationHelper.error(self, "移除失败", str(e))

    def _show_context_menu(self, pos):
        """显示右键菜单"""
        from qfluentwidgets import RoundMenu, Action
        
        item = self.tree.itemAt(pos)
        if not item:
            return
            
        # 如果当前未选中该项，且没有多选其他项，则选中它
        # Ensures that right-click operations apply to the item under cursor
        if not item.isSelected():
            # If nothing else is selected, or if we want to switch selection to this item
            # Standard behavior: Right click selects the item if it's not part of current selection
            if len(self.tree.selectedItems()) <= 1:
                self.tree.setCurrentItem(item)
                item.setSelected(True)
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        is_file = data.get("type") == "file"
        
        menu = RoundMenu(parent=self)
        
        if is_file:
            # 播放
            play_action = Action(FluentIcon.PLAY, "播放", self)
            play_action.triggered.connect(lambda: self.play_file.emit(data.get("path")))
            menu.addAction(play_action)
            
            # 打开文件夹
            open_folder_action = Action(FluentIcon.FOLDER, "在文件夹中显示", self)
            open_folder_action.triggered.connect(lambda: self._open_file_folder(data.get("path")))
            menu.addAction(open_folder_action)
            
            menu.addSeparator()
            
        # 从库中移除
        delete_action = Action(FluentIcon.DELETE, "从库中移除", self)
        delete_action.triggered.connect(self.on_delete_selected)
        menu.addAction(delete_action)
        
        menu.exec(self.tree.mapToGlobal(pos))

    def _open_file_folder(self, file_path: str):
        """打开文件所在文件夹"""
        import subprocess
        path = Path(file_path).parent
        if path.exists():
            subprocess.run(['explorer', str(path)])

    def _on_import_folder(self):
        """选择并导入文件夹（支持多选）"""
        # 使用 Qt 非原生对话框实现多选
        # 这是最稳定的方案，不依赖 pywin32 或 ctypes
        dialog = QFileDialog(self)
        dialog.setObjectName("folderImportDialog")
        dialog.setStyleSheet(self._build_import_dialog_qss())
        dialog.setWindowTitle("选择音效文件夹（按住 Ctrl/Shift 可多选）")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        
        # 尝试设置初始目录
        if self._library_roots:
            dialog.setDirectory(str(self._library_roots[0]))
        else:
            import os
            desktop = os.path.expanduser("~/Desktop")
            if os.path.exists(desktop):
                dialog.setDirectory(desktop)

        # 核心 Hack: 找到内部视图并开启多选
        from PySide6.QtWidgets import QListView, QTreeView, QAbstractItemView
        
        views = []
        views.extend(dialog.findChildren(QListView))
        views.extend(dialog.findChildren(QTreeView))
        
        for view in views:
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        if dialog.exec():
            folders = dialog.selectedFiles()
            if folders:
                logger.info(f"Selected {len(folders)} folder(s): {folders}")
                self._import_folders_batch(folders)

    def _build_import_dialog_qss(self) -> str:
        tokens = get_theme_tokens(isDarkTheme())
        return f"""
QFileDialog#folderImportDialog,
QFileDialog#folderImportDialog QWidget,
QFileDialog#folderImportDialog QFrame {{
    background-color: {tokens.surface_0};
    color: {tokens.text_primary};
}}

QFileDialog#folderImportDialog QTreeView,
QFileDialog#folderImportDialog QListView {{
    background-color: {tokens.surface_1};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    selection-background-color: {tokens.card_selected};
    selection-color: {tokens.text_primary};
}}

QFileDialog#folderImportDialog QLineEdit,
QFileDialog#folderImportDialog QComboBox {{
    background-color: {tokens.surface_2};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    border-radius: 4px;
    padding: 4px 8px;
}}

QFileDialog#folderImportDialog QPushButton {{
    background-color: {tokens.surface_2};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    border-radius: 4px;
    padding: 4px 10px;
    min-height: 24px;
}}

QFileDialog#folderImportDialog QPushButton:hover {{
    background-color: {tokens.card_hover};
    border-color: {tokens.border_soft};
}}

QFileDialog#folderImportDialog QPushButton:pressed {{
    background-color: {tokens.card_selected};
}}

QFileDialog#folderImportDialog QToolButton {{
    background: transparent;
    color: {tokens.text_secondary};
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 2px;
}}

QFileDialog#folderImportDialog QToolButton:hover {{
    background: {tokens.surface_2};
    border-color: {tokens.border};
}}

QFileDialog#folderImportDialog QHeaderView::section {{
    background-color: {tokens.surface_1};
    color: {tokens.text_secondary};
    border: none;
    border-bottom: 1px solid {tokens.border};
    padding: 5px 8px;
}}

QFileDialog#folderImportDialog QLabel {{
    color: {tokens.text_secondary};
    background: transparent;
}}

QFileDialog#folderImportDialog QSplitter::handle {{
    background: {tokens.border};
}}
"""

    
    def _import_folders_batch(self, folders: list):
        """批量导入多个文件夹"""
        # 归一化去重：避免同一路径被重复导入（大小写/斜杠差异）
        def _norm_folder(path_str: str) -> str:
            try:
                return os.path.normcase(os.path.normpath(str(Path(path_str).resolve())))
            except Exception:
                return os.path.normcase(os.path.normpath(str(path_str)))

        unique_folders = []
        seen = set()
        for folder in folders:
            key = _norm_folder(folder)
            if key in seen:
                continue
            seen.add(key)
            unique_folders.append(folder)

        self._folders_to_import = unique_folders
        self._current_import_index = 0
        self._start_next_folder_import()

    def _on_import_folders_dropped(self, folders: list):
        """从空状态区域拖入文件夹时的导入入口。"""
        if not folders:
            return
        logger.info(f"Import folders via drag-and-drop: {folders}")
        self._import_folders_batch(folders)
    
    def _start_next_folder_import(self):
        """开始导入下一个文件夹"""
        if self._current_import_index < len(self._folders_to_import):
            folder = self._folders_to_import[self._current_import_index]
            logger.info(f"Importing folder {self._current_import_index + 1}/{len(self._folders_to_import)}: {folder}")
            self._start_scan(folder)
        else:
            # All folders imported
            logger.info("All folders imported successfully")
            NotificationHelper.success(
                self,
                "批量导入完成",
                f"已成功导入 {len(self._folders_to_import)} 个文件夹",
                duration=3000
            )
    
    def _start_scan(self, folder_path: str):
        """开始扫描"""
        # 切换到扫描进度状态
        self.stack.setCurrentWidget(self.scan_progress)
        self.scan_progress.progress_bar.setValue(0)
        # 显示当前并行数，方便确认设置是否生效
        try:
            from transcriptionist_v3.core.config import AppConfig
            scan_workers = AppConfig.get("performance.scan_workers") or get_default_scan_workers()
        except Exception:
            scan_workers = get_default_scan_workers()
        self.scan_progress.status_label.setText(f"准备中...（并行数: {scan_workers}）")
        
        # 禁用导入按钮
        self.import_btn.setEnabled(False)
        
        # 创建工作线程
        self._scan_thread = QThread()
        self._scan_worker = QueueScanWorker(folder_path)
        self._scan_worker.moveToThread(self._scan_thread)
        
        # 连接信号
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        
        # 保存根目录
        self._root_folder = Path(folder_path)
        
        # 启动线程
        self._scan_thread.start()

    def _on_cancel_scan(self):
        """取消扫描"""
        if self._scan_worker:
            self._scan_worker.cancel()
        if hasattr(self, "_save_worker") and self._save_worker is not None:
            if hasattr(self._save_worker, "cancel"):
                self._save_worker.cancel()
        self._cleanup_scan_thread()
        self.stack.setCurrentWidget(self.empty_state)
        self.import_btn.setEnabled(True)
    
    def _on_scan_progress(self, scanned: int, total: int, current_file: str):
        """扫描进度更新"""
        self.scan_progress.update_progress(scanned, total, current_file)
    
    def _on_scan_finished(self, stats: dict):
        """扫描完成，启动队列处理线程"""
        self._cleanup_scan_thread()

        total = int(stats.get("total", 0) or 0)
        enqueued = int(stats.get("enqueued", 0) or 0)
        skipped = int(stats.get("skipped", 0) or 0)
        logger.info(
            "Queue scan finished: total=%d, enqueued=%d, skipped=%d",
            total,
            enqueued,
            skipped,
        )

        # 切换到队列处理进度界面
        self.scan_progress.title_label.setText("正在处理导入队列...")
        self.scan_progress._start_time = datetime.now()

        # 启动队列处理线程
        try:
            scan_workers = AppConfig.get("performance.scan_workers") or get_default_scan_workers()
        except Exception:
            scan_workers = get_default_scan_workers()
        batch_size = AppConfig.get("performance.import_batch_size", 5000)
        try:
            batch_size = int(batch_size)
        except (TypeError, ValueError):
            batch_size = 5000
        self.scan_progress.status_label.setText(f"正在准备导入...（并行数: {scan_workers}，批量: {batch_size}）")

        self._save_worker = ImportQueueWorker(root_folder=str(self._root_folder), batch_size=batch_size)
        self._save_thread = QThread()
        self._save_worker.moveToThread(self._save_thread)

        self._save_thread.started.connect(self._save_worker.run)
        self._save_worker.progress.connect(self._on_save_progress)
        self._save_worker.finished.connect(self._on_save_finished)
        self._save_worker.error.connect(self._on_save_error)
        self._save_worker.finished.connect(self._save_thread.quit)
        self._save_worker.error.connect(self._save_thread.quit)
        self._save_thread.finished.connect(self._cleanup_save_thread)

        self._save_thread.start()

    def _on_save_progress(self, current: int, total: int, message: str):
        """保存进度更新"""
        self.scan_progress.update_progress(current, total, message)
    
    def _on_save_finished(self, saved_count: int, skipped_count: int):
        """保存完成"""
        self._cleanup_save_thread()
        folders = getattr(self, "_folders_to_import", None)

        # ===== 批量导入模式：保持在扫描界面，直到所有文件夹完成 =====
        if folders:
            # 当前这个文件夹已完成，移动到下一个
            self._current_import_index = getattr(self, "_current_import_index", 0) + 1

            # 还有剩余文件夹需要导入，继续下一轮扫描（仍然停留在 scan_progress 界面）
            if self._current_import_index < len(folders):
                logger.info(
                    "Folder import %d/%d finished (saved=%d, skipped=%d), starting next folder",
                    self._current_import_index,
                    len(folders),
                    saved_count,
                    skipped_count,
                )
                # 更新标题，让用户知道是第几个文件夹
                self.scan_progress.title_label.setText(
                    f"正在导入第 {self._current_import_index + 1}/{len(folders)} 个文件夹..."
                )
                self._start_next_folder_import()
                return

            # 所有批量导入完成
            logger.info("All batch folders imported. Total folders: %d", len(folders))
            self.import_btn.setEnabled(True)
            self._folders_to_import = []
            self._current_import_index = 0

            # 统一刷新一次库视图，显示所有新导入的文件
            self._load_from_database_async()

            NotificationHelper.success(
                self,
                "批量导入完成",
                f"已成功导入 {len(folders)} 个文件夹",
                duration=3000,
            )
            return

        # ===== 单个文件夹导入：保持原有行为 =====
        self.import_btn.setEnabled(True)
        self._load_from_database_async()
        NotificationHelper.success(
            self,
            "扫描完成",
            f"已成功导入 {saved_count} 个新音效文件，跳过 {skipped_count} 个已存在文件",
        )
    
    def _on_save_error(self, error_msg: str):
        """保存错误"""
        self._cleanup_save_thread()
        self.import_btn.setEnabled(True)
        NotificationHelper.error(self, "保存失败", f"无法保存到数据库: {error_msg}")
        self.stack.setCurrentWidget(self.empty_state)
    
    def _cleanup_save_thread(self):
        """清理保存线程"""
        if hasattr(self, '_save_thread') and self._save_thread is not None:
            self._save_thread.quit()
            self._save_thread.wait()
            self._save_thread.deleteLater()
            self._save_thread = None
        if hasattr(self, '_save_worker') and self._save_worker is not None:
            self._save_worker.deleteLater()
            self._save_worker = None
    
    def _old_scan_finished_backup(self, results: list):
        """扫描完成（旧版同步逻辑，备份）"""
        self._cleanup_scan_thread()
        self.import_btn.setEnabled(True)
        
        # 处理结果
        self._audio_files = []
        self._file_metadata = {}
        # Keep existing structure, will be rebuilt by DB load anyway but scan needs to save first
        self._folder_structure = defaultdict(list) 
        self._selected_files.clear()
        self._selected_folders.clear()
        self._file_items.clear()
        
        # 保存到数据库
        saved_count = 0
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile, LibraryPath
            import hashlib
            
            with session_scope() as session:
                # 记录扫描的路径
                lib_path = session.query(LibraryPath).filter_by(path=str(self._root_folder)).first()
                if not lib_path:
                    lib_path = LibraryPath(
                        path=str(self._root_folder),
                        enabled=True,
                        recursive=True
                    )
                    session.add(lib_path)
                
                lib_path.last_scan_at = datetime.now()
                lib_path.file_count = len(results)
                
                # 批量查询已存在的文件路径（优化性能，避免 SQLite 变量数量限制）
                file_paths = [str(fp) for fp, _ in results]
                existing_paths: set[str] = set()
                BATCH_SIZE = 500
                for i in range(0, len(file_paths), BATCH_SIZE):
                    batch = file_paths[i:i + BATCH_SIZE]
                    rows = (
                        session.query(AudioFile.file_path)
                        .filter(AudioFile.file_path.in_(batch))
                        .all()
                    )
                    existing_paths.update(row.file_path for row in rows)
                
                # 批量准备新文件
                new_files = []
                for file_path, metadata in results:
                    if metadata and str(file_path) not in existing_paths:
                        # 跳过SHA256哈希计算以加速导入（节省20-40秒）
                        # 使用空字符串代替，因为实际上没有用到这个字段做去重
                        
                        # 创建新记录
                        audio_file = AudioFile(
                            file_path=str(file_path),
                            filename=file_path.name,
                            file_size=file_path.stat().st_size,
                            content_hash="",
                            duration=metadata.duration,
                            sample_rate=metadata.sample_rate,
                            bit_depth=metadata.bit_depth or 16,
                            channels=metadata.channels,
                            format=file_path.suffix.lstrip('.').lower(),
                            description=getattr(metadata, 'description', None) or metadata.comment,
                            original_filename=file_path.name  # Save original filename
                        )
                        new_files.append(audio_file)
                
                # 批量插入（比逐个插入快3-8秒）
                if new_files:
                    session.bulk_save_objects(new_files)
                    saved_count = len(new_files)
                
                session.commit()
                logger.info(f"Saved {saved_count} new files to database")
                NotificationHelper.success(self, "扫描完成", f"已成功导入 {saved_count} 个新音效文件")
                
                # 重新加载UI显示
                self._load_from_database_async()
            
        except Exception as e:
            logger.error(f"Failed to save to database: {e}")
            NotificationHelper.error(self, "数据库错误", f"保存扫描结果失败: {e}")
        
        # 切换到文件列表
        self.stack.setCurrentWidget(self.file_list_widget)
        
        # Check if we're in batch import mode
        if hasattr(self, '_folders_to_import') and self._folders_to_import:
            # Batch import mode: move to next folder
            self._current_import_index += 1
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, self._start_next_folder_import)
        else:
            # Single folder mode: ask if user wants to continue
            from qfluentwidgets import MessageDialog
            dialog = MessageDialog(
                "继续导入？",
                "当前文件夹导入完成。您想要继续导入其他文件夹吗？",
                self
            )
            dialog.yesButton.setText("继续导入")
            dialog.cancelButton.setText("完成")
            
            if dialog.exec():
                # Trigger import again
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self._on_import_folder)
            else:
                NotificationHelper.success(
                    self,
                    "导入完成",
                    f"本次共导入 {len(results)} 个文件",
                    duration=3000
                )
    
    def _on_scan_error(self, error_msg: str):
        """扫描错误"""
        self._cleanup_scan_thread()
        self.import_btn.setEnabled(True)
        self.stack.setCurrentWidget(self.empty_state)
        
        NotificationHelper.error(
            self,
            "扫描失败",
            error_msg,
            duration=5000
        )
    
    def _cleanup_scan_thread(self):
        """清理扫描线程"""
        cleanup_thread(self._scan_thread, self._scan_worker)
        self._scan_thread = None
        self._scan_worker = None
    
    def _cleanup_db_load_thread(self):
        """清理数据库加载线程"""
        cleanup_thread(self._db_load_thread, self._db_load_worker)
        self._db_load_thread = None
        self._db_load_worker = None
    
    def _load_from_database_async(self):
        """异步从数据库加载已有的音频文件 (不阻塞UI)"""
        # 创建工作线程
        self._db_load_thread = QThread()
        from transcriptionist_v3.core.config import AppConfig
        threshold = AppConfig.get("performance.db_load_paths_only_threshold", 200000)
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            threshold = 200000
        self._db_load_worker = DatabaseLoadWorker(paths_only=None, paths_only_threshold=threshold)
        self._db_load_worker.moveToThread(self._db_load_thread)
        
        # 连接信号
        self._db_load_thread.started.connect(self._db_load_worker.run)
        self._db_load_worker.finished.connect(self._on_db_load_finished)
        self._db_load_worker.error.connect(self._on_db_load_error)
        self._db_load_worker.progress.connect(self._on_db_load_progress)
        
        self._db_load_thread.start()
        logger.info("Started async database loading")

    def refresh(self):
        """Public refresh method to reload data from database"""
        self._load_from_database_async()
    
    def _on_db_load_progress(self, current: int, total: int, message: str):
        """数据库加载进度"""
        self.loading_state.update_progress(current, total, message)
    
    
    def _on_db_load_error(self, error_msg: str):
        """数据库加载错误"""
        self._cleanup_db_load_thread()
        logger.error(f"Failed to load from database: {error_msg}")

    def _deprecated_update_tree_removed(self):
        # 这个方法duplicate定义被移除以修复崩溃
        pass
    
    def on_translation_applied(self, old_path_str: str, new_path_str: str):
        """处理翻译应用（重命名）同步（从AI翻译页面触发）
        
        支持文件重命名和文件夹重命名。
        """
        import os
        logger.info(f"Translation applied: {old_path_str} -> {new_path_str}")
        
        try:
            from transcriptionist_v3.infrastructure.database.connection import session_scope
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            from transcriptionist_v3.application.library_manager.metadata_extractor import MetadataExtractor
            
            # 检测是否是批量操作（通过检查是否有多个待处理的更新）
            # 这里我们通过一个简单的启发式方法：如果短时间内有多个更新，认为是批量操作
            import time
            current_time = time.time()
            if not hasattr(self, '_last_translation_time'):
                self._last_translation_time = 0
                self._translation_count = 0
            
            time_since_last = current_time - self._last_translation_time
            if time_since_last < 0.1:  # 100ms内的更新认为是批量操作
                self._translation_count += 1
                self._batch_renaming = True
            else:
                self._translation_count = 1
                self._batch_renaming = False
            
            self._last_translation_time = current_time
            
            old_path = Path(old_path_str)
            new_path = Path(new_path_str)
            
            # 判断是文件还是文件夹（注意：磁盘上此时应该已经是新路径了）
            is_dir = new_path.is_dir()
            
            if is_dir:
                # ====== 文件夹重命名 ======
                logger.info(f"Folder rename detected: {old_path_str} -> {new_path_str}")
                
                # 1. 更新数据库中所有受影响的文件路径
                with session_scope() as session:
                    # 查找所有以旧路径开头的文件
                    # 使用 startswith 而不是手写 LIKE，避免路径中包含 %/_ 时产生误匹配
                    prefix = f"{old_path_str}{os.sep}"
                    audio_files = (
                        session.query(AudioFile)
                        .filter(AudioFile.file_path.startswith(prefix))
                        .all()
                    )
                    
                    for audio_file in audio_files:
                        old_file_path = audio_file.file_path
                        new_file_path = old_file_path.replace(old_path_str, new_path_str, 1)
                        audio_file.file_path = new_file_path
                        audio_file.filename = Path(new_file_path).name
                        logger.debug(f"DB updated: {old_file_path} -> {new_file_path}")
                    
                    logger.info(f"Updated {len(audio_files)} file paths in database after folder rename")
                
                # 2. 更新内存数据结构
                # Update _audio_files list
                for i, path in enumerate(self._audio_files):
                    path_str = str(path)
                    if path_str.startswith(old_path_str + os.sep):
                        new_file_path_str = path_str.replace(old_path_str, new_path_str, 1)
                        self._audio_files[i] = Path(new_file_path_str)
                
                # Update _file_metadata keys
                old_metadata_keys = [k for k in self._file_metadata.keys() if k.startswith(old_path_str + os.sep)]
                for old_key in old_metadata_keys:
                    new_key = old_key.replace(old_path_str, new_path_str, 1)
                    self._file_metadata[new_key] = self._file_metadata.pop(old_key)
                
                # Update _file_items dictionary (normalized_path -> QTreeWidgetItem)
                old_item_keys = [k for k in self._file_items.keys() if k.startswith(os.path.normpath(old_path_str) + os.sep)]
                for old_key in old_item_keys:
                    new_key = old_key.replace(os.path.normpath(old_path_str), os.path.normpath(new_path_str), 1)
                    item = self._file_items.pop(old_key)
                    
                    # Update item data
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data:
                        old_item_path = data.get("path", "")
                        new_item_path = old_item_path.replace(old_path_str, new_path_str, 1)
                        data["path"] = new_item_path
                        item.setData(0, Qt.ItemDataRole.UserRole, data)
                        item.setText(0, Path(new_item_path).name)
                        
                        # Update tooltip with new path
                        new_metadata = self._file_metadata.get(new_item_path)
                        if new_metadata:
                            new_path_obj = Path(new_item_path)
                            orig_name = getattr(new_metadata, 'original_filename', new_path_obj.name)
                            tags = getattr(new_metadata, 'tags', [])
                            tags_str = ", ".join(tags) if tags else "未进行AI智能打标"
                            
                            duration = getattr(new_metadata, 'duration', 0)
                            duration_str = format_duration(duration) if duration else "未知"
                            
                            ext = new_path_obj.suffix.upper().lstrip('.')
                            file_size = getattr(new_metadata, 'file_size', 0)
                            size_str = format_file_size(file_size) if file_size else "未知"
                            
                            tooltip = f"""
                            <p><b>名称:</b> {new_path_obj.name}</p>
                            <p><b>源文件名:</b> {orig_name}</p>
                            <p><b>标签:</b> {tags_str}</p>
                            <p><b>时长:</b> {duration_str} | <b>格式:</b> {ext} | <b>大小:</b> {size_str}</p>
                            """
                            item.setToolTip(0, tooltip.strip())
                    
                    self._file_items[new_key] = item
                
                # Update _selected_files set
                old_selected = [f for f in self._selected_files if f.startswith(old_path_str + os.sep)]
                for old_sel in old_selected:
                    self._selected_files.discard(old_sel)
                    new_sel = old_sel.replace(old_path_str, new_path_str, 1)
                    self._selected_files.add(new_sel)
                
                # Update _selected_folders set (如果包含旧路径，替换为新路径)
                # CRITICAL FIX: 需要更新所有以旧路径开头的文件夹路径（包括子文件夹）
                folders_to_update = [f for f in self._selected_folders if f.startswith(old_path_str + os.sep) or f == old_path_str]
                for old_folder in folders_to_update:
                    self._selected_folders.discard(old_folder)
                    if old_folder == old_path_str:
                        # 直接匹配的文件夹
                        self._selected_folders.add(new_path_str)
                    else:
                        # 子文件夹，替换路径前缀
                        new_folder = old_folder.replace(old_path_str, new_path_str, 1)
                        self._selected_folders.add(new_folder)
                        logger.debug(f"Updated folder in _selected_folders: {old_folder} -> {new_folder}")
                
                # 3. 更新 _all_file_data（关键：这是文件索引的基础数据）
                for i, (file_path, metadata) in enumerate(self._all_file_data):
                    path_str = str(file_path)
                    if path_str.startswith(old_path_str + os.sep):
                        new_file_path_str = path_str.replace(old_path_str, new_path_str, 1)
                        new_path_obj = Path(new_file_path_str)
                        self._all_file_data[i] = (new_path_obj, metadata)
                
                # 4. 重建文件夹索引（因为文件夹路径变了）
                # 优化：批量操作时延迟重建索引
                if hasattr(self, "_folder_file_index"):
                    self._folder_index_built = False
                    # 如果正在批量操作，延迟重建索引
                    if getattr(self, '_batch_renaming', False):
                        # 取消之前的延迟重建定时器（如果存在）
                        if hasattr(self, '_delayed_index_rebuild_timer'):
                            self._delayed_index_rebuild_timer.stop()
                        
                        # 创建新的延迟重建定时器（500ms后重建）
                        from PySide6.QtCore import QTimer
                        if not hasattr(self, '_delayed_index_rebuild_timer'):
                            self._delayed_index_rebuild_timer = QTimer(self)
                            self._delayed_index_rebuild_timer.setSingleShot(True)
                            self._delayed_index_rebuild_timer.timeout.connect(self._delayed_rebuild_folder_index)
                        
                        self._delayed_index_rebuild_timer.start(500)
                    else:
                        # 单个操作，立即重建
                        self._build_folder_index()
                
                # 5. 更新UI树中的文件夹节点
                norm_old_path = os.path.normpath(old_path_str)
                root = self.tree.invisibleRootItem()
                self._update_folder_node_recursive(root, norm_old_path, os.path.normpath(new_path_str))
                
                logger.info(f"Folder rename synchronized: {len(old_item_keys)} files updated")
                
            else:
                # ====== 文件重命名 ======
                logger.info(f"File rename detected: {old_path_str} -> {new_path_str}")
                
                # 1. 更新数据库
                with session_scope() as session:
                    audio_file = session.query(AudioFile).filter(AudioFile.file_path == old_path_str).first()
                    if audio_file:
                        audio_file.file_path = new_path_str
                        audio_file.filename = new_path.name
                        logger.info(f"Database synchronized: {old_path_str} -> {new_path_str}")
                
                # 2. 更新内存数据结构
                new_path_obj = Path(new_path_str)
                for i, path in enumerate(self._audio_files):
                    if str(path) == old_path_str:
                        self._audio_files[i] = new_path_obj
                        break
                
                # Update metadata mapping
                if old_path_str in self._file_metadata:
                    self._file_metadata[new_path_str] = self._file_metadata.pop(old_path_str)
                
                # Re-extract metadata to capture ORIGINAL_FILENAME tag
                old_filename = Path(old_path_str).name  # 保存原始文件名（重命名前的文件名）
                try:
                    extractor = MetadataExtractor()
                    new_metadata = extractor.extract(str(new_path_obj))
                    
                    # 确保 original_filename 被正确设置（重命名前的文件名）
                    # 如果从标签中读取的 original_filename 不存在或等于新文件名，设置为旧文件名
                    current_orig = getattr(new_metadata, 'original_filename', None)
                    if not current_orig or current_orig == new_path_obj.name:
                        new_metadata.original_filename = old_filename
                        logger.debug(f"Set original_filename to {old_filename} for {new_path_obj.name}")
                    
                    # 设置 translated_name 为新文件名（翻译后的文件名）
                    # 这样 UI 才知道这个文件已经被翻译了，从而显示 original_filename
                    new_metadata.translated_name = new_path_obj.name
                    logger.debug(f"Set translated_name to {new_path_obj.name}")
                    
                    self._file_metadata[new_path_str] = new_metadata
                    logger.debug(f"Re-extracted metadata for {new_path_obj.name}")
                except Exception as e:
                    logger.warning(f"Failed to re-extract metadata: {e}")
                    # 如果重新提取失败，使用旧的 metadata，但需要更新 original_filename 和 translated_name
                    new_metadata = self._file_metadata.get(new_path_str)
                    if new_metadata:
                        # 确保 original_filename 被设置为旧文件名
                        current_orig = getattr(new_metadata, 'original_filename', None)
                        if not current_orig or current_orig == new_path_obj.name:
                            new_metadata.original_filename = old_filename
                            logger.debug(f"Updated original_filename to {old_filename} in existing metadata")
                        # 设置 translated_name 为新文件名
                        new_metadata.translated_name = new_path_obj.name
                        logger.debug(f"Set translated_name to {new_path_obj.name} in existing metadata")
                
                # 2.5. 更新 _all_file_data（关键：这是文件索引的基础数据）
                for i, (file_path, metadata) in enumerate(self._all_file_data):
                    if str(file_path) == old_path_str:
                        # 使用新提取的 metadata，如果没有则用旧的
                        updated_metadata = new_metadata if new_metadata else metadata
                        
                        # 确保 original_filename 和 translated_name 被正确设置
                        if updated_metadata:
                            # 如果 original_filename 不存在或等于新文件名，设置为旧文件名
                            current_orig = getattr(updated_metadata, 'original_filename', None)
                            if not current_orig or current_orig == new_path_obj.name:
                                updated_metadata.original_filename = old_filename
                                logger.debug(f"Set original_filename to {old_filename} for {new_path_obj.name}")
                            # 设置 translated_name 为新文件名（翻译后的文件名）
                            updated_metadata.translated_name = new_path_obj.name
                            logger.debug(f"Set translated_name to {new_path_obj.name}")
                        else:
                            # 如果没有 metadata，创建一个新的，设置 original_filename 和 translated_name
                            from transcriptionist_v3.domain.models.metadata import AudioMetadata
                            updated_metadata = AudioMetadata()
                            updated_metadata.original_filename = old_filename
                            updated_metadata.translated_name = new_path_obj.name
                            logger.debug(f"Created new metadata with original_filename={old_filename}, translated_name={new_path_obj.name}")
                        
                        self._all_file_data[i] = (new_path_obj, updated_metadata)
                        break
                
                # 2.6. 重建文件夹索引（因为文件路径变了，文件夹索引需要更新）
                # 优化：批量操作时延迟重建索引，避免频繁重建导致性能问题
                if hasattr(self, "_folder_file_index"):
                    self._folder_index_built = False
                    # 如果正在批量操作，延迟重建索引
                    if getattr(self, '_batch_renaming', False):
                        # 取消之前的延迟重建定时器（如果存在）
                        if hasattr(self, '_delayed_index_rebuild_timer'):
                            self._delayed_index_rebuild_timer.stop()
                        
                        # 创建新的延迟重建定时器（500ms后重建，给批量操作时间完成）
                        from PySide6.QtCore import QTimer
                        if not hasattr(self, '_delayed_index_rebuild_timer'):
                            self._delayed_index_rebuild_timer = QTimer(self)
                            self._delayed_index_rebuild_timer.setSingleShot(True)
                            self._delayed_index_rebuild_timer.timeout.connect(self._delayed_rebuild_folder_index)
                        
                        self._delayed_index_rebuild_timer.start(500)
                    else:
                        # 单个操作，立即重建
                        self._build_folder_index()
                
                # 3. 更新UI树 (O(1) Access using _file_items map)
                norm_old_path = os.path.normpath(old_path_str)
                norm_new_path = os.path.normpath(new_path_str)
                
                item = None
                if norm_old_path in self._file_items:
                    item = self._file_items.pop(norm_old_path)
                else:
                    # 如果 _file_items 中没有找到，尝试从树中查找（处理路径规范化问题）
                    logger.debug(f"File item not found in _file_items for {norm_old_path}, searching in tree...")
                    item = self._find_file_item_in_tree(old_path_str)
                    if item:
                        # 从树中找到的项，也需要从 _file_items 中移除（如果存在）
                        # 遍历 _file_items 找到对应的项
                        for key, value in list(self._file_items.items()):
                            if value == item:
                                self._file_items.pop(key)
                                break
                
                if item:
                    # Update item appearance
                    item.setText(0, new_path_obj.name)
                    
                    # Update item data
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data:
                        data["path"] = new_path_str
                        item.setData(0, Qt.ItemDataRole.UserRole, data)
                    
                    # Update tooltip with new filename
                    new_metadata = self._file_metadata.get(new_path_str)
                    if new_metadata:
                        orig_name = getattr(new_metadata, 'original_filename', new_path_obj.name)
                        tags = getattr(new_metadata, 'tags', [])
                        tags_str = ", ".join(tags) if tags else "未进行AI智能打标"
                        
                        duration = getattr(new_metadata, 'duration', 0)
                        duration_str = format_duration(duration) if duration else "未知"
                        
                        ext = new_path_obj.suffix.upper().lstrip('.')
                        file_size = getattr(new_metadata, 'file_size', 0)
                        size_str = format_file_size(file_size) if file_size else "未知"
                        
                        tooltip = f"""
                        <p><b>名称:</b> {new_path_obj.name}</p>
                        <p><b>源文件名:</b> {orig_name}</p>
                        <p><b>标签:</b> {tags_str}</p>
                        <p><b>时长:</b> {duration_str} | <b>格式:</b> {ext} | <b>大小:</b> {size_str}</p>
                        """
                        item.setToolTip(0, tooltip.strip())
                        logger.debug(f"Tooltip updated for {new_path_obj.name}")
                    
                    # Update map with new key
                    self._file_items[norm_new_path] = item
                    
                    # Highlight the item
                    self.tree.scrollToItem(item)
                    item.setSelected(True)
                    
                    # Refresh FileInfoCard if visible
                    if hasattr(self, 'info_card'):
                        self.info_card.update_info(new_path_str, new_metadata)
                    
                    logger.info(f"UI Tree synchronized: {new_path_obj.name}")
                else:
                    # 注意：降级为 debug，因为文件系统重命名和数据库同步已成功
                    # 树项查找失败仅影响 UI 即时显示，刷新后会自动恢复
                    logger.debug(f"Tree item not found for {norm_old_path}, will be updated on refresh")
                
                # Update _selected_files
                if old_path_str in self._selected_files:
                    self._selected_files.discard(old_path_str)
                    self._selected_files.add(new_path_str)
                
                # CRITICAL FIX: 更新 _selected_folders 中所有相关的文件夹路径
                # 文件路径改变后，其父文件夹路径可能也改变了（如果父文件夹被重命名）
                old_parent = Path(old_path_str).parent
                new_parent = Path(new_path_str).parent
                old_parent_str = str(old_parent)
                new_parent_str = str(new_parent)
                
                # 如果父文件夹路径改变了，更新 _selected_folders
                if old_parent_str != new_parent_str and old_parent_str in self._selected_folders:
                    self._selected_folders.discard(old_parent_str)
                    self._selected_folders.add(new_parent_str)
                    logger.debug(f"Updated _selected_folders: {old_parent_str} -> {new_parent_str}")
                
                # 同时检查所有父级文件夹路径（处理嵌套文件夹重命名的情况）
                old_parent_parts = old_parent.parts
                new_parent_parts = new_parent.parts
                if old_parent_parts != new_parent_parts:
                    # 找出路径前缀不同的部分
                    for i in range(min(len(old_parent_parts), len(new_parent_parts))):
                        if old_parent_parts[i] != new_parent_parts[i]:
                            # 从第一个不同的部分开始，所有后续的父文件夹路径都需要更新
                            old_prefix = Path(*old_parent_parts[:i+1])
                            new_prefix = Path(*new_parent_parts[:i+1])
                            old_prefix_str = str(old_prefix)
                            new_prefix_str = str(new_prefix)
                            if old_prefix_str in self._selected_folders:
                                self._selected_folders.discard(old_prefix_str)
                                self._selected_folders.add(new_prefix_str)
                                logger.debug(f"Updated nested folder in _selected_folders: {old_prefix_str} -> {new_prefix_str}")
                            break

                # 刷新当前文件列表，使音效名称 / 原始名 / 标签在「音效列表」面板中立即更新
                # 注意：批量替换时，这个调用会被延迟到批量完成后
                if not getattr(self, '_batch_renaming', False):
                    try:
                        self._update_audio_files_panel_display()
                    except Exception as refresh_err:
                        logger.error(f"Failed to refresh audio files panel after rename: {refresh_err}")
            
        except Exception as e:
            logger.error(f"Error syncing translation applied: {e}", exc_info=True)
    
    def _update_folder_node_recursive(self, parent_item: QTreeWidgetItem, old_path_norm: str, new_path_norm: str):
        """递归查找并更新文件夹节点路径"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole)
            
            if data:
                item_path = data.get("path", "")
                item_path_norm = os.path.normpath(item_path)
                
                # Check if this is the folder we're looking for
                if item_path_norm == old_path_norm:
                    # Update folder node
                    new_path_str = item_path.replace(old_path_norm, new_path_norm, 1)
                    data["path"] = new_path_str
                    child.setData(0, Qt.ItemDataRole.UserRole, data)
                    child.setText(0, Path(new_path_str).name)
                    logger.info(f"Folder node updated: {old_path_norm} -> {new_path_norm}")
                    return True
                
                # Check if this path is a parent of the target
                if old_path_norm.startswith(item_path_norm + os.sep):
                    if self._update_folder_node_recursive(child, old_path_norm, new_path_norm):
                        return True
        
        return False
    
    def _on_clear_library(self):
        """清空音效库"""
        reply = QMessageBox.question(
            self, "确认清空", "是否确认清空所有音效数据？\n此操作不可撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self._db_manager.truncate_tables()
            self._audio_files.clear()
            self._folder_structure.clear()
            self._file_items.clear()
            self._root_folders = []
            
            self._update_tree()
            NotificationHelper.success(self, "清空成功", "音效库已清空")



    def _on_play_clicked(self, file_path: str):
        """播放按钮点击"""
        logger.info(f"Play file: {file_path}")
        self.play_file.emit(file_path)
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """单击选中文件/文件夹，显示详情"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        
        if data.get("type") == "file":
            # 文件被点击：显示详情
            file_path = data.get("path")
            metadata = self._file_metadata.get(file_path)
            self.info_card.update_info(file_path, metadata)
            self.file_selected.emit(file_path)
        elif data.get("type") == "folder":
            # 文件夹被点击：只显示信息卡，不触发音效文件面板
            self.info_card.clear_info()
        else:
            self.info_card.clear_info()
    
    def _collect_indices_for_folder_path(self, folder_path_str: str) -> list:
        """
        根据文件夹路径收集其（及所有子文件夹）下的文件全局索引。
        
        注意：完全基于预构建的 _folder_file_index 映射，不再访问 Qt 树节点，
        避免在大库/多选场景下频繁递归遍历树结构导致卡顿。
        """
        if not folder_path_str:
            return []

        # 延迟构建或补全索引
        if not hasattr(self, "_folder_file_index"):
            self._folder_file_index = {}
        if not getattr(self, "_folder_index_built", False):
            self._build_folder_index()

        from pathlib import Path as _Path

        target_prefix = _Path(folder_path_str)
        indices: list[int] = []
        for folder_key, idx_list in self._folder_file_index.items():
            try:
                _Path(folder_key).relative_to(target_prefix)
                indices.extend(idx_list)
            except ValueError:
                continue

        return indices

    def _collect_indices_in_folder(self, folder_item: QTreeWidgetItem) -> list:
        """
        保留旧接口：从树节点收集该文件夹下的所有文件索引。
        内部复用 _collect_indices_for_folder_path，避免重复实现。
        """
        data = folder_item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "folder":
            return []

        folder_path_str = data.get("path")
        return self._collect_indices_for_folder_path(folder_path_str)

    def _remove_descendant_folders(self, folder_path: str) -> None:
        """移除选中集合中指定文件夹的所有子孙文件夹（含自身）。"""
        if not folder_path:
            return
        base = os.path.normcase(os.path.normpath(folder_path))
        prefix = base if base.endswith(os.sep) else base + os.sep
        to_remove = []
        for p in self._selected_folders:
            try:
                cand = os.path.normcase(os.path.normpath(p))
            except Exception:
                continue
            if cand == base or cand.startswith(prefix):
                to_remove.append(p)
        for p in to_remove:
            self._selected_folders.discard(p)
    
    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """复选框状态改变"""
        if column != 0:
            return
        
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        
        is_checked = item.checkState(0) == Qt.CheckState.Checked
        
        if data.get("type") == "folder":
            folder_path = data.get("path")
            
            # 更新文件夹选中状态
            if is_checked:
                self._selected_folders.add(folder_path)
            else:
                # 取消勾选时，立即移除其子孙文件夹，避免列表残留
                self._remove_descendant_folders(folder_path)
            
            # 延迟执行树子项勾选同步，避免大文件夹下递归 setCheckState 阻塞主线程导致“卡一会”
            # 先让 50ms 后的音效列表刷新完成，再在 80ms 时同步树勾选，列表可先于树显示
            if not hasattr(self, "_pending_tree_sync"):
                self._pending_tree_sync = []
            self._pending_tree_sync.append((item, is_checked))
            if not hasattr(self, "_tree_sync_timer"):
                self._tree_sync_timer = QTimer(self)
                self._tree_sync_timer.setInterval(80)
                self._tree_sync_timer.setSingleShot(True)
                self._tree_sync_timer.timeout.connect(self._flush_pending_tree_sync)
            self._tree_sync_timer.start()
            
            # 使用轻量防抖：在短时间内合并多次勾选操作，只刷新一次音效列表
            if not hasattr(self, "_folder_update_timer"):
                self._folder_update_timer = QTimer(self)
                self._folder_update_timer.setInterval(50)  # 50ms 内多次变更只触发一次刷新
                self._folder_update_timer.setSingleShot(True)
                self._folder_update_timer.timeout.connect(self._update_audio_files_panel_display)
            self._folder_update_timer.start()
        else:
            file_path = data.get("path")
            if is_checked:
                self._selected_files.add(file_path)
            else:
                self._selected_files.discard(file_path)
        
        self._update_selected_count()

    def _flush_pending_tree_sync(self):
        """延迟执行：批量同步树节点勾选状态，避免勾选大文件夹时主线程长时间阻塞。"""
        pending = getattr(self, "_pending_tree_sync", [])
        if not pending:
            return
        self._pending_tree_sync = []
        queue = deque()
        for parent_item, checked in pending:
            try:
                for i in range(parent_item.childCount()):
                    queue.append((parent_item.child(i), checked))
            except Exception as e:
                logger.warning(f"Tree sync enqueue failed: {e}")
        if not queue:
            return

        # 新任务覆盖旧任务，避免积压导致长时间无响应
        self._tree_sync_queue = queue
        self._tree_sync_in_progress = True
        if not hasattr(self, "_tree_sync_worker"):
            self._tree_sync_worker = QTimer(self)
            self._tree_sync_worker.setInterval(0)
            self._tree_sync_worker.timeout.connect(self._process_tree_sync_batch)
        if not self._tree_sync_worker.isActive():
            self._tree_sync_worker.start()

    def _process_tree_sync_batch(self):
        """分批处理树勾选同步，避免一次性递归导致卡顿。"""
        queue = getattr(self, "_tree_sync_queue", None)
        if not queue:
            if hasattr(self, "_tree_sync_worker"):
                self._tree_sync_worker.stop()
            self._tree_sync_in_progress = False
            return

        batch_size = getattr(self, "_tree_sync_batch_size", 200)
        state_checked = Qt.CheckState.Checked
        state_unchecked = Qt.CheckState.Unchecked

        self.tree.blockSignals(True)
        processed = 0
        while queue and processed < batch_size:
            item, checked = queue.popleft()
            item.setCheckState(0, state_checked if checked else state_unchecked)

            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data:
                if data.get("type") == "file":
                    file_path = data.get("path")
                    if checked:
                        self._selected_files.add(file_path)
                    else:
                        self._selected_files.discard(file_path)
                elif data.get("type") == "folder":
                    folder_path = data.get("path")
                    if checked:
                        self._selected_folders.add(folder_path)
                    else:
                        self._selected_folders.discard(folder_path)

            for i in range(item.childCount()):
                queue.append((item.child(i), checked))
            processed += 1
        self.tree.blockSignals(False)

        if not queue:
            self._tree_sync_queue = None
            if hasattr(self, "_tree_sync_worker"):
                self._tree_sync_worker.stop()
            self._tree_sync_in_progress = False
            # 同步结束后再触发一次统计更新，确保计数准确
            self._schedule_selection_update()
    
    def _set_children_checked(self, parent_item: QTreeWidgetItem, checked: bool):
        """递归设置子项选中状态"""
        self.tree.blockSignals(True)
        
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setCheckState(0, state)
            
            data = child.data(0, Qt.ItemDataRole.UserRole)
            if data:
                if data.get("type") == "file":
                    file_path = data.get("path")
                    if checked:
                        self._selected_files.add(file_path)
                    else:
                        self._selected_files.discard(file_path)
                elif data.get("type") == "folder":
                    # 同步更新子文件夹选中状态
                    folder_path = data.get("path")
                    if checked:
                        self._selected_folders.add(folder_path)
                    else:
                        self._selected_folders.discard(folder_path)
            
            if child.childCount() > 0:
                self._set_children_checked(child, checked)
        
        self.tree.blockSignals(False)
    
    def _get_selected_file_paths(self) -> List[str]:
        """
        获取当前选中的文件路径列表（供“已选择”计数和 AI 板块使用）。
        - 全选：返回 _all_file_data 中全部路径；
        - 仅勾选文件夹：按 _folder_file_index 推算这些文件夹及其子文件夹下的所有文件路径；
        - 仅勾选文件：返回 _selected_files。
        这样在单选文件夹时，即使用户未展开树或懒加载未加载叶子，也能正确统计并下发。
        """
        if self._is_all_selected:
            return [str(path) for path, _ in self._all_file_data]
        if self._selected_folders:
            # 直接基于“文件夹路径 -> 文件索引”映射计算，避免频繁在 Qt 树中递归查找节点
            all_indices: List[int] = []
            for folder_path in self._selected_folders:
                indices = self._collect_indices_for_folder_path(folder_path)
                if indices:
                    all_indices.extend(indices)

            unique = sorted(set(all_indices))
            paths: List[str] = []
            for idx in unique:
                if 0 <= idx < len(self._all_file_data):
                    p, _ = self._all_file_data[idx]
                    paths.append(str(p))
            return paths
        return list(self._selected_files)

    def _update_selected_count(self):
        """
        更新选中计数（高频路径，必须轻量）。

        关键优化：
        - 勾选/取消勾选在短时间内可能触发多次（尤其是多选文件夹/层级联动）；
        - 若每次都立刻构建“完整路径列表”并 emit 给 AI 页面，会导致 UI 主线程卡顿；
        - 因此这里改为“防抖合并 + 变更去重”，只在用户操作停顿后计算一次并下发一次。
        """
        self._schedule_selection_update()

    def _selection_state_key(self):
        """用于去重的轻量 key（不构建大列表）。"""
        # 注意：不要在这里生成 paths（会很大且很慢）
        return (
            bool(getattr(self, "_is_all_selected", False)),
            tuple(sorted(getattr(self, "_selected_folders", set()))),
            tuple(sorted(getattr(self, "_selected_files", set()))),
        )

    def _schedule_selection_update(self):
        """合并短时间内的多次勾选变更。"""
        if not hasattr(self, "_selection_update_timer"):
            self._selection_update_timer = QTimer(self)
            # 120ms：足够合并“连点/勾选联动”，又不会让 UI 显得延迟明显
            self._selection_update_timer.setInterval(120)
            self._selection_update_timer.setSingleShot(True)
            self._selection_update_timer.timeout.connect(self._apply_selection_update)
        self._selection_update_timer.start()

    def _apply_selection_update(self):
        """真正执行：计算数量 + 下发 paths（仅在状态有变化时）。"""
        if getattr(self, "_tree_sync_in_progress", False):
            # 树同步尚未完成，延后再计算，避免计数不准
            self._schedule_selection_update()
            return
        key = self._selection_state_key()
        last_key = getattr(self, "_last_selection_state_key", None)
        if last_key == key:
            return
        self._last_selection_state_key = key

        # 先只计算 count 和 selection 描述（轻量），不构建完整 paths 列表
        selection: dict = {"mode": "none", "count": 0}

        if self._is_all_selected:
            total = len(self._all_file_data)
            selection = {"mode": "all", "count": total, "total": total}
        elif self._selected_folders:
            all_indices: List[int] = []
            for folder_path in self._selected_folders:
                indices = self._collect_indices_for_folder_path(folder_path)
                if indices:
                    all_indices.extend(indices)
            unique_indices = sorted(set(all_indices))
            selection = {
                "mode": "folders",
                "count": len(unique_indices),
                "folders": sorted(self._selected_folders),
            }
        else:
            files = list(self._selected_files)
            selection = {"mode": "files", "count": len(files), "files": files}

        self.selected_label.setText(f"已选择 {selection.get('count', 0)} 个文件")

        # v2：优先发轻量选择描述（AI 页面按需解析/取路径）
        self.selection_changed.emit(selection)

        # v1：兼容旧通道。仅在“勾选具体文件且数量不大”时发送完整路径列表，避免大库内存/卡顿风险。
        if selection.get("mode") == "files":
            self.files_checked.emit(selection.get("files", []))
        elif selection.get("mode") == "none":
            # 仅在“清空选择”时发空列表，用于兼容旧页面逻辑
            self.files_checked.emit([])
        else:
            # folders/all 模式下不推送（也不要 emit 空列表，避免旧槽函数把 UI 计数覆盖成 0）
            pass
    
    def _update_audio_files_panel_display(self):
        """根据勾选状态更新音效文件面板显示"""
        # 若当前有待处理的批量更新，优先合并后再执行（简单防抖由 _on_item_changed 控制）
        if not self._selected_folders:
            # 没有选中文件夹，清空音效文件面板
            self.folder_clicked.emit("", [])
            # 重置上次的显示 key，避免“取消后再次选择同一批文件夹”被误判为无变化
            setattr(self, "_last_folder_display_key", None)
            return
        
        # 收集所有选中文件夹的文件索引（惰性加载用）
        # 直接按路径用 _folder_file_index 收集，避免 _find_folder_item_by_path 全树递归导致卡顿
        all_indices: List[int] = []
        folder_names = []
        for folder_path in self._selected_folders:
            indices = self._collect_indices_for_folder_path(folder_path)
            if indices:
                all_indices.extend(indices)
                folder_names.append(Path(folder_path).name)
        
        # 去重索引
        unique_indices = sorted(set(all_indices))
        
        # 生成显示标题
        if len(folder_names) == 1:
            display_path = folder_names[0]
        elif len(folder_names) <= 3:
            display_path = ", ".join(folder_names)
        else:
            display_path = f"{folder_names[0]}, {folder_names[1]} +{len(folder_names)-2}个"
        
        # 如果结果和上一次完全一致，则不再重复刷新，避免多次无意义重建模型
        last_key = getattr(self, "_last_folder_display_key", None)
        current_key = (tuple(sorted(self._selected_folders)), tuple(unique_indices))
        if last_key == current_key:
            return
        self._last_folder_display_key = current_key

        # 发送信号给音效文件面板（传递全局索引列表，具体数据由面板懒加载）
        logger.info(f"Update audio files panel: {len(unique_indices)} files from {len(folder_names)} folders")
        self.folder_clicked.emit(display_path, unique_indices)
    
    def _find_file_item_in_tree(self, file_path: str) -> Optional[QTreeWidgetItem]:
        """从树中查找文件项（用于处理 _file_items 中找不到的情况）"""
        def search_recursive(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if data and data.get("type") == "file":
                    if data.get("path") == file_path:
                        return child
                # 递归搜索子节点
                result = search_recursive(child)
                if result:
                    return result
            return None
        
        root = self.tree.invisibleRootItem()
        return search_recursive(root)
    
    def _find_folder_item_by_path(self, folder_path: str) -> Optional[QTreeWidgetItem]:
        """根据路径查找文件夹节点"""
        for i in range(self.tree.topLevelItemCount()):
            root_item = self.tree.topLevelItem(i)
            result = self._find_folder_item_recursive(root_item, folder_path)
            if result:
                return result
        return None
    
    def _find_folder_item_recursive(self, item: QTreeWidgetItem, folder_path: str) -> Optional[QTreeWidgetItem]:
        """递归查找文件夹节点"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "folder" and data.get("path") == folder_path:
            return item
        
        for i in range(item.childCount()):
            child = item.child(i)
            result = self._find_folder_item_recursive(child, folder_path)
            if result:
                return result
        
        return None
    
    def get_selected_files(self) -> List[str]:
        """获取选中的文件路径列表 - 支持虚拟全选与勾选文件夹"""
        return self._get_selected_file_paths()

    def _on_select_all(self, state):
        """全选/取消全选 - 优化版本，不加载所有文件"""
        checked = state == Qt.CheckState.Checked.value
        
        if checked:
            # 标记全选状态（不加载所有文件到 UI）
            self._is_all_selected = True
            # 计数与下发交给防抖合并逻辑，避免全选时重复触发多次大列表生成
            self._schedule_selection_update()
            
            # 清空音效文件面板（全选不显示特定文件夹）
            self.folder_clicked.emit("", [])
            
            logger.info(f"All {len(self._all_file_data)} files selected (virtual selection)")
        else:
            # 取消全选
            self._is_all_selected = False
            self._selected_files.clear()
            self._selected_folders.clear()
            
            # 取消 UI 中已加载文件的选中状态
            self.tree.blockSignals(True)
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                # 大树节点取消选中使用分批同步，避免阻塞
                if not hasattr(self, "_pending_tree_sync"):
                    self._pending_tree_sync = []
                self._pending_tree_sync.append((item, False))
            self.tree.blockSignals(False)
            if getattr(self, "_pending_tree_sync", []):
                if not hasattr(self, "_tree_sync_timer"):
                    self._tree_sync_timer = QTimer(self)
                    self._tree_sync_timer.setInterval(80)
                    self._tree_sync_timer.setSingleShot(True)
                    self._tree_sync_timer.timeout.connect(self._flush_pending_tree_sync)
                self._tree_sync_timer.start()
            
            self._schedule_selection_update()
            
            # 清空音效文件面板
            self.folder_clicked.emit("", [])
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """双击播放"""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "file":
            file_path = data.get("path")
            logger.info(f"Play file: {file_path}")
            self.play_file.emit(file_path)
    
    def eventFilter(self, obj, event):
        """事件过滤器 - 处理搜索框焦点"""
        if obj == self.search_edit:
            from PySide6.QtCore import QEvent
            if event.type() == QEvent.Type.FocusIn:
                self.search_hint.setVisible(True)
            elif event.type() == QEvent.Type.FocusOut:
                if not self.search_edit.text():
                    self.search_hint.setVisible(False)
        
        return super().eventFilter(obj, event)

    def _on_search(self, *args):
        """
        搜索触发入口：使用防抖计时器，避免在用户快速输入/删除时多次全量搜索。
        所有连接到该槽的信号（searchSignal/textChanged/returnPressed/下拉框变化）
        只会启动或重置计时器，实际搜索逻辑在 _execute_search 中完成。
        """
        if hasattr(self, "_search_timer"):
            self._search_timer.stop()
            self._search_timer.start()
    
    def _execute_search(self):
        """真正执行搜索逻辑 - 使用后端 SearchEngine"""
        text = self.search_edit.text().strip()
        
        # 1. 如果搜索框为空，恢复默认视图（懒加载模式）
        if not text:
            if not self._lazy_load_enabled:
                self._lazy_load_enabled = True
                self._update_tree_lazy() # 重新构建并将懒加载模式打开
            return
            
        # 2. 如果有搜索内容，切换到"全量搜索结果视图"（禁用懒加载）
        self._lazy_load_enabled = False
        
        try:
            # 构建查询字符串
            query_str = text
            
            # 执行搜索
            query = self._search_engine.parse_query(query_str)
            # 搜索全部数据库
            result = self._search_engine.execute_sync(query)
            matched_ids = set(result.file_ids)
            
            logger.info(f"Search '{query_str}' found {len(matched_ids)} matches")
            
            # 3. 重建树，只包含匹配项
            self.tree.clear()
            self._file_items.clear()
            
            # 重建文件夹结构
            self._build_folder_tree_structure()
            
            # 填充匹配的文件
            # 痛点：我们需要知道 ID -> FilePath 的反向映射，或者遍历 _all_file_data
            # 为提高效率，我们可以遍历 _all_file_data，因为我们有 _file_path_to_id 映射
            
            count = 0
            # 优化：仅当有匹配时才遍历
            if matched_ids:
                # 预先获取 ID 映射
                path_id_map = self._file_path_to_id
                matched_path_set = None
                if not path_id_map:
                    # paths_only 模式下没有缓存映射：按需查一次 DB 获取匹配路径集合
                    try:
                        from transcriptionist_v3.infrastructure.database.models import AudioFile
                        with session_scope() as session:
                            rows = (
                                session.query(AudioFile.id, AudioFile.file_path)
                                .filter(AudioFile.id.in_(list(matched_ids)))
                                .all()
                            )
                        matched_path_set = {row.file_path for row in rows}
                    except Exception as e:
                        logger.error(f"Failed to resolve matched paths: {e}")
                        matched_path_set = set()
                
                # 冻结刷新
                self.tree.setUpdatesEnabled(False)
                
                for file_path, metadata in self._all_file_data:
                    path_str = str(file_path)
                    fid = path_id_map.get(path_str) if path_id_map else None
                    
                    if (fid in matched_ids) or (matched_path_set is not None and path_str in matched_path_set):
                        # 是匹配项，添加到树中
                        # 确保 file_path 是 Path 对象
                        if not isinstance(file_path, Path):
                            file_path = Path(file_path)
                            
                        # 添加到对应文件夹
                        parent_path = file_path.parent
                        parent_item = self._folder_items.get(str(parent_path))
                        
                        if parent_item:
                            self._create_file_item(parent_item, file_path)
                            # 展开该文件的父文件夹路径
                            temp = parent_item
                            while temp:
                                temp.setExpanded(True)
                                temp = temp.parent()
                            count += 1
                
                self.tree.setUpdatesEnabled(True)
            
            # 更新统计
            self.stats_label.setText(f"搜索结果: {count} 个")
            
            # 隐藏没有子项的文件夹
            self._hide_empty_folders()

        except Exception as e:
            logger.error(f"Search failed: {e}", exc_info=True)
            self.stats_label.setText("搜索出错")

    def _hide_empty_folders(self):
        """隐藏空文件夹 (用于搜索结果视图)"""
        if not self._folder_items:
            return
            
        def check_vis(item):
            has_visible_child = False
            for i in range(item.childCount()):
                child = item.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                
                if data and data.get("type") == "file":
                    # 文件肯定可见（因为我们只添加了匹配的）
                    has_visible_child = True
                else:
                    # 文件夹，递归检查
                    if check_vis(child):
                        has_visible_child = True
            
            item.setHidden(not has_visible_child)
            return has_visible_child

        # 从根节点开始检查
        for i in range(self.tree.topLevelItemCount()):
            check_vis(self.tree.topLevelItem(i))

    def _show_all_items(self):
        # Deprecated by new logic
        pass

    def _recursive_set_hidden(self, item, hidden):
        # Deprecated
        pass

    def _filter_tree_by_ids(self, matched_ids):
        # Deprecated
        pass
    
    def _on_ai_search_clicked(self):
        """跳转到 AI 检索页面"""
        files = self._get_selected_file_paths()
        if not files:
            NotificationHelper.warning(
                self,
                "提示",
                "请先勾选要AI检索的文件"
            )
            return
            
        logger.info(f"Requesting AI Search for {len(files)} files")
        self.request_ai_search.emit(files)
        NotificationHelper.info(
            self,
            "AI检索",
            f"已选择 {len(files)} 个文件，请切换到AI检索页面"
        )
    
    def _on_ai_translate(self):
        """AI翻译选中的文件"""
        files = self._get_selected_file_paths()
        if not files:
            NotificationHelper.warning(
                self,
                "提示",
                "请先勾选要翻译的文件"
            )
            return
        
        self.files_checked.emit(files)
        NotificationHelper.info(
            self,
            "AI翻译",
            f"已选择 {len(files)} 个文件，请切换到AI翻译页面"
        )
    
    def get_all_files(self) -> list:
        """获取所有文件列表"""
        return [str(f) for f in self._audio_files]
    
    def get_file_metadata(self, file_path: str):
        """获取文件元数据"""
        return self._file_metadata.get(file_path)

    def _on_clear_library(self):
        """
        清空按钮（按选择范围执行）：
        - 若用户点击了“全选”：清空整个库（树/列表/右侧面板全部清空）
        - 若未全选但勾选了某个音效文件夹：仅清空这些文件夹下的音效数据（不删硬盘文件）
        - 若既未全选也未选择任何文件夹：不执行，并提示用户先选择
        """
        # 1) 范围判定
        is_all = bool(getattr(self, "_is_all_selected", False))
        selected_folders = sorted(getattr(self, "_selected_folders", set()) or [])

        if (not is_all) and (not selected_folders):
            NotificationHelper.warning(self, "提示", "请先选择要清空的音效文件夹，或勾选“全选”以清空整个库。")
            return

        # 2) 确认弹窗（根据范围显示不同文案）
        from qfluentwidgets import MessageDialog
        if is_all:
            title = "清空音效库"
            content = "确定要清空所有音效库数据吗？\n此操作将删除数据库中的所有记录，但不会删除硬盘上的文件。"
            yes_text = "确定清空"
        else:
            title = "清空选中文件夹"
            if len(selected_folders) == 1:
                content = f"确定要清空该文件夹下的音效数据吗？\n{selected_folders[0]}\n\n此操作不会删除硬盘上的文件。"
            else:
                content = f"确定要清空所选 {len(selected_folders)} 个文件夹下的音效数据吗？\n此操作不会删除硬盘上的文件。"
            yes_text = "确定清空所选"

        dialog = MessageDialog(title, content, self)
        dialog.yesButton.setText(yes_text)
        dialog.cancelButton.setText("取消")
        if not dialog.exec():
            return

        # 3) 执行清理（数据库 + 内存 + UI）
        try:
            from pathlib import Path as _Path
            import os
            from sqlalchemy import or_
            from transcriptionist_v3.infrastructure.database.models import AudioFile, LibraryPath, ImportQueue

            def _norm(p: str) -> str:
                try:
                    return os.path.normcase(os.path.normpath(str(p)))
                except Exception:
                    return str(p)

            if is_all:
                # --- A. 全库清空 ---
                with session_scope() as session:
                    session.query(AudioFile).delete()
                    session.query(LibraryPath).delete()
                    # 关键：同时清空导入队列，否则会出现“扫描全跳过但库为空”的假导入状态
                    session.query(ImportQueue).delete()
                    session.commit()

                # 内存结构彻底清空
                self._audio_files = []
                self._library_roots = []
                self._file_metadata = {}
                self._folder_structure.clear()
                self._selected_files.clear()
                self._selected_folders.clear()
                self._all_file_data = []
                self._file_items.clear()
                self._folder_items = {}
                self._folder_file_index = {}
                self._folder_index_built = False
                self._file_path_to_id = {}
                try:
                    self._file_info_cache.clear()
                except Exception:
                    self._file_info_cache = {}
                setattr(self, "_last_folder_display_key", None)
                setattr(self, "_last_selection_state_key", None)

                # UI 清空
                self.tree.clear()
                self.stats_label.setText("")
                self.selected_label.setText("已选择 0 个文件")
                self.info_card.clear_info()
                self.stack.setCurrentWidget(self.empty_state)

                # 重置全选按钮状态（避免 UI 显示仍为全选）
                self.select_all_cb.blockSignals(True)
                self.select_all_cb.setChecked(False)
                self.select_all_cb.blockSignals(False)
                self._is_all_selected = False

                # 清空右侧音效列表面板
                self.folder_clicked.emit("", [])

                # Emit signals
                self.files_checked.emit([])  # Clear selection in other pages
                self.library_cleared.emit()  # Notify global clear

                NotificationHelper.success(self, "已清空", "音效库已重置")
                logger.info("Library cleared by user (all)")
                return

            # --- B. 仅清空选中文件夹 ---
            # 4) 数据库：删除选中文件夹（含子目录）下的音效记录 + 导入队列
            folder_norms = [_norm(p) for p in selected_folders]

            def _prefix_variants(folder_path: str) -> list[str]:
                # 支持 both slash
                p = str(folder_path).rstrip("\\/") + os.sep
                p_alt = p.replace("\\", "/") if "\\" in p else p.replace("/", "\\")
                return [p, p_alt]

            like_clauses = []
            queue_like_clauses = []
            for folder_path in selected_folders:
                for prefix in _prefix_variants(folder_path):
                    like_clauses.append(AudioFile.file_path.like(prefix + "%"))
                    queue_like_clauses.append(ImportQueue.file_path.like(prefix + "%"))

            with session_scope() as session:
                if like_clauses:
                    session.query(AudioFile).filter(or_(*like_clauses)).delete(synchronize_session=False)
                if queue_like_clauses:
                    session.query(ImportQueue).filter(or_(*queue_like_clauses)).delete(synchronize_session=False)

                # 如果清空的是库根路径，同时从 LibraryPath 移除（否则下次刷新/扫描会再出现）
                roots = [str(r) for r in (getattr(self, "_library_roots", []) or [])]
                roots_norm = {_norm(r): r for r in roots}
                to_remove_roots = []
                for folder_path in selected_folders:
                    key = _norm(folder_path)
                    if key in roots_norm:
                        to_remove_roots.append(roots_norm[key])
                if to_remove_roots:
                    # 双斜杠兼容
                    rp = set(to_remove_roots)
                    rp |= {p.replace("\\", "/") for p in list(rp)}
                    rp |= {p.replace("/", "\\") for p in list(rp)}
                    session.query(LibraryPath).filter(LibraryPath.path.in_(list(rp))).delete(synchronize_session=False)
                session.commit()

            # 5) 内存：从 _all_file_data 中移除这些文件夹下的条目，并更新 roots
            def _is_under_any_selected(file_path_str: str) -> bool:
                fp = _norm(file_path_str)
                for folder_norm, folder_raw in zip(folder_norms, selected_folders):
                    # 以 folder 为前缀（含子目录）
                    base = folder_norm.rstrip("\\/") + os.sep
                    if fp == folder_norm or fp.startswith(base):
                        return True
                return False

            new_all = []
            for file_path, metadata in (getattr(self, "_all_file_data", []) or []):
                if not _is_under_any_selected(str(file_path)):
                    new_all.append((file_path, metadata))
            self._all_file_data = new_all

            # roots 更新（被移除的根从列表中删除）
            if getattr(self, "_library_roots", None):
                keep_roots = []
                for r in self._library_roots:
                    if _norm(str(r)) not in set(folder_norms):
                        keep_roots.append(r)
                self._library_roots = keep_roots

            # 清理索引/缓存并重建树（懒加载结构）
            self._file_items.clear()
            self._folder_items = {}
            self._folder_file_index = {}
            self._folder_index_built = False
            self._file_path_to_id = {}
            try:
                self._file_info_cache.clear()
            except Exception:
                self._file_info_cache = {}
            setattr(self, "_last_folder_display_key", None)
            setattr(self, "_last_selection_state_key", None)

            # 清理选择状态（清空后不保留旧勾选）
            self._selected_files.clear()
            self._selected_folders.clear()
            self._is_all_selected = False
            self.select_all_cb.blockSignals(True)
            self.select_all_cb.setChecked(False)
            self.select_all_cb.blockSignals(False)

            # UI：重建文件夹树结构/统计，并清空右侧面板
            self.folder_clicked.emit("", [])
            if not self._all_file_data:
                self.tree.clear()
                self.stats_label.setText("")
                self.selected_label.setText("已选择 0 个文件")
                self.info_card.clear_info()
                self.stack.setCurrentWidget(self.empty_state)
            else:
                # 只更新树结构（不加载文件）
                self._update_tree_lazy()
                self.info_card.clear_info()

            # Emit（局部清空不触发全局 library_cleared，避免其它页面误认为全库清空）
            self.files_checked.emit([])  # 清掉旧的“文件勾选”通道
            self.selection_changed.emit({"mode": "none", "count": 0})

            NotificationHelper.success(self, "已清空", "已清空所选文件夹下的音效数据")
            logger.info(f"Library cleared by user (folders={len(selected_folders)})")

        except Exception as e:
            logger.error(f"Failed to clear library: {e}", exc_info=True)
            NotificationHelper.error(self, "错误", f"清空失败: {e}")

    # ==================== 懒加载相关方法 ====================
    
    def _update_tree_lazy(self):
        """更新文件树 - 只构建文件夹结构，不加载文件"""
        self.tree.clear()
        self._file_items.clear()
        self._loaded_count = 0
        
        # 重置全选状态
        self.select_all_cb.blockSignals(True)
        self.select_all_cb.setChecked(False)
        self.select_all_cb.blockSignals(False)
        self._selected_files.clear()
        self._selected_folders.clear()
        self._update_selected_count()
        
        if not self._all_file_data:
            self.stack.setCurrentWidget(self.empty_state)
            return
        
        # 直接构建文件夹结构
        self._build_folder_tree_structure()
        
        # 更新统计信息
        self._update_stats()
        
        # 切换到树视图
        self.stack.setCurrentWidget(self.file_list_widget)
    
    def _build_folder_tree_structure(self):
        """构建文件夹树结构（不包含文件）"""
        # 按根目录分组文件
        files_by_root = defaultdict(list)
        
        logger.info(f"Building folder tree for {len(self._all_file_data)} files, {len(self._library_roots)} roots")
        
        for file_path, metadata in self._all_file_data:
            # 找到文件所属的根目录
            path_obj = Path(file_path) if not isinstance(file_path, Path) else file_path
            root_found = None
            
            for root in self._library_roots:
                try:
                    path_obj.relative_to(root)
                    root_found = root
                    break
                except ValueError:
                    continue
            
            if root_found:
                files_by_root[root_found].append((path_obj, metadata))
            else:
                logger.warning(f"File {path_obj} does not belong to any root!")
        
        # 为每个根目录创建文件夹树
        self._folder_items = {}  # {folder_path_str: QTreeWidgetItem}
        
        for root_path in self._library_roots:
            files = files_by_root.get(root_path, [])
            
            if not files:
                # 即使没有文件，也创建根节点
                logger.warning(f"No files found for root: {root_path}")
                root_item = QTreeWidgetItem([root_path.name, "", ""])
                root_item.setIcon(0, FluentIcon.FOLDER.icon())
                root_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(root_path)})
                root_item.setFont(0, QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
                root_item.setCheckState(0, Qt.CheckState.Unchecked)
                self.tree.addTopLevelItem(root_item)
                self._folder_items[str(root_path)] = root_item
                root_item.setExpanded(True)
                continue
            
            # 创建根节点
            root_item = QTreeWidgetItem([root_path.name, "", ""])
            root_item.setIcon(0, FluentIcon.FOLDER.icon())
            root_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(root_path)})
            root_item.setFont(0, QFont("Microsoft YaHei UI", 10, QFont.Weight.Bold))
            root_item.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(root_item)
            self._folder_items[str(root_path)] = root_item
            
            # 收集所有子文件夹
            folders = set()
            for file_path, _ in files:
                parent = file_path.parent
                while parent != root_path:
                    folders.add(parent)
                    parent = parent.parent
                    if parent == parent.parent:
                        break
            
            # 按层级排序文件夹
            sorted_folders = sorted(folders, key=lambda p: (len(p.parts), str(p)))
            
            # 创建文件夹节点
            for folder_path in sorted_folders:
                parent_path = folder_path.parent
                parent_item = self._folder_items.get(str(parent_path), root_item)
                
                folder_item = QTreeWidgetItem([folder_path.name, "", ""])
                folder_item.setIcon(0, FluentIcon.FOLDER.icon())
                folder_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "folder", "path": str(folder_path)})
                folder_item.setCheckState(0, Qt.CheckState.Unchecked)
                
                if parent_item:
                    parent_item.addChild(folder_item)
                    self._folder_items[str(folder_path)] = folder_item
                else:
                    logger.warning(f"Parent item not found for folder: {folder_path}")
            
            root_item.setExpanded(True)
        
        # 同步重建“文件夹 -> 文件索引”映射，供 _collect_files_in_folder 使用
        self._build_folder_index()

    def _build_folder_index(self):
        """
        构建“文件夹路径 -> 文件在 _all_file_data 中索引列表”的映射。

        这样在勾选文件夹时，不需要再对所有文件做 relative_to 判断，可显著降低 CPU 和 IO。
        """
        self._folder_file_index = {}
        from pathlib import Path as _Path

        for idx, (file_path, metadata) in enumerate(self._all_file_data):
            path_obj = _Path(file_path) if not isinstance(file_path, _Path) else file_path
            parent = path_obj.parent
            folder_key = str(parent)
            self._folder_file_index.setdefault(folder_key, []).append(idx)

        self._folder_index_built = True
    
    def _delayed_rebuild_folder_index(self):
        """延迟重建文件夹索引（用于批量操作优化）"""
        logger.info("Delayed rebuild folder index after batch operation")
        self._build_folder_index()
        # 清除批量操作标志
        self._batch_renaming = False
        # 批量操作完成后，刷新音效文件面板
        try:
            self._update_audio_files_panel_display()
        except Exception as e:
            logger.error(f"Failed to refresh audio files panel after batch operation: {e}")

    # ========= 提供给音效列表的懒加载接口 =========
    def get_file_info_by_index(self, index: int) -> Optional[dict]:
        """
        根据全局索引返回文件信息 dict。
        仅用于 AudioFilesPanel 懒加载显示，必要时会按需查询数据库。
        """
        try:
            if index < 0 or index >= len(self._all_file_data):
                return None
            from pathlib import Path as _Path
            file_path, metadata = self._all_file_data[index]
            path_obj = _Path(file_path) if not isinstance(file_path, _Path) else file_path
            
            # 1) 有元数据就直接返回
            if metadata is not None:
                return {
                    "file_path": str(path_obj),
                    "filename": path_obj.name,
                    "duration": getattr(metadata, "duration", 0),
                    "file_size": getattr(metadata, "file_size", 0),
                    "format": path_obj.suffix.lstrip(".").lower(),
                    "sample_rate": getattr(metadata, "sample_rate", 0),
                    "channels": getattr(metadata, "channels", 0),
                    "original_filename": getattr(metadata, "original_filename", path_obj.name),
                    "translated_name": getattr(metadata, "translated_name", None),
                    "tags": getattr(metadata, "tags", []),
                }
            
            # 2) 元数据未加载：从 DB 按需读取（带缓存）
            return self._get_file_info_from_db(str(path_obj))
        except Exception as e:
            logger.warning(f"get_file_info_by_index failed for index={index}: {e}")
            return None

    def _get_file_info_from_db(self, file_path: str) -> Optional[dict]:
        """按需从数据库读取文件信息（带 LRU 缓存），避免一次性加载全库元数据。"""
        if not file_path:
            return None
        cached = self._file_info_cache.get(file_path)
        if isinstance(cached, dict):
            # 刷新 LRU
            self._file_info_cache.move_to_end(file_path, last=True)
            return cached

        try:
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            with session_scope() as session:
                query_paths = {file_path}
                if "\\" in file_path:
                    query_paths.add(file_path.replace("\\", "/"))
                row = (
                    session.query(AudioFile)
                    .filter(AudioFile.file_path.in_(list(query_paths)))
                    .first()
                )
                if not row:
                    return None
                info = {
                    "file_path": row.file_path,
                    "filename": row.filename,
                    "duration": getattr(row, "duration", 0) or 0,
                    "file_size": getattr(row, "file_size", 0) or 0,
                    "format": (row.format or "").lower(),
                    "sample_rate": getattr(row, "sample_rate", 0) or 0,
                    "channels": getattr(row, "channels", 0) or 0,
                    "original_filename": getattr(row, "original_filename", row.filename),
                    "translated_name": getattr(row, "translated_name", None),
                    "tags": [t.tag for t in getattr(row, "tags", [])],
                }
        except Exception as e:
            logger.warning(f"Failed to query db for file info: {e}")
            return None

        # 写入缓存
        self._file_info_cache[file_path] = info
        if len(self._file_info_cache) > self._file_info_cache_limit:
            self._file_info_cache.popitem(last=False)
        return info

    def get_file_path_by_index(self, index: int) -> Optional[str]:
        """为 AI 页面提供的轻量接口：通过全局索引取 file_path。"""
        info = self.get_file_info_by_index(index)
        if isinstance(info, dict):
            p = info.get("file_path")
            return str(p) if p else None
        return None

    def get_indices_by_paths(self, paths: List[str]) -> List[int]:
        """
        根据文件路径列表返回在库中的全局索引列表（用于标签选中 → 音效列表）。
        不在库中的路径会被忽略。
        """
        if not paths:
            return []
        path_set = {str(p).strip() for p in paths if p}
        indices: List[int] = []
        for idx, (file_path, _) in enumerate(self._all_file_data):
            if str(file_path).strip() in path_set:
                indices.append(idx)
        return sorted(set(indices))

    def resolve_selection_to_paths(self, selection: dict) -> List[str]:
        """
        将 selection_changed 的轻量选择描述解析为路径列表。
        注意：这是“按需”重活，只应在用户点击开始任务时调用，而不是在勾选时调用。
        """
        mode = selection.get("mode")
        if mode == "all":
            return [str(path) for path, _ in self._all_file_data]
        if mode == "files":
            return list(selection.get("files", []))
        if mode == "folders":
            folders = selection.get("folders") or []
            all_indices: List[int] = []
            for folder_path in folders:
                indices = self._collect_indices_for_folder_path(folder_path)
                if indices:
                    all_indices.extend(indices)
            unique = sorted(set(all_indices))
            paths: List[str] = []
            for idx in unique:
                if 0 <= idx < len(self._all_file_data):
                    p, _ = self._all_file_data[idx]
                    paths.append(str(p))
            return paths
        return []
    
    def _load_next_batch(self):
        """加载下一批文件"""
        if self._is_loading or not self._lazy_load_enabled:
            return
        
        self._is_loading = True
        
        start = self._loaded_count
        end = min(start + self._batch_size, len(self._all_file_data))
        
        if start >= end:
            self._is_loading = False
            return
        
        logger.info(f"Loading batch: {start}-{end} of {len(self._all_file_data)}")
        
        # 加载这批文件
        for i in range(start, end):
            file_path, metadata = self._all_file_data[i]
            if not isinstance(file_path, Path):
                file_path = Path(file_path)
            self._create_file_item_lazy(file_path, metadata)
        
        self._loaded_count = end
        self._is_loading = False
        
        logger.info(f"Loaded {self._loaded_count}/{len(self._all_file_data)} files")
        self._update_stats()
    
    def _on_scroll(self, value):
        """滚动事件 - 不再需要懒加载"""
        pass
    
    def _create_file_item_lazy(self, file_path: Path, metadata):
        """创建文件项（懒加载版，添加到对应文件夹）"""
        # 不再显示文件，只显示文件夹
        return
        
        # 找到父文件夹节点
        # parent_path = file_path.parent
        # parent_path_str = str(parent_path)
        # parent_item = self._folder_items.get(parent_path_str)
        # 
        # if not parent_item:
        #     # 如果找不到父文件夹，记录警告并跳过
        #     logger.warning(f"Parent folder not found for {file_path.name}, parent: {parent_path_str}")
        #     return
        # 
        # # 创建文件项
        # self._create_file_item(parent_item, file_path)
    
    def _update_stats(self):
        """更新统计信息"""
        total = len(self._all_file_data) if self._all_file_data else len(self._audio_files)
        loaded = self._loaded_count if self._lazy_load_enabled else total
        
        if self._lazy_load_enabled and loaded < total:
            self.stats_label.setText(f"已加载 {loaded}/{total} 个音效")
        else:
            self.stats_label.setText(f"共 {total} 个音效")
    
    # ==================== 标签批量更新相关方法 ====================
    
    def _on_tags_batch_updated(self, batch_updates: list):
        """
        批量更新文件标签显示，并同步到音效列表的「标签」列。
        
        参数：
            batch_updates: [{'file_path': str, 'tags': list}, ...]
        """
        import os
        for update in batch_updates:
            file_path = update['file_path']
            tags = update['tags']
            
            # 路径匹配容错：使用 normpath 规范化后匹配
            norm_path = os.path.normpath(file_path) if file_path else ""
            meta_key = None
            
            # 尝试多种路径格式查找 metadata
            for candidate in [file_path, norm_path, str(Path(file_path)), Path(file_path).as_posix()]:
                if candidate and candidate in self._file_metadata:
                    meta_key = candidate
                    break
            
            # 1. 更新元数据（_file_metadata 与 _all_file_data 中为同一引用，音效列表依赖 get_file_info_by_index）
            if meta_key and meta_key in self._file_metadata:
                metadata = self._file_metadata[meta_key]
                if hasattr(metadata, 'tags'):
                    metadata.tags = tags
                logger.debug(f"Updated tags for {Path(file_path).name}: {tags}")
            else:
                # _file_metadata 中没找到：更新 _file_info_cache 确保下次从数据库读取时能显示
                # 同时清除可能存在的旧缓存，确保下次调用 get_file_info_by_index 会重新从 DB 读取
                for cache_key in [file_path, norm_path, str(Path(file_path))]:
                    if cache_key in self._file_info_cache:
                        self._file_info_cache[cache_key]["tags"] = tags
                        logger.debug(f"Updated cache tags for {Path(file_path).name}: {tags}")
                        break
                else:
                    # 缓存中也没有，预填充一个条目以便下次读取
                    self._file_info_cache[norm_path] = {"tags": tags, "file_path": file_path}
            
            # 2. 若该文件已在树中创建，同步更新树节点 tooltip（树节点 key 可能与 meta 一致）
            if file_path in self._file_items:
                item = self._file_items[file_path]
                tags_text = ", ".join(tags) if tags else "无标签"
                current_tooltip = item.toolTip(0) or file_path
                new_tooltip = f"{current_tooltip}\n标签: {tags_text}"
                item.setToolTip(0, new_tooltip)
        
        logger.info(f"Batch updated {len(batch_updates)} files' tags")
        # 3. 节流刷新音效列表：每约 3 批刷新一次，避免 6k+ 条时每 500 条就全量重绘导致卡顿
        count = getattr(self, "_tagging_batch_count", 0) + 1
        setattr(self, "_tagging_batch_count", count)
        if count % 3 == 0 or count == 1:
            self._refresh_audio_files_panel_after_tags_update()

    def _refresh_audio_files_panel_after_tags_update(self):
        """打标批量更新后强制刷新音效列表，使标签列显示最新结果。"""
        if not self._selected_folders:
            return
        # 清除上次显示 key，使 _update_audio_files_panel_display 会再次 emit，面板会重绘
        setattr(self, "_last_folder_display_key", None)
        self._update_audio_files_panel_display()
