import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class GlossaryManager:
    """
    术语库管理器 (Singleton)
    负责术语库的加载、保存、查询。
    """
    _instance: Optional['GlossaryManager'] = None
    
    def __init__(self, config_dir: Optional[Path] = None):
        self._glossary: Dict[str, str] = {}
        if config_dir:
            self._file_path = config_dir / "glossary.json"
        else:
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            self._file_path = get_data_dir() / "glossary.json"
        
        self.load()

    @classmethod
    def instance(cls, config_dir: Optional[Path] = None) -> 'GlossaryManager':
        if cls._instance is None:
            cls._instance = cls(config_dir)
        return cls._instance

    def load(self):
        """从 JSON 加载"""
        if self._file_path.exists():
            try:
                with open(self._file_path, 'r', encoding='utf-8') as f:
                    self._glossary = json.load(f)
                logger.info(f"Loaded {len(self._glossary)} glossary terms")
            except Exception as e:
                logger.error(f"Failed to load glossary: {e}")

    def save(self):
        """保存到 JSON"""
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file_path, 'w', encoding='utf-8') as f:
                json.dump(self._glossary, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(self._glossary)} glossary terms")
        except Exception as e:
            logger.error(f"Failed to save glossary: {e}")

    def get_all(self) -> Dict[str, str]:
        return self._glossary.copy()

    def update(self, glossary: Dict[str, str]):
        self._glossary.update(glossary)
        self.save()

    def add_term(self, en: str, zh: str):
        self._glossary[en] = zh
        self.save()

    def remove_term(self, en: str):
        if en in self._glossary:
            del self._glossary[en]
            self.save()

    def clear(self):
        self._glossary.clear()
        self.save()
