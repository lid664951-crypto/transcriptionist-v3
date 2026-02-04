"""
Renaming Service

Handles renaming of audio files with metadata preservation.
Specifically, it writes the 'ORIGINAL_FILENAME' tag before renaming.
"""

import os
import shutil
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from transcriptionist_v3.infrastructure.database.connection import session_scope
from transcriptionist_v3.infrastructure.database.models import AudioFile

logger = logging.getLogger(__name__)

class RenamingService:
    @staticmethod
    def rename_sync(file_path: str, new_name: str) -> Tuple[bool, str, str]:
        """Synchronous version of RenameWithMetadata."""
        path = Path(file_path)
        if not path.exists():
            return False, "文件不存在", file_path

        # 额外检查目标目录写入权限，尽早给出友好提示（尤其是只读盘/受保护目录）
        try:
            parent_dir = path.parent
            # os.access 在 Windows 上不是绝对可靠，但可以过滤掉明显的只读情况
            if not os.access(parent_dir, os.W_OK):
                msg = f"目标文件夹没有写入权限：{parent_dir}"
                logger.warning(f"Rename aborted due to write permission: {file_path} -> {new_name} ({msg})")
                return False, msg, file_path
        except Exception as e:
            # 权限检测失败不阻断流程，后续 rename 仍会有更明确的异常
            logger.debug(f"Failed to pre-check write permission for {path}: {e}")

        # 1. Write Metadata (Sync)
        try:
            RenamingService._write_original_filename_sync(path, path.name)
        except PermissionError as e:
            # 权限错误 - 返回友好提示
            logger.warning(f"Failed to write metadata for {path.name}: {e}")
            return False, str(e), file_path
        except Exception as e:
            # 其他错误 - 记录但继续重命名
            logger.warning(f"Failed to write metadata for {path.name}: {e}")

        # 2. Rename & DB Update
        try:
            new_path_obj = path.parent / new_name
            if new_path_obj.exists() and new_path_obj != path:
                stem = new_path_obj.stem
                suffix = new_path_obj.suffix
                counter = 1
                while new_path_obj.exists():
                    new_path_obj = path.parent / f"{stem}_{counter}{suffix}"
                    counter += 1
            
            path.rename(new_path_obj)
            new_path_str = str(new_path_obj)
            
            try:
                RenamingService._update_database(str(path), new_path_str, new_path_obj.name)
            except Exception as e:
                logger.error(f"DB update failed: {e}")
                
            return True, "成功", new_path_str
        except Exception as e:
            return False, f"重命名失败: {e}", file_path

    @staticmethod
    async def RenameWithMetadata(file_path: str, new_name: str) -> Tuple[bool, str, str]:
        return RenamingService.rename_sync(file_path, new_name)

    @staticmethod
    def _write_original_filename_sync(path: Path, original_name: str):
        """Synchronous implementation of metadata writing."""
        try:
            import mutagen
            from mutagen.id3 import ID3, TXXX
            from mutagen.flac import FLAC
            from mutagen.oggvorbis import OggVorbis
            from mutagen.mp4 import MP4
            from mutagen.wave import WAVE
            
            ext = path.suffix.lower()
            f = mutagen.File(str(path))
            
            if f is None: return

            if isinstance(f, (FLAC, OggVorbis)):
                f["ORIGINAL_FILENAME"] = original_name
                f.save()
            elif ext in ['.mp3', '.wav']:
                if f.tags is None:
                    try:
                        f.add_tags()
                    except Exception as e:
                        # 标签结构初始化失败，后续写入会被跳过
                        logger.warning(f"Failed to add tags for {path.name}: {e}")
                if ext == '.wav' and not isinstance(f.tags, ID3):
                   try:
                       f = WAVE(str(path))
                       if f.tags is None:
                           f.add_tags()
                   except Exception as e:
                       logger.warning(f"Failed to convert WAV tags for {path.name}: {e}")
                if isinstance(f.tags, ID3):
                    f.tags.add(TXXX(encoding=3, desc='ORIGINAL_FILENAME', text=[original_name]))
                    f.save()
            elif isinstance(f, MP4):
                f["----:com.apple.iTunes:ORIGINAL_FILENAME"] = original_name.encode('utf-8')
                f.save()
        except ImportError:
            logger.error("Mutagen not installed")
        except PermissionError as e:
            # 权限错误 - 提供详细信息并抛出给上层处理
            logger.error(f"Permission denied when writing metadata to {path.name}: {e}")
            raise PermissionError(
                f"无法写入文件标签信息。可能原因：\n"
                f"• 文件是只读的\n"
                f"• 文件在受保护的目录\n"
                f"• 文件正在被其他程序使用\n"
                f"文件：{path.name}"
            )
        except Exception as e:
            raise e

    @staticmethod
    async def _write_original_filename(path: Path, original_name: str):
        """Async wrapper."""
        await asyncio.to_thread(RenamingService._write_original_filename_sync, path, original_name)

    @staticmethod
    def _update_database(old_path: str, new_path: str, new_filename: str):
        """Update file path in database."""
        with session_scope() as session:
            # Query by old path
            # Note: We need to handle potential path format differences (slash vs backslash)
            db_file = session.query(AudioFile).filter(AudioFile.file_path == old_path).first()
            if db_file:
                db_file.file_path = new_path
                db_file.filename = new_filename
                db_file.modified_at = datetime.now()
