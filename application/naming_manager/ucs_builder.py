"""
UCS Builder

构建符合UCS（Universal Category System）规范的文件名。
"""

from __future__ import annotations

import re
import logging
from typing import Optional, List

from transcriptionist_v3.domain.models import UCSComponents

logger = logging.getLogger(__name__)


class UCSBuilder:
    """
    UCS文件名构建器
    
    提供流式API构建UCS规范的文件名。
    """
    
    # 分隔符
    SEPARATOR = "_"
    
    # 非法字符（文件名中不允许的字符）
    ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    
    # 空格替换
    SPACE_REPLACEMENT = "-"
    
    def __init__(self):
        self._category: str = ""
        self._subcategory: str = ""
        self._descriptor: str = ""
        self._variation: str = ""
        self._version: str = ""
        self._extension: str = "wav"
        self._creator_id: str = ""
        
        # 构建选项
        self._normalize_case: bool = True  # 标准化大小写
        self._replace_spaces: bool = True  # 替换空格
        self._strip_illegal: bool = True   # 移除非法字符
    
    def reset(self) -> "UCSBuilder":
        """重置构建器"""
        self._category = ""
        self._subcategory = ""
        self._descriptor = ""
        self._variation = ""
        self._version = ""
        self._extension = "wav"
        self._creator_id = ""
        return self
    
    def category(self, value: str) -> "UCSBuilder":
        """设置类别"""
        self._category = self._normalize(value)
        return self
    
    def subcategory(self, value: str) -> "UCSBuilder":
        """设置子类别"""
        self._subcategory = self._normalize(value)
        return self
    
    def descriptor(self, value: str) -> "UCSBuilder":
        """设置描述符"""
        self._descriptor = self._normalize(value)
        return self
    
    def variation(self, value: str) -> "UCSBuilder":
        """设置变体号"""
        # 变体号通常是数字，保持原样
        self._variation = value.strip()
        return self
    
    def version(self, value: str) -> "UCSBuilder":
        """设置版本号"""
        # 确保版本号格式正确
        value = value.strip()
        if value and not value.lower().startswith("v"):
            value = f"v{value}"
        self._version = value
        return self
    
    def extension(self, value: str) -> "UCSBuilder":
        """设置扩展名"""
        self._extension = value.lstrip(".").lower()
        return self
    
    def creator_id(self, value: str) -> "UCSBuilder":
        """设置创建者ID"""
        self._creator_id = value.upper().strip()
        return self
    
    def from_components(self, components: UCSComponents) -> "UCSBuilder":
        """从UCS组件初始化"""
        self._category = components.category
        self._subcategory = components.subcategory
        self._descriptor = components.descriptor
        self._variation = components.variation
        self._version = components.version
        self._extension = components.extension or "wav"
        self._creator_id = components.creator_id
        return self
    
    def normalize_case(self, enabled: bool) -> "UCSBuilder":
        """设置是否标准化大小写"""
        self._normalize_case = enabled
        return self
    
    def replace_spaces(self, enabled: bool) -> "UCSBuilder":
        """设置是否替换空格"""
        self._replace_spaces = enabled
        return self
    
    def strip_illegal(self, enabled: bool) -> "UCSBuilder":
        """设置是否移除非法字符"""
        self._strip_illegal = enabled
        return self
    
    def _normalize(self, value: str) -> str:
        """标准化字符串"""
        if not value:
            return ""
        
        result = value.strip()
        
        # 替换空格
        if self._replace_spaces:
            result = result.replace(" ", self.SPACE_REPLACEMENT)
        
        # 移除非法字符
        if self._strip_illegal:
            result = self.ILLEGAL_CHARS.sub("", result)
        
        # 标准化大小写（首字母大写）
        if self._normalize_case:
            # 保持每个单词首字母大写
            words = result.replace(self.SPACE_REPLACEMENT, " ").replace(self.SEPARATOR, " ").split()
            result = self.SPACE_REPLACEMENT.join(w.capitalize() for w in words)
        
        return result
    
    def build(self) -> str:
        """
        构建UCS文件名
        
        Returns:
            完整的UCS文件名
            
        Raises:
            ValueError: 如果缺少必需的组件
        """
        if not self._category:
            raise ValueError("类别（Category）是必需的")
        if not self._subcategory:
            raise ValueError("子类别（Subcategory）是必需的")
        
        parts: List[str] = []
        
        # 添加创建者ID（如果有）
        if self._creator_id:
            parts.append(self._creator_id)
        
        # 添加必需组件
        parts.append(self._category)
        parts.append(self._subcategory)
        
        # 添加可选组件
        if self._descriptor:
            parts.append(self._descriptor)
        
        if self._variation:
            parts.append(self._variation)
        
        if self._version:
            parts.append(self._version)
        
        # 构建文件名
        name = self.SEPARATOR.join(parts)
        
        # 添加扩展名
        if self._extension:
            name = f"{name}.{self._extension}"
        
        return name
    
    def build_components(self) -> UCSComponents:
        """构建UCS组件对象"""
        return UCSComponents(
            category=self._category,
            subcategory=self._subcategory,
            descriptor=self._descriptor,
            variation=self._variation,
            version=self._version,
            extension=self._extension,
            creator_id=self._creator_id,
        )
    
    def preview(self) -> str:
        """
        预览构建结果（不抛出异常）
        
        Returns:
            预览的文件名，如果缺少必需组件则返回部分结果
        """
        try:
            return self.build()
        except ValueError:
            # 返回部分结果
            parts = []
            if self._creator_id:
                parts.append(self._creator_id)
            if self._category:
                parts.append(self._category)
            if self._subcategory:
                parts.append(self._subcategory)
            if self._descriptor:
                parts.append(self._descriptor)
            if self._variation:
                parts.append(self._variation)
            if self._version:
                parts.append(self._version)
            
            name = self.SEPARATOR.join(parts) if parts else "[未命名]"
            if self._extension:
                name = f"{name}.{self._extension}"
            return name
    
    @staticmethod
    def quick_build(
        category: str,
        subcategory: str,
        descriptor: str = "",
        variation: str = "",
        version: str = "",
        extension: str = "wav",
    ) -> str:
        """
        快速构建UCS文件名
        
        静态方法，无需创建实例。
        """
        builder = UCSBuilder()
        builder.category(category)
        builder.subcategory(subcategory)
        
        if descriptor:
            builder.descriptor(descriptor)
        if variation:
            builder.variation(variation)
        if version:
            builder.version(version)
        if extension:
            builder.extension(extension)
        
        return builder.build()
