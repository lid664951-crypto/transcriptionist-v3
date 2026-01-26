"""
字体管理模块 - HarmonyOS Sans 字体加载
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# 字体文件路径 - 支持开发环境和打包后环境
def _get_fonts_dir() -> Path:
    """获取字体目录路径，支持 PyInstaller 打包"""
    if getattr(sys, 'frozen', False):
        # 打包后：使用 PyInstaller 的临时目录
        return Path(sys._MEIPASS) / "resources" / "fonts"
    else:
        # 开发环境：使用当前文件的父目录
        return Path(__file__).parent.parent / "resources" / "fonts"

FONTS_DIR = _get_fonts_dir()

# HarmonyOS Sans 字体家族名称
FONT_FAMILY = "HarmonyOS Sans SC"

# 备用字体
FALLBACK_FONTS = ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "sans-serif"]

# 字体文件映射 (支持多种命名格式)
FONT_FILES = {
    "Light": ["HarmonyOS_Sans_SC_Light.ttf", "HarmonyOS_SansSC_Light.ttf", "HarmonyOS_Sans_Light.ttf"],
    "Regular": ["HarmonyOS_Sans_SC_Regular.ttf", "HarmonyOS_SansSC_Regular.ttf"], 
    "Medium": ["HarmonyOS_Sans_SC_Medium.ttf", "HarmonyOS_SansSC_Medium.ttf"],
    "Bold": ["HarmonyOS_Sans_SC_Bold.ttf", "HarmonyOS_SansSC_Bold.ttf"],
}

_fonts_loaded = False
_available_family: Optional[str] = None


def load_fonts() -> bool:
    """
    加载 HarmonyOS Sans 字体
    
    Returns:
        bool: 是否成功加载至少一个字体文件
    """
    global _fonts_loaded, _available_family
    
    if _fonts_loaded:
        return _available_family is not None
    
    _fonts_loaded = True
    loaded_count = 0
    
    if not FONTS_DIR.exists():
        logger.warning(f"Fonts directory not found: {FONTS_DIR}")
        _available_family = _get_fallback_font()
        return False
    
    for weight, filenames in FONT_FILES.items():
        # 支持多个候选文件名
        if isinstance(filenames, str):
            filenames = [filenames]
        
        for filename in filenames:
            font_path = FONTS_DIR / filename
            
            if not font_path.exists():
                continue
            
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            
            if font_id == -1:
                logger.warning(f"Failed to load font: {font_path}")
                continue
            
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                logger.info(f"Loaded font: {filename} -> {families[0]}")
                if _available_family is None:
                    _available_family = families[0]
                loaded_count += 1
                break  # 成功加载一个就跳过其他候选
            else:
                logger.warning(f"No font families found in: {font_path}")
    
    if loaded_count == 0:
        logger.warning("No HarmonyOS Sans fonts loaded, using fallback")
        _available_family = _get_fallback_font()
        return False
    
    logger.info(f"Loaded {loaded_count} HarmonyOS Sans font files")
    return True


def _get_fallback_font() -> str:
    """获取备用字体"""
    for font in FALLBACK_FONTS:
        if QFontDatabase.hasFamily(font):
            logger.info(f"Using fallback font: {font}")
            return font
    return "sans-serif"


def get_font_family() -> str:
    """
    获取可用的字体家族名称
    
    Returns:
        str: 字体家族名称
    """
    global _available_family
    
    if not _fonts_loaded:
        load_fonts()
    
    return _available_family or _get_fallback_font()


def get_font(size: int = 9, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """
    获取配置好的字体对象
    
    Args:
        size: 字体大小 (pt)
        weight: 字体粗细
        
    Returns:
        QFont: 字体对象
    """
    family = get_font_family()
    font = QFont(family, size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def apply_app_font(app: QApplication, size: int = 9) -> None:
    """
    为应用程序设置全局字体
    
    Args:
        app: QApplication 实例
        size: 默认字体大小
    """
    load_fonts()
    font = get_font(size, QFont.Weight.Normal)
    app.setFont(font)
    logger.info(f"App font set to: {font.family()}, {size}pt")


# 便捷函数 - 获取不同字重的字体
def get_light_font(size: int = 9) -> QFont:
    """获取细体字体 (用于注释、次要信息)"""
    return get_font(size, QFont.Weight.Light)


def get_regular_font(size: int = 9) -> QFont:
    """获取常规字体 (用于正文)"""
    return get_font(size, QFont.Weight.Normal)


def get_medium_font(size: int = 9) -> QFont:
    """获取中等字体 (用于小标题)"""
    return get_font(size, QFont.Weight.Medium)


def get_bold_font(size: int = 9) -> QFont:
    """获取粗体字体 (用于标题、强调)"""
    return get_font(size, QFont.Weight.Bold)
