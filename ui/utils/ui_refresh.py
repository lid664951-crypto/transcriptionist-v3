"""
UI刷新工具函数

提供统一的UI刷新接口，用于批量操作后更新界面
"""

import logging
from typing import List, Dict, Any, Optional, Callable

from transcriptionist_v3.infrastructure.database.connection import session_scope
from transcriptionist_v3.infrastructure.database.models import AudioFile

logger = logging.getLogger(__name__)


def reload_audio_files_from_database() -> List[Dict[str, Any]]:
    """
    从数据库重新加载所有音频文件数据
    
    Returns:
        List[Dict[str, Any]]: 音频文件数据列表，格式化为UI可用的字典
    """
    try:
        with session_scope() as session:
            audio_files = session.query(AudioFile).all()
            
            # 转换为字典格式（适配UI）
            files_data = []
            for af in audio_files:
                files_data.append({
                    'id': af.id,
                    'file_path': af.file_path,
                    'filename': af.filename,
                    'original_filename': af.original_filename,
                    'duration': af.duration,
                    'sample_rate': af.sample_rate,
                    'bit_depth': af.bit_depth,
                    'channels': af.channels,
                    'format': af.format,
                    'file_size': af.file_size,
                    'description': af.description,
                    'created_at': af.created_at,
                    'modified_at': af.modified_at,
                })
            
            logger.info(f"从数据库加载了 {len(files_data)} 个音频文件")
            return files_data
            
    except Exception as e:
        logger.error(f"从数据库加载音频文件失败: {e}")
        return []


def reload_specific_files(file_ids: List[int]) -> List[Dict[str, Any]]:
    """
    从数据库重新加载指定的音频文件
    
    Args:
        file_ids: 文件ID列表
        
    Returns:
        List[Dict[str, Any]]: 音频文件数据列表
    """
    try:
        with session_scope() as session:
            audio_files = session.query(AudioFile).filter(
                AudioFile.id.in_(file_ids)
            ).all()
            
            files_data = []
            for af in audio_files:
                files_data.append({
                    'id': af.id,
                    'file_path': af.file_path,
                    'filename': af.filename,
                    'original_filename': af.original_filename,
                    'duration': af.duration,
                    'sample_rate': af.sample_rate,
                    'bit_depth': af.bit_depth,
                    'channels': af.channels,
                    'format': af.format,
                    'file_size': af.file_size,
                    'description': af.description,
                })
            
            return files_data
            
    except Exception as e:
        logger.error(f"从数据库加载指定文件失败: {e}")
        return []


def create_refresh_callback(
    audio_list_view,
    library_view: Optional[Any] = None,
    on_success: Optional[Callable] = None
) -> Callable:
    """
    创建一个标准的刷新回调函数
    
    Args:
        audio_list_view: 音频列表视图组件
        library_view: 库视图组件（可选）
        on_success: 成功后的额外回调（可选）
        
    Returns:
        Callable: 可用于批量操作的回调函数
    """
    def callback(result):
        """批量操作完成后的回调"""
        # 检查是否有成功的操作
        success_count = getattr(result, 'success', 0)
        
        if success_count > 0:
            logger.info(f"批量操作成功 {success_count} 个文件，开始刷新UI")
            
            # 从数据库重新加载数据
            updated_files = reload_audio_files_from_database()
            
            # 刷新音频列表视图
            if hasattr(audio_list_view, 'reload_items'):
                audio_list_view.reload_items(updated_files)
            elif hasattr(audio_list_view, 'set_items'):
                audio_list_view.set_items(updated_files)
            
            # 刷新库视图
            if library_view and hasattr(library_view, 'set_files'):
                library_view.set_files(updated_files)
            
            logger.info(f"UI刷新完成，显示 {len(updated_files)} 个文件")
            
            # 调用额外的成功回调
            if on_success:
                on_success(result, updated_files)
        else:
            logger.info("批量操作没有成功的项目，跳过UI刷新")
    
    return callback


# 便捷函数：直接刷新UI
def refresh_ui_after_batch_operation(audio_list_view, library_view: Optional[Any] = None):
    """
    批量操作后直接刷新UI（不需要回调）
    
    Args:
        audio_list_view: 音频列表视图
        library_view: 库视图（可选）
    """
    updated_files = reload_audio_files_from_database()
    
    if hasattr(audio_list_view, 'reload_items'):
        audio_list_view.reload_items(updated_files)
    elif hasattr(audio_list_view, 'set_items'):
        audio_list_view.set_items(updated_files)
    
    if library_view and hasattr(library_view, 'set_files'):
        library_view.set_files(updated_files)
    
    logger.info(f"UI刷新完成，显示 {len(updated_files)} 个文件")
