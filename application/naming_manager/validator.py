"""
Naming Validator

验证文件名是否符合UCS规范和文件系统要求。
"""

from __future__ import annotations

import re
import os
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set

from transcriptionist_v3.domain.models import UCSComponents, UCS_CATEGORIES

logger = logging.getLogger(__name__)


class ValidationError(Enum):
    """验证错误类型"""
    
    # UCS格式错误
    MISSING_CATEGORY = "missing_category"
    MISSING_SUBCATEGORY = "missing_subcategory"
    INVALID_CATEGORY = "invalid_category"
    INVALID_FORMAT = "invalid_format"
    
    # 文件系统错误
    ILLEGAL_CHARACTERS = "illegal_characters"
    RESERVED_NAME = "reserved_name"
    NAME_TOO_LONG = "name_too_long"
    PATH_TOO_LONG = "path_too_long"
    EMPTY_NAME = "empty_name"
    
    # 冲突错误
    FILE_EXISTS = "file_exists"
    DUPLICATE_NAME = "duplicate_name"


@dataclass
class ValidationResult:
    """验证结果"""
    
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    def add_error(self, error: ValidationError, message: str = "") -> None:
        """添加错误"""
        self.errors.append(error)
        self.is_valid = False
        if message:
            self.warnings.append(message)
    
    def add_warning(self, message: str) -> None:
        """添加警告"""
        self.warnings.append(message)
    
    def add_suggestion(self, suggestion: str) -> None:
        """添加建议"""
        self.suggestions.append(suggestion)
    
    @property
    def error_messages(self) -> List[str]:
        """获取错误消息列表"""
        messages = {
            ValidationError.MISSING_CATEGORY: "缺少类别",
            ValidationError.MISSING_SUBCATEGORY: "缺少子类别",
            ValidationError.INVALID_CATEGORY: "无效的类别",
            ValidationError.INVALID_FORMAT: "格式不正确",
            ValidationError.ILLEGAL_CHARACTERS: "包含非法字符",
            ValidationError.RESERVED_NAME: "使用了系统保留名称",
            ValidationError.NAME_TOO_LONG: "文件名过长",
            ValidationError.PATH_TOO_LONG: "路径过长",
            ValidationError.EMPTY_NAME: "文件名为空",
            ValidationError.FILE_EXISTS: "文件已存在",
            ValidationError.DUPLICATE_NAME: "重复的文件名",
        }
        return [messages.get(e, str(e)) for e in self.errors]


class NamingValidator:
    """
    命名验证器
    
    验证文件名是否符合：
    1. UCS命名规范
    2. 文件系统限制
    3. 自定义规则
    """
    
    # Windows保留名称
    WINDOWS_RESERVED = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    
    # 非法字符（Windows）
    ILLEGAL_CHARS_WINDOWS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    
    # 非法字符（通用）
    ILLEGAL_CHARS_UNIX = re.compile(r'[/\x00]')
    
    # 最大文件名长度
    MAX_FILENAME_LENGTH = 255
    
    # 最大路径长度（Windows）
    MAX_PATH_LENGTH_WINDOWS = 260
    
    def __init__(self):
        self._known_categories: Set[str] = set(c.upper() for c in UCS_CATEGORIES)
        self._strict_mode: bool = False
        self._check_exists: bool = True
    
    def set_strict_mode(self, enabled: bool) -> None:
        """设置严格模式（严格检查UCS规范）"""
        self._strict_mode = enabled
    
    def set_check_exists(self, enabled: bool) -> None:
        """设置是否检查文件是否存在"""
        self._check_exists = enabled
    
    def add_category(self, category: str) -> None:
        """添加自定义类别"""
        self._known_categories.add(category.upper())
    
    def validate(
        self,
        filename: str,
        target_dir: Optional[str] = None,
        existing_names: Optional[Set[str]] = None,
    ) -> ValidationResult:
        """
        验证文件名
        
        Args:
            filename: 要验证的文件名
            target_dir: 目标目录（用于检查文件是否存在）
            existing_names: 已存在的文件名集合（用于检查重复）
            
        Returns:
            ValidationResult: 验证结果
        """
        result = ValidationResult(is_valid=True)
        
        # 基本检查
        if not filename or not filename.strip():
            result.add_error(ValidationError.EMPTY_NAME)
            return result
        
        # 提取文件名（不含路径）
        name = Path(filename).name
        stem = Path(filename).stem
        
        # 检查非法字符
        self._check_illegal_chars(name, result)
        
        # 检查保留名称
        self._check_reserved_names(stem, result)
        
        # 检查长度
        self._check_length(name, target_dir, result)
        
        # 检查UCS格式
        self._check_ucs_format(stem, result)
        
        # 检查文件是否存在
        if self._check_exists and target_dir:
            self._check_file_exists(name, target_dir, result)
        
        # 检查重复
        if existing_names:
            self._check_duplicate(name, existing_names, result)
        
        return result
    
    def validate_components(self, components: UCSComponents) -> ValidationResult:
        """验证UCS组件"""
        result = ValidationResult(is_valid=True)
        
        # 检查必需字段
        if not components.category:
            result.add_error(ValidationError.MISSING_CATEGORY)
        
        if not components.subcategory:
            result.add_error(ValidationError.MISSING_SUBCATEGORY)
        
        # 严格模式下检查类别是否已知
        if self._strict_mode and components.category:
            if components.category.upper() not in self._known_categories:
                result.add_error(
                    ValidationError.INVALID_CATEGORY,
                    f"未知的类别: {components.category}",
                )
                result.add_suggestion(f"建议使用标准UCS类别，如: {', '.join(list(self._known_categories)[:5])}...")
        
        # 验证构建的文件名
        if result.is_valid:
            full_name = components.full_name
            name_result = self.validate(full_name)
            
            # 合并结果
            result.errors.extend(name_result.errors)
            result.warnings.extend(name_result.warnings)
            result.suggestions.extend(name_result.suggestions)
            result.is_valid = result.is_valid and name_result.is_valid
        
        return result
    
    def _check_illegal_chars(self, name: str, result: ValidationResult) -> None:
        """检查非法字符"""
        # 根据操作系统选择检查模式
        if os.name == "nt":
            pattern = self.ILLEGAL_CHARS_WINDOWS
        else:
            pattern = self.ILLEGAL_CHARS_UNIX
        
        match = pattern.search(name)
        if match:
            result.add_error(
                ValidationError.ILLEGAL_CHARACTERS,
                f"包含非法字符: '{match.group()}'",
            )
            # 提供修复建议
            fixed = pattern.sub("_", name)
            result.add_suggestion(f"建议替换为: {fixed}")
    
    def _check_reserved_names(self, stem: str, result: ValidationResult) -> None:
        """检查保留名称"""
        if os.name == "nt":
            # Windows保留名称检查
            upper_stem = stem.upper()
            if upper_stem in self.WINDOWS_RESERVED:
                result.add_error(
                    ValidationError.RESERVED_NAME,
                    f"'{stem}' 是Windows保留名称",
                )
                result.add_suggestion(f"建议添加前缀或后缀，如: {stem}_file")
    
    def _check_length(
        self,
        name: str,
        target_dir: Optional[str],
        result: ValidationResult,
    ) -> None:
        """检查长度限制"""
        # 文件名长度
        if len(name) > self.MAX_FILENAME_LENGTH:
            result.add_error(
                ValidationError.NAME_TOO_LONG,
                f"文件名长度 {len(name)} 超过限制 {self.MAX_FILENAME_LENGTH}",
            )
        
        # 完整路径长度（Windows）
        if os.name == "nt" and target_dir:
            full_path = os.path.join(target_dir, name)
            if len(full_path) > self.MAX_PATH_LENGTH_WINDOWS:
                result.add_error(
                    ValidationError.PATH_TOO_LONG,
                    f"路径长度 {len(full_path)} 超过Windows限制 {self.MAX_PATH_LENGTH_WINDOWS}",
                )
    
    def _check_ucs_format(self, stem: str, result: ValidationResult) -> None:
        """检查UCS格式"""
        parts = stem.split("_")
        
        if len(parts) < 2:
            result.add_warning("文件名不符合UCS格式（建议: Category_Subcategory_Descriptor）")
            return
        
        # 检查类别
        category = parts[0].upper()
        if self._strict_mode and category not in self._known_categories:
            result.add_warning(f"未知的UCS类别: {parts[0]}")
    
    def _check_file_exists(
        self,
        name: str,
        target_dir: str,
        result: ValidationResult,
    ) -> None:
        """检查文件是否存在"""
        full_path = os.path.join(target_dir, name)
        if os.path.exists(full_path):
            result.add_error(
                ValidationError.FILE_EXISTS,
                f"文件已存在: {full_path}",
            )
    
    def _check_duplicate(
        self,
        name: str,
        existing_names: Set[str],
        result: ValidationResult,
    ) -> None:
        """检查重复文件名"""
        # 不区分大小写比较（Windows兼容）
        lower_name = name.lower()
        for existing in existing_names:
            if existing.lower() == lower_name:
                result.add_error(
                    ValidationError.DUPLICATE_NAME,
                    f"与现有文件名重复: {existing}",
                )
                break
    
    def suggest_fix(self, filename: str) -> str:
        """
        建议修复后的文件名
        
        Args:
            filename: 原始文件名
            
        Returns:
            修复后的文件名
        """
        name = Path(filename).stem
        ext = Path(filename).suffix
        
        # 移除非法字符
        if os.name == "nt":
            name = self.ILLEGAL_CHARS_WINDOWS.sub("_", name)
        else:
            name = self.ILLEGAL_CHARS_UNIX.sub("_", name)
        
        # 处理保留名称
        if os.name == "nt" and name.upper() in self.WINDOWS_RESERVED:
            name = f"{name}_file"
        
        # 截断过长的文件名
        max_stem_length = self.MAX_FILENAME_LENGTH - len(ext)
        if len(name) > max_stem_length:
            name = name[:max_stem_length]
        
        return f"{name}{ext}"
