"""
资源路径管理工具

提供统一的资源文件路径获取方法，支持开发环境和打包后环境。

使用方法:
    from ui.utils.resources import get_resource_path
    
    icon_path = get_resource_path("resources/icons/app_icon.png")
    qss_path = get_resource_path("resources/styles/workstation_dark.qss")
"""

import sys
from pathlib import Path
from typing import Union


def get_resource_path(relative_path: Union[str, Path]) -> Path:
    """
    获取资源文件的绝对路径
    
    自动处理开发环境和打包后环境的路径差异：
    - 开发环境: 使用源代码目录
    - 打包后: 使用 PyInstaller 的临时解压目录 (_MEIPASS)
    
    Args:
        relative_path: 相对于 ui 目录的路径
                      例如: "resources/icons/app_icon.png"
                           "resources/styles/workstation_dark.qss"
    
    Returns:
        Path: 资源文件的绝对路径
    
    Examples:
        >>> icon_path = get_resource_path("resources/icons/app_icon.png")
        >>> # 开发环境: C:/项目/ui/resources/icons/app_icon.png
        >>> # 打包后: C:/Temp/_MEI123/ui/resources/icons/app_icon.png
    """
    if isinstance(relative_path, str):
        relative_path = Path(relative_path)
    
    if getattr(sys, 'frozen', False):
        # 打包后：兼容 PyInstaller 与 Nuitka
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller onefile/onedir
            base_path = Path(sys._MEIPASS) / "ui"
        else:
            # Nuitka standalone：资源通常位于可执行文件同级目录
            exe_dir = Path(sys.executable).resolve().parent
            nuitka_ui = exe_dir / "ui"
            base_path = nuitka_ui if nuitka_ui.exists() else exe_dir
    else:
        # 开发环境：使用当前文件的父目录的父目录（ui/utils/ -> ui/）
        base_path = Path(__file__).parent.parent
    
    return base_path / relative_path


def get_icon_path(icon_name: str) -> Path:
    """
    获取图标文件路径的快捷方法
    
    Args:
        icon_name: 图标文件名，例如 "app_icon.png"
    
    Returns:
        Path: 图标文件的绝对路径
    """
    return get_resource_path(f"resources/icons/{icon_name}")


def get_app_icon_path() -> Path:
    """
    获取应用主图标路径（用于窗口/任务栏）。
    Windows 上优先返回 .ico（多分辨率，任务栏/Alt+Tab 显示更稳定），否则 .png。
    """
    import sys as _sys
    ico_path = get_resource_path("resources/icons/app_icon.ico")
    png_path = get_resource_path("resources/icons/app_icon.png")
    if _sys.platform == "win32" and ico_path.exists():
        return ico_path
    if png_path.exists():
        return png_path
    return ico_path if ico_path.exists() else png_path


def get_image_path(image_name: str) -> Path:
    """
    获取图片文件路径的快捷方法
    
    Args:
        image_name: 图片文件名，例如 "wechat_qr.png"
    
    Returns:
        Path: 图片文件的绝对路径
    """
    return get_resource_path(f"resources/images/{image_name}")


def get_style_path(style_name: str) -> Path:
    """
    获取样式文件路径的快捷方法
    
    Args:
        style_name: 样式文件名，例如 "workstation_dark.qss"
    
    Returns:
        Path: 样式文件的绝对路径
    """
    return get_resource_path(f"resources/styles/{style_name}")


def resource_exists(relative_path: Union[str, Path]) -> bool:
    """
    检查资源文件是否存在
    
    Args:
        relative_path: 相对于 ui 目录的路径
    
    Returns:
        bool: 文件是否存在
    """
    return get_resource_path(relative_path).exists()


def get_base_path() -> Path:
    """
    获取 UI 模块的基础路径
    
    Returns:
        Path: UI 模块的基础路径
    """
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            return Path(sys._MEIPASS) / "ui"
        exe_dir = Path(sys.executable).resolve().parent
        nuitka_ui = exe_dir / "ui"
        return nuitka_ui if nuitka_ui.exists() else exe_dir
    else:
        return Path(__file__).parent.parent


# 导出常用路径
RESOURCES_DIR = get_resource_path("resources")
ICONS_DIR = get_resource_path("resources/icons")
IMAGES_DIR = get_resource_path("resources/images")
STYLES_DIR = get_resource_path("resources/styles")
