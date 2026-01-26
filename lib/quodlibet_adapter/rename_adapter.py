"""
Quod Libet Rename Adapter

适配 Quod Libet 的重命名功能到 Transcriptionist v3。
复用 Quod Libet 20多年积累的成熟代码。

Based on Quod Libet - https://github.com/quodlibet/quodlibet
Copyright (C) 2004-2025 Quod Libet contributors
Copyright (C) 2024-2026 音译家开发者 (modifications and adaptations)

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""

from __future__ import annotations

import os
import re
import unicodedata
import logging
from pathlib import Path
from typing import Optional, List, Callable, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ============================================================
# 从 Quod Libet util/path.py 移植的路径处理函数
# ============================================================

def strip_win32_incompat(string: str, bad: str = r'\:*?;"<>|') -> str:
    """
    移除 Windows 不兼容的字符
    
    从 Quod Libet 移植，经过20多年的实战验证。
    """
    if os.name == "nt":
        bad += "/"
    
    if not string:
        return string
    
    new = "".join((s in bad and "_") or s for s in string)
    parts = new.split(os.sep)
    
    def fix_end(s: str) -> str:
        """修复结尾的点和空格（Windows不允许）"""
        return re.sub(r"[\. ]$", "_", s)
    
    return os.sep.join(fix_end(p) for p in parts)


def strip_win32_incompat_from_path(string: str) -> str:
    """
    从路径中移除 Windows 不兼容字符，保留路径分隔符和驱动器部分
    """
    drive, tail = os.path.splitdrive(string)
    tail = os.sep.join(strip_win32_incompat(s) for s in tail.split(os.sep))
    return drive + tail


def limit_path(path: str, max_length: int = 255, ellipsis: bool = True) -> str:
    """
    限制路径中每个部分的长度
    
    Args:
        path: 文件路径
        max_length: 每个部分的最大长度
        ellipsis: 是否添加省略号
    """
    main, ext = os.path.splitext(path)
    parts = main.split(os.sep)
    
    for i, p in enumerate(parts):
        limit = max_length
        if i == len(parts) - 1:
            limit -= len(ext)
        
        if len(p) > limit:
            if ellipsis:
                p = p[:limit - 2] + ".."
            else:
                p = p[:limit]
        parts[i] = p
    
    return os.sep.join(parts) + ext


# ============================================================
# 从 Quod Libet qltk/renamefiles.py 移植的过滤器
# ============================================================

@dataclass
class FilterResult:
    """过滤器结果"""
    original: str
    filtered: str
    filter_name: str


class RenameFilter:
    """重命名过滤器基类"""
    
    name: str = "Base Filter"
    description: str = ""
    order: float = 1.0
    
    def filter(self, original: str, filename: str) -> str:
        """
        过滤文件名
        
        Args:
            original: 原始文件名
            filename: 当前文件名（可能已被其他过滤器处理）
            
        Returns:
            过滤后的文件名
        """
        raise NotImplementedError
    
    def filter_list(
        self,
        originals: List[str],
        filenames: List[str],
    ) -> List[str]:
        """批量过滤"""
        return [self.filter(o, f) for o, f in zip(originals, filenames)]


class SpacesToUnderscores(RenameFilter):
    """将空格替换为下划线"""
    
    name = "空格转下划线"
    description = "将文件名中的空格替换为下划线"
    order = 1.0
    
    def filter(self, original: str, filename: str) -> str:
        return filename.replace(" ", "_")


class ReplaceColons(RenameFilter):
    """将冒号分隔替换为连字符"""
    
    name = "冒号转连字符"
    description = '例如: "iv: allegro.flac" → "iv - allegro.flac"'
    order = 1.05
    
    def filter(self, original: str, filename: str) -> str:
        regx = re.compile(r"\s*[:;]\s+\b")
        return regx.sub(" - ", filename)


class StripWindowsIncompat(RenameFilter):
    """移除 Windows 不兼容字符"""
    
    name = "移除Windows不兼容字符"
    description = "移除 Windows 文件系统不支持的字符"
    order = 1.1
    
    def filter(self, original: str, filename: str) -> str:
        return strip_win32_incompat_from_path(filename)


class StripDiacriticals(RenameFilter):
    """移除变音符号"""
    
    name = "移除变音符号"
    description = "移除字符上的变音符号（如 é → e）"
    order = 1.2
    
    def filter(self, original: str, filename: str) -> str:
        return "".join(
            filter(
                lambda s: not unicodedata.combining(s),
                unicodedata.normalize("NFKD", filename),
            )
        )


class StripNonASCII(RenameFilter):
    """移除非 ASCII 字符"""
    
    name = "移除非ASCII字符"
    description = "将非 ASCII 字符替换为下划线"
    order = 1.3
    
    def filter(self, original: str, filename: str) -> str:
        return "".join((s <= "~" and s) or "_" for s in filename)


class Lowercase(RenameFilter):
    """转换为小写"""
    
    name = "转为小写"
    description = "将文件名转换为全小写"
    order = 1.4
    
    def filter(self, original: str, filename: str) -> str:
        return filename.lower()


class Uppercase(RenameFilter):
    """转换为大写"""
    
    name = "转为大写"
    description = "将文件名转换为全大写"
    order = 1.5
    
    def filter(self, original: str, filename: str) -> str:
        return filename.upper()


class TitleCase(RenameFilter):
    """转换为标题格式"""
    
    name = "标题格式"
    description = "将每个单词首字母大写"
    order = 1.6
    
    def filter(self, original: str, filename: str) -> str:
        return filename.title()


class RemoveMultipleSpaces(RenameFilter):
    """移除多余空格"""
    
    name = "移除多余空格"
    description = "将多个连续空格替换为单个空格"
    order = 1.7
    
    def filter(self, original: str, filename: str) -> str:
        return re.sub(r"\s+", " ", filename).strip()


class RemoveParentheses(RenameFilter):
    """移除括号内容"""
    
    name = "移除括号内容"
    description = "移除圆括号及其内容"
    order = 1.8
    
    def filter(self, original: str, filename: str) -> str:
        return re.sub(r"\s*\([^)]*\)", "", filename).strip()


class RemoveBrackets(RenameFilter):
    """移除方括号内容"""
    
    name = "移除方括号内容"
    description = "移除方括号及其内容"
    order = 1.9
    
    def filter(self, original: str, filename: str) -> str:
        return re.sub(r"\s*\[[^\]]*\]", "", filename).strip()


# 所有可用的过滤器
AVAILABLE_FILTERS: List[type] = [
    SpacesToUnderscores,
    ReplaceColons,
    StripWindowsIncompat,
    StripDiacriticals,
    StripNonASCII,
    Lowercase,
    Uppercase,
    TitleCase,
    RemoveMultipleSpaces,
    RemoveParentheses,
    RemoveBrackets,
]


class FilterChain:
    """
    过滤器链
    
    按顺序应用多个过滤器。
    """
    
    def __init__(self):
        self._filters: List[RenameFilter] = []
    
    def add_filter(self, filter_instance: RenameFilter) -> None:
        """添加过滤器"""
        self._filters.append(filter_instance)
        self._filters.sort(key=lambda f: f.order)
    
    def remove_filter(self, filter_type: type) -> None:
        """移除过滤器"""
        self._filters = [f for f in self._filters if not isinstance(f, filter_type)]
    
    def clear(self) -> None:
        """清空过滤器"""
        self._filters.clear()
    
    def apply(self, original: str, filename: str) -> Tuple[str, List[FilterResult]]:
        """
        应用所有过滤器
        
        Returns:
            (最终文件名, 过滤结果列表)
        """
        results = []
        current = filename
        
        for f in self._filters:
            filtered = f.filter(original, current)
            if filtered != current:
                results.append(FilterResult(
                    original=current,
                    filtered=filtered,
                    filter_name=f.name,
                ))
            current = filtered
        
        return current, results
    
    def apply_list(
        self,
        originals: List[str],
        filenames: List[str],
    ) -> List[str]:
        """批量应用过滤器"""
        return [self.apply(o, f)[0] for o, f in zip(originals, filenames)]
    
    @property
    def filters(self) -> List[RenameFilter]:
        """获取当前过滤器列表"""
        return self._filters.copy()


# ============================================================
# 便捷函数
# ============================================================

def create_default_filter_chain() -> FilterChain:
    """创建默认过滤器链（适用于音效文件）"""
    chain = FilterChain()
    chain.add_filter(RemoveMultipleSpaces())
    chain.add_filter(StripWindowsIncompat())
    return chain


def create_strict_filter_chain() -> FilterChain:
    """创建严格过滤器链（最大兼容性）"""
    chain = FilterChain()
    chain.add_filter(SpacesToUnderscores())
    chain.add_filter(StripWindowsIncompat())
    chain.add_filter(StripDiacriticals())
    chain.add_filter(Lowercase())
    return chain


def sanitize_filename(filename: str, strict: bool = False) -> str:
    """
    清理文件名
    
    Args:
        filename: 原始文件名
        strict: 是否使用严格模式
        
    Returns:
        清理后的文件名
    """
    if strict:
        chain = create_strict_filter_chain()
    else:
        chain = create_default_filter_chain()
    
    result, _ = chain.apply(filename, filename)
    return result
