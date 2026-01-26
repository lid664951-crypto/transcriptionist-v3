"""
Batch Rename Manager

批量重命名管理器，支持冲突检测和撤销。
参考Quod Libet的renamefiles模块设计。
"""

from __future__ import annotations

import os
import shutil
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Set, Callable, Tuple, TYPE_CHECKING
from datetime import datetime

from .validator import NamingValidator, ValidationResult
from .history import RenameHistory, RenameHistoryEntry

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ConflictResolution(Enum):
    """冲突解决策略"""
    
    SKIP = "skip"           # 跳过
    OVERWRITE = "overwrite" # 覆盖
    RENAME = "rename"       # 自动重命名（添加序号）
    ASK = "ask"             # 询问用户


@dataclass
class RenameOperation:
    """单个重命名操作"""
    
    source: str           # 源文件路径
    target: str           # 目标文件路径
    
    # 状态
    validated: bool = False
    validation_result: Optional[ValidationResult] = None
    
    # 执行结果
    executed: bool = False
    success: bool = False
    error: str = ""
    
    @property
    def source_name(self) -> str:
        """源文件名"""
        return Path(self.source).name
    
    @property
    def target_name(self) -> str:
        """目标文件名"""
        return Path(self.target).name
    
    @property
    def has_conflict(self) -> bool:
        """是否有冲突"""
        return os.path.exists(self.target) and self.source != self.target
    
    @property
    def is_same(self) -> bool:
        """源和目标是否相同"""
        return os.path.normpath(self.source) == os.path.normpath(self.target)


@dataclass
class RenameResult:
    """批量重命名结果"""
    
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    
    operations: List[RenameOperation] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def all_success(self) -> bool:
        """是否全部成功"""
        return self.failed == 0 and self.success == self.total


class BatchRenameManager:
    """
    批量重命名管理器
    
    功能：
    - 批量重命名文件
    - 冲突检测和解决
    - 预览模式
    - 撤销支持
    - 进度回调
    """
    
    def __init__(self, db_session: Optional['Session'] = None):
        self._validator = NamingValidator()
        self._history = RenameHistory()
        self._conflict_resolution = ConflictResolution.ASK
        self._db_session = db_session
        
        # 回调
        self._progress_callback: Optional[Callable[[int, int, str], None]] = None
        self._conflict_callback: Optional[Callable[[RenameOperation], ConflictResolution]] = None
    
    def set_conflict_resolution(self, resolution: ConflictResolution) -> None:
        """设置默认冲突解决策略"""
        self._conflict_resolution = resolution
    
    def set_progress_callback(
        self,
        callback: Callable[[int, int, str], None],
    ) -> None:
        """设置进度回调"""
        self._progress_callback = callback
    
    def set_conflict_callback(
        self,
        callback: Callable[[RenameOperation], ConflictResolution],
    ) -> None:
        """设置冲突回调"""
        self._conflict_callback = callback
    
    def create_operations(
        self,
        files: List[str],
        new_names: List[str],
        target_dir: Optional[str] = None,
    ) -> List[RenameOperation]:
        """
        创建重命名操作列表
        
        Args:
            files: 源文件路径列表
            new_names: 新文件名列表（仅文件名，不含路径）
            target_dir: 目标目录（如果为None，则使用源文件所在目录）
            
        Returns:
            重命名操作列表
        """
        if len(files) != len(new_names):
            raise ValueError("文件列表和新名称列表长度不匹配")
        
        operations = []
        
        for source, new_name in zip(files, new_names):
            source_path = Path(source)
            
            # 确定目标目录
            if target_dir:
                dest_dir = target_dir
            else:
                dest_dir = str(source_path.parent)
            
            # 构建目标路径
            target = os.path.join(dest_dir, new_name)
            
            operations.append(RenameOperation(
                source=str(source_path),
                target=target,
            ))
        
        return operations
    
    def validate_operations(
        self,
        operations: List[RenameOperation],
    ) -> Tuple[List[RenameOperation], List[str]]:
        """
        验证重命名操作
        
        Returns:
            (验证后的操作列表, 错误消息列表)
        """
        errors = []
        existing_names: Set[str] = set()
        
        for op in operations:
            # 跳过相同的源和目标
            if op.is_same:
                op.validated = True
                continue
            
            # 验证目标文件名
            target_dir = str(Path(op.target).parent)
            result = self._validator.validate(
                op.target_name,
                target_dir=target_dir,
                existing_names=existing_names,
            )
            
            op.validated = True
            op.validation_result = result
            
            if not result.is_valid:
                errors.extend(
                    f"{op.source_name}: {msg}"
                    for msg in result.error_messages
                )
            
            # 添加到已存在名称集合（用于检测批量操作内的重复）
            existing_names.add(op.target_name)
        
        return operations, errors
    
    def detect_conflicts(
        self,
        operations: List[RenameOperation],
    ) -> List[RenameOperation]:
        """
        检测冲突
        
        Returns:
            有冲突的操作列表
        """
        conflicts = []
        
        # 检查目标文件是否已存在
        for op in operations:
            if op.has_conflict:
                conflicts.append(op)
        
        # 检查批量操作内的冲突（多个源文件重命名为相同目标）
        target_map: Dict[str, List[RenameOperation]] = {}
        for op in operations:
            target_lower = op.target.lower()
            if target_lower not in target_map:
                target_map[target_lower] = []
            target_map[target_lower].append(op)
        
        for target, ops in target_map.items():
            if len(ops) > 1:
                conflicts.extend(ops)
        
        return list(set(conflicts))
    
    def resolve_conflict(
        self,
        operation: RenameOperation,
        resolution: Optional[ConflictResolution] = None,
    ) -> RenameOperation:
        """
        解决单个冲突
        
        Args:
            operation: 有冲突的操作
            resolution: 解决策略（如果为None，使用默认策略或回调）
            
        Returns:
            解决后的操作
        """
        if resolution is None:
            if self._conflict_callback:
                resolution = self._conflict_callback(operation)
            else:
                resolution = self._conflict_resolution
        
        if resolution == ConflictResolution.SKIP:
            operation.executed = True
            operation.success = False
            operation.error = "跳过（冲突）"
            
        elif resolution == ConflictResolution.OVERWRITE:
            # 保持原目标，执行时会覆盖
            pass
            
        elif resolution == ConflictResolution.RENAME:
            # 自动重命名
            operation.target = self._generate_unique_name(operation.target)
        
        return operation
    
    def _generate_unique_name(self, path: str) -> str:
        """生成唯一的文件名"""
        p = Path(path)
        stem = p.stem
        suffix = p.suffix
        parent = p.parent
        
        counter = 1
        while True:
            new_name = f"{stem}_{counter:02d}{suffix}"
            new_path = parent / new_name
            if not new_path.exists():
                return str(new_path)
            counter += 1
            if counter > 999:
                raise ValueError(f"无法生成唯一文件名: {path}")
    
    def execute(
        self,
        operations: List[RenameOperation],
        dry_run: bool = False,
    ) -> RenameResult:
        """
        执行批量重命名
        
        Args:
            operations: 重命名操作列表
            dry_run: 是否为预览模式（不实际执行）
            
        Returns:
            重命名结果
        """
        result = RenameResult(total=len(operations))
        
        # 创建历史记录批次
        batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for i, op in enumerate(operations):
            # 进度回调
            if self._progress_callback:
                self._progress_callback(i + 1, len(operations), op.source_name)
            
            # 跳过相同的源和目标
            if op.is_same:
                result.skipped += 1
                op.executed = True
                op.success = True
                continue
            
            # 跳过已标记为跳过的操作
            if op.executed and not op.success:
                result.skipped += 1
                continue
            
            # 检查验证结果
            if op.validation_result and not op.validation_result.is_valid:
                result.failed += 1
                op.executed = True
                op.success = False
                op.error = "; ".join(op.validation_result.error_messages)
                result.errors.append(f"{op.source_name}: {op.error}")
                continue
            
            # 处理冲突
            if op.has_conflict:
                op = self.resolve_conflict(op)
                if op.executed and not op.success:
                    result.skipped += 1
                    continue
            
            # 执行重命名
            if dry_run:
                op.executed = True
                op.success = True
                result.success += 1
            else:
                try:
                    self._do_rename(op)
                    op.executed = True
                    op.success = True
                    result.success += 1
                    
                    # 记录历史
                    self._history.add_entry(RenameHistoryEntry(
                        batch_id=batch_id,
                        source=op.source,
                        target=op.target,
                        timestamp=datetime.now(),
                    ))
                    
                except Exception as e:
                    op.executed = True
                    op.success = False
                    op.error = str(e)
                    result.failed += 1
                    result.errors.append(f"{op.source_name}: {e}")
                    logger.error(f"重命名失败: {op.source} -> {op.target}, 错误: {e}")
            
            result.operations.append(op)
        
        # 保存历史
        if not dry_run and result.success > 0:
            self._history.save()
        
        return result
    
    def _do_rename(self, operation: RenameOperation) -> None:
        """执行单个重命名操作"""
        source = operation.source
        target = operation.target
        
        # 确保目标目录存在
        target_dir = Path(target).parent
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # 如果目标存在且是覆盖模式，先删除
        if os.path.exists(target) and source != target:
            os.remove(target)
        
        # 重命名（或移动）
        shutil.move(source, target)
        
        # 同步更新数据库路径
        self._update_database_path(source, target)
        
        logger.info(f"重命名: {source} -> {target}")
    
    def _update_database_path(self, old_path: str, new_path: str) -> None:
        """
        更新数据库中的文件路径
        
        Args:
            old_path: 旧文件路径
            new_path: 新文件路径
        """
        if not self._db_session:
            logger.warning("数据库会话未设置，跳过路径更新")
            return
        
        try:
            from ...infrastructure.database.models import AudioFile
            
            # 规范化路径（处理路径分隔符差异）
            old_path_normalized = os.path.normpath(old_path)
            new_path_normalized = os.path.normpath(new_path)
            
            # 查找数据库中的记录
            audio_file = self._db_session.query(AudioFile).filter(
                AudioFile.file_path == old_path_normalized
            ).first()
            
            if audio_file:
                # 更新路径和文件名
                audio_file.file_path = new_path_normalized
                audio_file.filename = Path(new_path).name
                audio_file.modified_at = datetime.utcnow()
                
                self._db_session.commit()
                logger.info(f"数据库路径已更新: {old_path} -> {new_path}")
            else:
                logger.warning(f"数据库中未找到文件记录: {old_path}")
                
        except Exception as e:
            logger.error(f"更新数据库路径失败: {e}")
            if self._db_session:
                self._db_session.rollback()
            # 不抛出异常，避免影响重命名操作
    
    def undo_last_batch(self) -> RenameResult:
        """撤销最后一批重命名操作"""
        entries = self._history.get_last_batch()
        
        if not entries:
            return RenameResult(total=0)
        
        # 反向执行（从目标恢复到源）
        operations = [
            RenameOperation(source=e.target, target=e.source)
            for e in reversed(entries)
        ]
        
        result = self.execute(operations)
        
        # 如果成功，从历史中移除
        if result.all_success:
            self._history.remove_last_batch()
        
        return result
    
    def preview(
        self,
        files: List[str],
        new_names: List[str],
        target_dir: Optional[str] = None,
    ) -> RenameResult:
        """
        预览重命名结果
        
        不实际执行，只返回预期结果。
        """
        operations = self.create_operations(files, new_names, target_dir)
        operations, errors = self.validate_operations(operations)
        
        # 检测冲突
        conflicts = self.detect_conflicts(operations)
        for op in conflicts:
            if self._conflict_resolution == ConflictResolution.RENAME:
                op.target = self._generate_unique_name(op.target)
        
        return self.execute(operations, dry_run=True)
    
    @property
    def history(self) -> RenameHistory:
        """获取历史记录"""
        return self._history
