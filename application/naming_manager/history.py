"""
Rename History

重命名历史记录，支持撤销操作。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class RenameHistoryEntry:
    """重命名历史条目"""
    
    batch_id: str           # 批次ID
    source: str             # 源文件路径
    target: str             # 目标文件路径
    timestamp: datetime     # 时间戳
    
    # 可选元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "batch_id": self.batch_id,
            "source": self.source,
            "target": self.target,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RenameHistoryEntry:
        """从字典创建"""
        return cls(
            batch_id=data.get("batch_id", ""),
            source=data.get("source", ""),
            target=data.get("target", ""),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat())),
            metadata=data.get("metadata", {}),
        )


class RenameHistory:
    """
    重命名历史管理器
    
    功能：
    - 记录重命名操作
    - 按批次管理
    - 支持撤销
    - 持久化存储
    """
    
    MAX_HISTORY_SIZE = 1000  # 最大历史记录数
    MAX_BATCHES = 50         # 最大批次数
    
    def __init__(self, config_dir: Optional[str] = None):
        self._entries: List[RenameHistoryEntry] = []
        self._config_dir = config_dir
        
        # 加载历史
        if config_dir:
            self._load()
    
    def add_entry(self, entry: RenameHistoryEntry) -> None:
        """添加历史条目"""
        self._entries.append(entry)
        
        # 限制历史大小
        if len(self._entries) > self.MAX_HISTORY_SIZE:
            self._entries = self._entries[-self.MAX_HISTORY_SIZE:]
    
    def get_all_entries(self) -> List[RenameHistoryEntry]:
        """获取所有历史条目"""
        return self._entries.copy()
    
    def get_batch(self, batch_id: str) -> List[RenameHistoryEntry]:
        """获取指定批次的条目"""
        return [e for e in self._entries if e.batch_id == batch_id]
    
    def get_last_batch(self) -> List[RenameHistoryEntry]:
        """获取最后一个批次的条目"""
        if not self._entries:
            return []
        
        last_batch_id = self._entries[-1].batch_id
        return self.get_batch(last_batch_id)
    
    def get_batch_ids(self) -> List[str]:
        """获取所有批次ID（按时间倒序）"""
        batch_ids = []
        seen = set()
        
        for entry in reversed(self._entries):
            if entry.batch_id not in seen:
                batch_ids.append(entry.batch_id)
                seen.add(entry.batch_id)
        
        return batch_ids
    
    def remove_batch(self, batch_id: str) -> int:
        """删除指定批次"""
        original_count = len(self._entries)
        self._entries = [e for e in self._entries if e.batch_id != batch_id]
        return original_count - len(self._entries)
    
    def remove_last_batch(self) -> int:
        """删除最后一个批次"""
        if not self._entries:
            return 0
        
        last_batch_id = self._entries[-1].batch_id
        return self.remove_batch(last_batch_id)
    
    def clear(self) -> None:
        """清空历史"""
        self._entries.clear()
    
    def save(self) -> None:
        """保存历史到文件"""
        if not self._config_dir:
            return
        
        history_file = Path(self._config_dir) / "rename_history.json"
        
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = [e.to_dict() for e in self._entries]
            
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"保存了 {len(data)} 条重命名历史")
            
        except Exception as e:
            logger.error(f"保存重命名历史失败: {e}")
    
    def _load(self) -> None:
        """从文件加载历史"""
        if not self._config_dir:
            return
        
        history_file = Path(self._config_dir) / "rename_history.json"
        
        if not history_file.exists():
            return
        
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self._entries = [RenameHistoryEntry.from_dict(item) for item in data]
            
            logger.debug(f"加载了 {len(self._entries)} 条重命名历史")
            
        except Exception as e:
            logger.error(f"加载重命名历史失败: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        batch_ids = self.get_batch_ids()
        
        return {
            "total_entries": len(self._entries),
            "total_batches": len(batch_ids),
            "oldest_entry": self._entries[0].timestamp.isoformat() if self._entries else None,
            "newest_entry": self._entries[-1].timestamp.isoformat() if self._entries else None,
        }
    
    def search(
        self,
        query: str,
        limit: int = 100,
    ) -> List[RenameHistoryEntry]:
        """
        搜索历史记录
        
        Args:
            query: 搜索关键词（匹配源或目标路径）
            limit: 最大返回数量
            
        Returns:
            匹配的历史条目
        """
        query_lower = query.lower()
        results = []
        
        for entry in reversed(self._entries):
            if (query_lower in entry.source.lower() or 
                query_lower in entry.target.lower()):
                results.append(entry)
                if len(results) >= limit:
                    break
        
        return results
    
    def can_undo(self) -> bool:
        """是否可以撤销"""
        if not self._entries:
            return False
        
        # 检查最后一批的目标文件是否存在
        last_batch = self.get_last_batch()
        for entry in last_batch:
            if not Path(entry.target).exists():
                return False
        
        return True
    
    def get_undo_preview(self) -> List[Dict[str, str]]:
        """
        获取撤销预览
        
        Returns:
            将要撤销的操作列表 [{"from": target, "to": source}, ...]
        """
        last_batch = self.get_last_batch()
        return [
            {"from": e.target, "to": e.source}
            for e in reversed(last_batch)
        ]
