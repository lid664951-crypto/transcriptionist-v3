"""
Library Service - 音效库服务

整合数据库、扫描器、元数据提取器和文件监视器的统一服务层。
提供文件持久化、搜索、监视等功能。
"""

import logging
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Callable, Tuple
from datetime import datetime

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 支持的音频格式
SUPPORTED_FORMATS = {".wav", ".flac", ".mp3", ".ogg", ".aiff", ".aif", ".m4a", ".mp4"}


class LibraryService:
    """
    音效库服务
    
    功能：
    - 文件扫描和元数据提取
    - 数据库持久化
    - 文件监视（自动更新）
    - 高级搜索
    """
    
    _instance: Optional['LibraryService'] = None
    
    def __init__(self):
        self._db_manager = None
        self._file_watcher = None
        self._watcher_started = False
        
        # 回调
        self._on_file_added: Optional[Callable[[str, dict], None]] = None
        self._on_file_removed: Optional[Callable[[str], None]] = None
        self._on_file_modified: Optional[Callable[[str, dict], None]] = None
    
    @classmethod
    def instance(cls) -> 'LibraryService':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _get_db_manager(self):
        """延迟获取数据库管理器"""
        if self._db_manager is None:
            try:
                from ...infrastructure.database.connection import get_db_manager
                self._db_manager = get_db_manager()
            except Exception as e:
                logger.error(f"Failed to get database manager: {e}")
        return self._db_manager
    
    def _get_session(self) -> Optional[Session]:
        """获取数据库会话"""
        db = self._get_db_manager()
        if db:
            return db.get_session()
        return None
    
    # ═══════════════════════════════════════════════════════════
    # 文件扫描和持久化
    # ═══════════════════════════════════════════════════════════
    
    def scan_folder(
        self,
        folder_path: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Tuple[Path, dict]]:
        """
        扫描文件夹并提取元数据
        
        Args:
            folder_path: 文件夹路径
            progress_callback: 进度回调 (scanned, total, current_file)
            
        Returns:
            List of (file_path, metadata) tuples
        """
        import os
        from .metadata_extractor import MetadataExtractor
        
        folder = Path(folder_path)
        extractor = MetadataExtractor()
        
        # 收集所有音频文件
        audio_files = []
        for root, dirs, files in os.walk(folder):
            for filename in files:
                file_path = Path(root) / filename
                if file_path.suffix.lower() in SUPPORTED_FORMATS:
                    audio_files.append(file_path)
        
        total = len(audio_files)
        results = []
        
        # 提取元数据
        for i, file_path in enumerate(audio_files):
            if progress_callback:
                progress_callback(i + 1, total, str(file_path))
            
            try:
                metadata = extractor.extract(file_path)
                results.append((file_path, metadata))
            except Exception as e:
                logger.warning(f"Failed to extract metadata from {file_path}: {e}")
                results.append((file_path, None))
        
        return results
    
    def save_to_database(
        self,
        files: List[Tuple[Path, dict]],
        library_path: str
    ) -> int:
        """
        将扫描结果保存到数据库
        
        Args:
            files: (file_path, metadata) 列表
            library_path: 库路径
            
        Returns:
            保存的文件数量
        """
        session = self._get_session()
        if not session:
            logger.warning("Database not available, files will not be persisted")
            return 0
        
        try:
            from ...infrastructure.database.models import AudioFile, LibraryPath
            
            # 确保库路径存在
            lib_path = session.query(LibraryPath).filter_by(path=library_path).first()
            if not lib_path:
                lib_path = LibraryPath(
                    path=library_path,
                    enabled=True,
                    recursive=True,
                    last_scan_at=datetime.utcnow()
                )
                session.add(lib_path)
            else:
                lib_path.last_scan_at = datetime.utcnow()
            
            saved_count = 0
            
            for file_path, metadata in files:
                file_path_str = str(file_path)
                
                # 检查文件是否已存在
                existing = session.query(AudioFile).filter_by(file_path=file_path_str).first()
                
                if existing:
                    # 更新现有记录
                    self._update_audio_file(existing, file_path, metadata)
                else:
                    # 创建新记录
                    audio_file = self._create_audio_file(file_path, metadata)
         