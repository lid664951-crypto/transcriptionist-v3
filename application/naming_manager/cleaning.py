import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class CleaningRule:
    """清洗规则数据模型"""
    def __init__(self, id: str, name: str, pattern: str, replacement: str, 
                 description: str = "", example: str = "", enabled: bool = True):
        self.id = id
        self.name = name
        self.pattern = pattern
        self.replacement = replacement
        self.description = description
        self.example = example
        self.enabled = enabled
    
    def apply(self, text: str) -> str:
        if not self.enabled:
            return text
        try:
            return re.sub(self.pattern, self.replacement, text)
        except Exception as e:
            logger.warning(f"Failed to apply rule {self.id}: {e}")
            return text
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "pattern": self.pattern,
            "replacement": self.replacement,
            "description": self.description,
            "enabled": self.enabled
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CleaningRule':
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            pattern=data.get("pattern", ""),
            replacement=data.get("replacement", ""),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            example=data.get("example", "")
        )

# 默认内置规则
DEFAULT_RULES = [
    CleaningRule(id="remove_parentheses", name="移除圆括号内容", pattern=r"\(.*?\)", replacement="", example="爆炸音效(新) -> 爆炸音效", description="删除所有圆括号及其内部内容"),
    CleaningRule(id="remove_sq_brackets", name="移除方括号内容", pattern=r"\[.*?\]", replacement="", example="爆炸音效[最终版] -> 爆炸音效", description="删除所有方括号及其内部内容"),
    CleaningRule(id="replace_underscore", name="下划线转空格", pattern=r"_", replacement=" ", example="Explosion_Large_Close -> Explosion Large Close", description="将下划线替换为空格，有助于AI生成更自然的中文词组"),
    CleaningRule("remove_special", "移除特殊字符", r'[@#$%^&*!]', '', "示例: 魔法声@v2! → 魔法声v2"),
    CleaningRule("remove_double_underscore", "移除多余下划线", r'_{2,}', '_', "示例: 脚步声__木质 → 脚步声_木质"),
    CleaningRule("trim_underscore", "移除首尾下划线", r'^_+|_+$', '', "示例: _环境声_ → 环境声"),
    CleaningRule("remove_number_suffix", "移除数字后缀", r'\d+$', '', "示例: 爆炸01 → 爆炸", False),
    CleaningRule("remove_version", "移除版本号", r'[_\-]?v\d+', '', "示例: 音效_v2 → 音效", False),
]

class CleaningManager:
    """
    清洗规则管理器 (Singleton)
    负责规则的持久化和应用。
    """
    _instance: Optional['CleaningManager'] = None
    
    def __init__(self, config_dir: Optional[Path] = None):
        self._rules: List[CleaningRule] = [r for r in DEFAULT_RULES]
        if config_dir:
            self._file_path = config_dir / "cleaning_rules.json"
        else:
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            self._file_path = get_data_dir() / "cleaning_rules.json"
        
        self.load()

    @classmethod
    def instance(cls, config_dir: Optional[Path] = None) -> 'CleaningManager':
        if cls._instance is None:
            cls._instance = cls(config_dir)
        return cls._instance

    def load(self):
        """加载已保存的状态"""
        if self._file_path.exists():
            try:
                with open(self._file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # data is a dict: {rule_id: enabled}
                for rule in self._rules:
                    if rule.id in data:
                        rule.enabled = data[rule.id]
                logger.info("Loaded cleaning rules state")
            except Exception as e:
                logger.error(f"Failed to load cleaning rules: {e}")

    def save(self):
        """保存规则状态"""
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            data = {r.id: r.enabled for r in self._rules}
            with open(self._file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Saved cleaning rules state")
        except Exception as e:
            logger.error(f"Failed to save cleaning rules: {e}")

    def get_rules(self) -> List[CleaningRule]:
        return self._rules

    def set_rule_enabled(self, rule_id: str, enabled: bool):
        for rule in self._rules:
            if rule.id == rule_id:
                rule.enabled = enabled
                self.save()
                break

    def apply_all(self, text: str) -> str:
        """应用所有启用的规则"""
        original = text
        for rule in self._rules:
            text = rule.apply(text)
        result = text.strip()
        logger.info(f"Cleaning: '{original}' -> '{result}'")
        return result
