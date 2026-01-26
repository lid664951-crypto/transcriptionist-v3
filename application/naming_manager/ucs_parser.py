"""
UCS Parser

解析UCS（Universal Category System）命名格式的文件名。
UCS是音效行业标准的命名规范。

命名格式: Category_Subcategory_Descriptor_Variation_Version.ext
示例: Explosion_Large_Debris_01_v1.wav
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from transcriptionist_v3.domain.models import UCSComponents

logger = logging.getLogger(__name__)


@dataclass
class UCSParseResult:
    """UCS解析结果"""
    
    success: bool
    components: Optional[UCSComponents] = None
    original: str = ""
    error: str = ""
    warnings: List[str] = field(default_factory=list)
    
    @property
    def is_valid_ucs(self) -> bool:
        """是否为有效的UCS命名"""
        return self.success and self.components is not None and self.components.is_valid


class UCSParser:
    """
    UCS命名解析器
    
    支持多种UCS命名变体：
    - 标准格式: Category_Subcategory_Descriptor_Variation_Version.ext
    - 简化格式: Category_Subcategory_Descriptor.ext
    - 带创建者ID: CreatorID_Category_Subcategory_Descriptor.ext
    """
    
    # UCS标准分隔符
    SEPARATOR = "_"
    
    # 版本号模式 (v1, v2, V01, etc.)
    VERSION_PATTERN = re.compile(r'^[vV]?\d+$')
    
    # 变体号模式 (01, 02, A, B, etc.)
    VARIATION_PATTERN = re.compile(r'^(\d{1,3}|[A-Z])$')
    
    # 创建者ID模式 (通常是大写字母缩写)
    CREATOR_ID_PATTERN = re.compile(r'^[A-Z]{2,5}$')
    
    # 常见的UCS类别（用于识别）
    KNOWN_CATEGORIES = {
        "AMB", "AMBIENCE", "AMBIANCE",
        "ANM", "ANIMAL", "ANIMALS",
        "CART", "CARTOON",
        "CRWD", "CROWD", "CROWDS",
        "DEST", "DESTRUCTION",
        "DOOR", "DOORS",
        "ELEC", "ELECTRONIC", "ELECTRONICS",
        "EXPL", "EXPLOSION", "EXPLOSIONS",
        "FIRE",
        "FOLY", "FOLEY",
        "FTST", "FOOTSTEP", "FOOTSTEPS",
        "HSHD", "HOUSEHOLD",
        "HMN", "HUMAN",
        "IMPT", "IMPACT", "IMPACTS",
        "INDL", "INDUSTRIAL",
        "MACH", "MACHINE", "MACHINES",
        "MATL", "MATERIAL", "MATERIALS",
        "MOVE", "MOVEMENT",
        "MUS", "MUSIC",
        "NAT", "NATURE",
        "OFFC", "OFFICE",
        "SCFI", "SCI-FI", "SCIFI",
        "SPRT", "SPORT", "SPORTS",
        "TECH", "TECHNOLOGY",
        "TOOL", "TOOLS",
        "TRAN", "TRANSPORT", "TRANSPORTATION",
        "UI", "INTERFACE",
        "VHCL", "VEHICLE", "VEHICLES",
        "WATR", "WATER",
        "WEAP", "WEAPON", "WEAPONS",
        "WTHR", "WEATHER",
        "WHSH", "WHOOSH",
    }
    
    def __init__(self):
        self._custom_categories: set = set()
    
    def add_custom_category(self, category: str) -> None:
        """添加自定义类别"""
        self._custom_categories.add(category.upper())
    
    def parse(self, filename: str) -> UCSParseResult:
        """
        解析文件名为UCS组件
        
        Args:
            filename: 文件名（可以包含路径）
            
        Returns:
            UCSParseResult: 解析结果
        """
        try:
            # 提取文件名和扩展名
            path = Path(filename)
            name = path.stem
            extension = path.suffix.lstrip(".")
            
            if not name:
                return UCSParseResult(
                    success=False,
                    original=filename,
                    error="空文件名",
                )
            
            # 分割组件
            parts = name.split(self.SEPARATOR)
            
            if len(parts) < 2:
                return UCSParseResult(
                    success=False,
                    original=filename,
                    error="文件名不符合UCS格式（至少需要类别和子类别）",
                )
            
            # 解析组件
            components, warnings = self._parse_parts(parts, extension)
            
            return UCSParseResult(
                success=True,
                components=components,
                original=filename,
                warnings=warnings,
            )
            
        except Exception as e:
            logger.error(f"解析UCS文件名失败: {filename}, 错误: {e}")
            return UCSParseResult(
                success=False,
                original=filename,
                error=str(e),
            )
    
    def _parse_parts(
        self, 
        parts: List[str], 
        extension: str
    ) -> Tuple[UCSComponents, List[str]]:
        """
        解析分割后的组件
        
        支持多种格式：
        1. Category_Subcategory
        2. Category_Subcategory_Descriptor
        3. Category_Subcategory_Descriptor_Variation
        4. Category_Subcategory_Descriptor_Variation_Version
        5. CreatorID_Category_Subcategory_...
        """
        warnings = []
        creator_id = ""
        
        # 检查第一个部分是否是创建者ID
        if len(parts) > 2 and self._is_creator_id(parts[0]):
            creator_id = parts[0]
            parts = parts[1:]
            warnings.append(f"检测到创建者ID: {creator_id}")
        
        # 至少需要类别和子类别
        if len(parts) < 2:
            return UCSComponents(extension=extension, creator_id=creator_id), warnings
        
        category = parts[0]
        subcategory = parts[1]
        descriptor = ""
        variation = ""
        version = ""
        
        # 检查类别是否已知
        if not self._is_known_category(category):
            warnings.append(f"未知的UCS类别: {category}")
        
        # 解析剩余部分
        remaining = parts[2:]
        
        if remaining:
            # 从后向前解析版本号和变体号
            if remaining and self._is_version(remaining[-1]):
                version = remaining.pop()
            
            if remaining and self._is_variation(remaining[-1]):
                variation = remaining.pop()
            
            # 剩余的都是描述符
            if remaining:
                descriptor = self.SEPARATOR.join(remaining)
        
        components = UCSComponents(
            category=category,
            subcategory=subcategory,
            descriptor=descriptor,
            variation=variation,
            version=version,
            extension=extension,
            creator_id=creator_id,
        )
        
        return components, warnings
    
    def _is_creator_id(self, text: str) -> bool:
        """检查是否是创建者ID"""
        return bool(self.CREATOR_ID_PATTERN.match(text))
    
    def _is_known_category(self, category: str) -> bool:
        """检查是否是已知类别"""
        upper = category.upper()
        return upper in self.KNOWN_CATEGORIES or upper in self._custom_categories
    
    def _is_version(self, text: str) -> bool:
        """检查是否是版本号"""
        return bool(self.VERSION_PATTERN.match(text))
    
    def _is_variation(self, text: str) -> bool:
        """检查是否是变体号"""
        return bool(self.VARIATION_PATTERN.match(text))
    
    def parse_batch(self, filenames: List[str]) -> List[UCSParseResult]:
        """批量解析文件名"""
        return [self.parse(f) for f in filenames]
    
    def extract_category_info(self, filename: str) -> Dict[str, str]:
        """
        提取类别信息（简化版本）
        
        返回字典包含: category, subcategory, descriptor
        """
        result = self.parse(filename)
        
        if result.success and result.components:
            return {
                "category": result.components.category,
                "subcategory": result.components.subcategory,
                "descriptor": result.components.descriptor,
            }
        
        return {"category": "", "subcategory": "", "descriptor": ""}
