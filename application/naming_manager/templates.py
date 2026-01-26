"""
Naming Templates

自定义命名模板系统，支持变量替换和条件逻辑。
参考Quod Libet的pattern模块设计。
"""

from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class TemplateVariable(Enum):
    """模板变量"""
    
    # 文件信息
    FILENAME = "filename"           # 原文件名（不含扩展名）
    EXTENSION = "extension"         # 扩展名
    DIRNAME = "dirname"             # 目录名
    
    # UCS组件
    CATEGORY = "category"           # 类别
    SUBCATEGORY = "subcategory"     # 子类别
    DESCRIPTOR = "descriptor"       # 描述符
    VARIATION = "variation"         # 变体号
    VERSION = "version"             # 版本号
    
    # 元数据
    TITLE = "title"                 # 标题
    ARTIST = "artist"               # 艺术家
    ALBUM = "album"                 # 专辑
    GENRE = "genre"                 # 流派
    YEAR = "year"                   # 年份
    
    # 技术信息
    DURATION = "duration"           # 时长
    SAMPLERATE = "samplerate"       # 采样率
    CHANNELS = "channels"           # 声道数
    BITDEPTH = "bitdepth"           # 位深
    
    # 序号
    INDEX = "index"                 # 序号（批量重命名时）
    INDEX_PADDED = "index_padded"   # 补零序号
    
    # 日期时间
    DATE = "date"                   # 当前日期
    TIME = "time"                   # 当前时间
    DATETIME = "datetime"           # 日期时间
    
    # 翻译
    TRANSLATED = "translated"       # 翻译后的名称


@dataclass
class NamingTemplate:
    """
    命名模板
    
    模板语法：
    - {variable} - 变量替换
    - {variable|default} - 带默认值的变量
    - {variable:format} - 带格式的变量
    - [condition|if_true|if_false] - 条件表达式
    """
    
    id: str
    name: str
    pattern: str
    description: str = ""
    
    # 元数据
    category: str = "custom"  # builtin, custom, user
    is_builtin: bool = False
    
    def format(self, context: Dict[str, Any]) -> str:
        """
        使用上下文格式化模板
        
        Args:
            context: 变量上下文字典
            
        Returns:
            格式化后的字符串
        """
        result = self.pattern
        
        # 处理条件表达式 [condition|if_true|if_false]
        result = self._process_conditions(result, context)
        
        # 处理变量替换 {variable} 或 {variable|default}
        result = self._process_variables(result, context)
        
        return result
    
    def _process_conditions(self, text: str, context: Dict[str, Any]) -> str:
        """处理条件表达式"""
        # 匹配 [condition|if_true|if_false] 或 [condition|if_true]
        pattern = re.compile(r'\[([^|\]]+)\|([^|\]]*)\|?([^\]]*)\]')
        
        def replace_condition(match):
            condition = match.group(1).strip()
            if_true = match.group(2)
            if_false = match.group(3) if match.group(3) else ""
            
            # 评估条件
            value = context.get(condition, "")
            if value:
                return if_true
            return if_false
        
        return pattern.sub(replace_condition, text)
    
    def _process_variables(self, text: str, context: Dict[str, Any]) -> str:
        """处理变量替换"""
        # 匹配 {variable}, {variable|default}, {variable:format}
        pattern = re.compile(r'\{([^}:]+)(?::([^}|]+))?(?:\|([^}]*))?\}')
        
        def replace_variable(match):
            var_name = match.group(1).strip()
            format_spec = match.group(2)
            default = match.group(3) if match.group(3) is not None else ""
            
            # 获取值
            value = context.get(var_name, default)
            
            # 应用格式
            if format_spec and value:
                try:
                    if format_spec.startswith("0") and format_spec[1:].isdigit():
                        # 补零格式 {index:03}
                        width = int(format_spec[1:])
                        value = str(value).zfill(width)
                    elif format_spec == "upper":
                        value = str(value).upper()
                    elif format_spec == "lower":
                        value = str(value).lower()
                    elif format_spec == "title":
                        value = str(value).title()
                except Exception:
                    pass
            
            return str(value) if value else default
        
        return pattern.sub(replace_variable, text)
    
    def get_variables(self) -> List[str]:
        """获取模板中使用的变量列表"""
        # 提取 {variable} 中的变量名
        var_pattern = re.compile(r'\{([^}:]+)(?::[^}|]+)?(?:\|[^}]*)?\}')
        variables = var_pattern.findall(self.pattern)
        
        # 提取条件中的变量名
        cond_pattern = re.compile(r'\[([^|\]]+)\|')
        conditions = cond_pattern.findall(self.pattern)
        
        return list(set(variables + conditions))
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "pattern": self.pattern,
            "description": self.description,
            "category": self.category,
            "is_builtin": self.is_builtin,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NamingTemplate:
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            pattern=data.get("pattern", ""),
            description=data.get("description", ""),
            category=data.get("category", "custom"),
            is_builtin=data.get("is_builtin", False),
        )


# 内置模板 (仅保留 4 种核心模板)
BUILTIN_TEMPLATES = [
    NamingTemplate(
        id="ucs_standard",
        name="UCS标准命名",
        pattern="{category}_{subcategory}_{translated}_{index}",
        description="EXPLOSION_BOMB_爆炸_1",
        category="builtin",
        is_builtin=True,
    ),
    NamingTemplate(
        id="bilingual",
        name="中英双语",
        pattern="【{translated}】{filename}",
        description="【爆炸】Explosion",
        category="builtin",
        is_builtin=True,
    ),
    NamingTemplate(
        id="numbered",
        name="序号命名",
        pattern="{translated}_{index}",
        description="爆炸_1",
        category="builtin",
        is_builtin=True,
    ),
    NamingTemplate(
        id="translated_only",
        name="仅译名",
        pattern="{translated}",
        description="爆炸",
        category="builtin",
        is_builtin=True,
    ),
]


class TemplateManager:
    """
    模板管理器
    
    管理内置和自定义命名模板。
    """
    
    _instance: Optional[TemplateManager] = None
    
    def __init__(self, config_dir: Optional[str] = None):
        self._templates: Dict[str, NamingTemplate] = {}
        self._config_dir = config_dir
        self._active_template_id = "translated_only"  # 默认使用翻译后名称
        
        # 加载内置模板
        for template in BUILTIN_TEMPLATES:
            self._templates[template.id] = template
        
        # 加载用户模板
        if config_dir:
            self._load_user_templates()
            self._load_settings()
    
    @classmethod
    def instance(cls, config_dir: Optional[str] = None) -> TemplateManager:
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls(config_dir)
        return cls._instance
    
    def get_template(self, template_id: str) -> Optional[NamingTemplate]:
        """获取模板"""
        return self._templates.get(template_id)
    
    def get_all_templates(self) -> List[NamingTemplate]:
        """获取所有模板"""
        return list(self._templates.values())
    
    def get_builtin_templates(self) -> List[NamingTemplate]:
        """获取内置模板"""
        return [t for t in self._templates.values() if t.is_builtin]
    
    def get_user_templates(self) -> List[NamingTemplate]:
        """获取用户模板"""
        return [t for t in self._templates.values() if not t.is_builtin]
    
    def add_template(self, template: NamingTemplate) -> None:
        """添加模板"""
        self._templates[template.id] = template
        self._save_user_templates()
    
    def remove_template(self, template_id: str) -> bool:
        """删除模板"""
        template = self._templates.get(template_id)
        if template and not template.is_builtin:
            del self._templates[template_id]
            self._save_user_templates()
            return True
        return False
    
    def update_template(self, template: NamingTemplate) -> bool:
        """更新模板"""
        if template.id in self._templates:
            if not self._templates[template.id].is_builtin:
                self._templates[template.id] = template
                self._save_user_templates()
                return True
        return False
    
    def format_with_template(
        self,
        template_id: str,
        context: Dict[str, Any],
    ) -> Optional[str]:
        """使用模板格式化"""
        template = self.get_template(template_id)
        if template:
            result = template.format(context)
            logger.info(f"Formatted template '{template_id}': '{template.pattern}' -> '{result}'")
            return result
        logger.warning(f"Template '{template_id}' not found for formatting")
        return None
        
    @property
    def active_template_id(self) -> str:
        return self._active_template_id
        
    @active_template_id.setter
    def active_template_id(self, value: str) -> None:
        if value in self._templates or value: # Allow custom patterns too if we want
            self._active_template_id = value
            self._save_settings()
            
    def get_active_pattern(self) -> str:
        """获取当前激活的模板内容"""
        template = self.get_template(self._active_template_id)
        if template:
            return template.pattern
        # Fallback for old default
        if self._active_template_id == "translated_only":
            return "{translated}"
        return self._active_template_id # 如果存的是自定义字符串直接返回
        
    def _load_settings(self) -> None:
        """加载设置"""
        if not self._config_dir:
            return
        settings_file = Path(self._config_dir) / "naming_settings.json"
        if settings_file.exists():
            try:
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._active_template_id = data.get("active_template_id", "translated_only")
            except Exception as e:
                logger.error(f"Failed to load naming settings: {e}")
                
    def _save_settings(self) -> None:
        """保存设置"""
        if not self._config_dir:
            return
        settings_file = Path(self._config_dir) / "naming_settings.json"
        try:
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump({"active_template_id": self._active_template_id}, f)
        except Exception as e:
            logger.error(f"Failed to save naming settings: {e}")
    
    def _load_user_templates(self) -> None:
        """加载用户模板"""
        if not self._config_dir:
            return
        
        templates_file = Path(self._config_dir) / "naming_templates.json"
        
        if templates_file.exists():
            try:
                with open(templates_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                for item in data:
                    template = NamingTemplate.from_dict(item)
                    template.is_builtin = False
                    self._templates[template.id] = template
                    
                logger.info(f"加载了 {len(data)} 个用户模板")
                
            except Exception as e:
                logger.error(f"加载用户模板失败: {e}")
    
    def _save_user_templates(self) -> None:
        """保存用户模板"""
        if not self._config_dir:
            return
        
        templates_file = Path(self._config_dir) / "naming_templates.json"
        
        try:
            user_templates = [
                t.to_dict() for t in self._templates.values()
                if not t.is_builtin
            ]
            
            templates_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(templates_file, "w", encoding="utf-8") as f:
                json.dump(user_templates, f, ensure_ascii=False, indent=2)
                
            logger.info(f"保存了 {len(user_templates)} 个用户模板")
            
        except Exception as e:
            logger.error(f"保存用户模板失败: {e}")
    
    def create_context(
        self,
        filename: str,
        ucs_components: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        index: int = 0,
        translated: str = "",
    ) -> Dict[str, Any]:
        """
        创建模板上下文
        
        Args:
            filename: 原始文件名
            ucs_components: UCS组件字典
            metadata: 元数据字典
            index: 序号（批量重命名时）
            translated: 翻译后的名称
            
        Returns:
            上下文字典
        """
        from datetime import datetime
        
        path = Path(filename)
        
        context = {
            # 文件信息
            "filename": path.stem,
            "original": path.stem,  # <--- Added alias for legacy template compatibility
            "extension": path.suffix.lstrip("."),
            "dirname": path.parent.name,
            
            # 序号
            "index": index,
            "index_padded": f"{index:03d}",
            
            # 日期时间
            "date": datetime.now().strftime("%Y%m%d"),
            "time": datetime.now().strftime("%H%M%S"),
            "datetime": datetime.now().strftime("%Y%m%d_%H%M%S"),
            
            # 翻译
            "translated": translated,
        }
        
        # 添加UCS组件
        if ucs_components:
            context.update({
                "category": ucs_components.get("category", ""),
                "subcategory": ucs_components.get("subcategory", ""),
                "descriptor": ucs_components.get("descriptor", ""),
                "variation": ucs_components.get("variation", ""),
                "version": ucs_components.get("version", ""),
            })
        
        # 添加元数据
        if metadata:
            context.update({
                "title": metadata.get("title", ""),
                "artist": metadata.get("artist", ""),
                "album": metadata.get("album", ""),
                "genre": metadata.get("genre", ""),
                "year": metadata.get("year", ""),
                "duration": metadata.get("duration", ""),
                "samplerate": metadata.get("sample_rate", ""),
                "channels": metadata.get("channels", ""),
                "bitdepth": metadata.get("bit_depth", ""),
            })
        
        return context
