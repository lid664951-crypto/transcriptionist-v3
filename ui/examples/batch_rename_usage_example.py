"""
批量重命名对话框使用示例

展示如何正确调用批量重命名对话框，并在完成后刷新UI
"""

from typing import List
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from transcriptionist_v3.ui.dialogs import show_batch_rename_dialog
from transcriptionist_v3.application.naming_manager import RenameResult
from transcriptionist_v3.infrastructure.database.connection import session_scope
from transcriptionist_v3.infrastructure.database.models import AudioFile


def reload_audio_files_from_database() -> List[dict]:
    """
    从数据库重新加载所有音频文件数据
    
    Returns:
        List[dict]: 音频文件数据列表
    """
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
            })
        
        return files_data


def on_batch_rename_complete(result: RenameResult, audio_list_view, library_view=None):
    """
    批量重命名完成后的回调函数
    
    Args:
        result: 重命名结果
        audio_list_view: 音频列表视图组件
        library_view: 库视图组件（可选）
    """
    if result.success > 0:
        # 从数据库重新加载数据
        updated_files = reload_audio_files_from_database()
        
        # 刷新音频列表视图
        audio_list_view.reload_items(updated_files)
        
        # 如果有库视图，也刷新它
        if library_view:
            library_view.set_files(updated_files)
        
        print(f"✓ UI已刷新，显示 {len(updated_files)} 个文件")


# 示例1：在库页面中调用批量重命名
def example_call_from_library_page(parent_window, selected_files, audio_list_view, library_view):
    """
    从库页面调用批量重命名的示例
    
    Args:
        parent_window: 父窗口
        selected_files: 选中的文件路径列表
        audio_list_view: 音频列表视图
        library_view: 库视图
    """
    # 创建回调函数（使用lambda捕获视图引用）
    def on_complete(result: RenameResult):
        on_batch_rename_complete(result, audio_list_view, library_view)
    
    # 显示批量重命名对话框
    show_batch_rename_dialog(
        parent=parent_window,
        files=selected_files,
        on_complete=on_complete
    )


# 示例2：在AI翻译完成后调用批量重命名
def example_call_after_ai_translation(parent_window, translated_files, audio_list_view):
    """
    AI翻译完成后调用批量重命名的示例
    
    Args:
        parent_window: 父窗口
        translated_files: 翻译后的文件路径列表
        audio_list_view: 音频列表视图
    """
    def on_complete(result: RenameResult):
        on_batch_rename_complete(result, audio_list_view)
    
    show_batch_rename_dialog(
        parent=parent_window,
        files=translated_files,
        on_complete=on_complete
    )


# 示例3：简单的刷新回调（最小实现）
def example_minimal_callback(parent_window, files, audio_list_view):
    """
    最小实现的示例
    """
    show_batch_rename_dialog(
        parent=parent_window,
        files=files,
        on_complete=lambda result: audio_list_view.reload_items(
            reload_audio_files_from_database()
        ) if result.success > 0 else None
    )


"""
使用说明：

1. 在任何需要调用批量重命名的地方，使用以下模式：

   def on_rename_complete(result):
       if result.success > 0:
           # 从数据库重新加载
           updated_data = reload_audio_files_from_database()
           # 刷新UI
           self.audio_list_view.reload_items(updated_data)
   
   show_batch_rename_dialog(
       parent=self,
       files=selected_file_paths,
       on_complete=on_rename_complete
   )

2. 关键点：
   - 必须传入 on_complete 回调
   - 回调中必须从数据库重新加载数据
   - 使用 reload_items() 或 set_items() 刷新UI

3. 这样可以确保：
   - 文件重命名后，数据库路径已更新
   - UI显示的是数据库中的最新路径
   - 播放器能正确加载文件
"""
