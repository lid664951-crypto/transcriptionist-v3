"""
Translation Cache

翻译缓存服务，避免重复翻译相同内容。
"""

from __future__ import annotations

import json
import logging
import hashlib
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import threading

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    original: str
    translated: str
    provider_id: str
    created_at: str
    hit_count: int = 0


class TranslationCache:
    """
    翻译缓存
    
    功能：
    - 内存缓存 + 持久化存储
    - LRU淘汰策略
    - 按提供者分离缓存
    """
    
    _instance: Optional['TranslationCache'] = None
    _lock = threading.Lock()
    
    def __init__(self, cache_dir: Optional[Path] = None, max_size: int = 10000):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._dirty = False
        
        # 缓存文件路径
        if cache_dir is None:
            from ...core.config import get_data_dir
            cache_dir = get_data_dir() / "cache"
        
        self._cache_dir = cache_dir
        self._cache_file = cache_dir / "translation_cache.json"
        
        # 加载缓存
        self._load()
    
    @classmethod
    def instance(cls) -> 'TranslationCache':
        """获取单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def _make_key(self, text: str, provider_id: str = "") -> str:
        """生成缓存键"""
        content = f"{provider_id}:{text}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, text: str, provider_id: str = "") -> Optional[str]:
        """获取缓存的翻译"""
        key = self._make_key(text, provider_id)
        entry = self._cache.get(key)
        
        if entry:
            # 检测无效缓存：如果原文 == 译文，说明之前翻译失败，删除并返回 None
            if entry.original == entry.translated:
                del self._cache[key]
                self._dirty = True
                logger.debug(f"Removed invalid cache entry (original == translated): {text[:30]}...")
                return None
            
            entry.hit_count += 1
            self._dirty = True
            return entry.translated
        
        return None
    
    def has(self, text: str, provider_id: str = "") -> bool:
        """检查是否有缓存"""
        key = self._make_key(text, provider_id)
        return key in self._cache
    
    def set(self, text: str, translated: str, provider_id: str = "") -> None:
        """设置缓存"""
        key = self._make_key(text, provider_id)
        
        self._cache[key] = CacheEntry(
            original=text,
            translated=translated,
            provider_id=provider_id,
            created_at=datetime.now().isoformat(),
        )
        self._dirty = True
        
        # 检查是否需要淘汰
        if len(self._cache) > self._max_size:
            self._evict()
    
    def _evict(self) -> None:
        """淘汰最少使用的条目"""
        if not self._cache:
            return
        
        # 按hit_count排序，删除最少使用的20%
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k].hit_count,
        )
        
        evict_count = len(sorted_keys) // 5
        for key in sorted_keys[:evict_count]:
            del self._cache[key]
        
        logger.debug(f"Evicted {evict_count} cache entries")
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
        self._dirty = True
    
    def _load(self) -> None:
        """从文件加载缓存"""
        if not self._cache_file.exists():
            return
        
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            for key, entry_data in data.items():
                self._cache[key] = CacheEntry(**entry_data)
            
            logger.info(f"Loaded {len(self._cache)} cache entries")
            
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
    
    def save(self) -> None:
        """保存缓存到文件"""
        if not self._dirty:
            return
        
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            
            data = {
                key: asdict(entry)
                for key, entry in self._cache.items()
            }
            
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            self._dirty = False
            logger.debug(f"Saved {len(self._cache)} cache entries")
            
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
    
    @property
    def size(self) -> int:
        """缓存大小"""
        return len(self._cache)
    
    def get_stats(self) -> Dict:
        """获取缓存统计"""
        total_hits = sum(e.hit_count for e in self._cache.values())
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "total_hits": total_hits,
        }
