"""
Naming Manager Module

音译家的命名管理模块，提供UCS命名解析、构建、验证和批量重命名功能。
参考Quod Libet的renamefiles模块设计。
"""

from .ucs_parser import UCSParser, UCSParseResult
from .ucs_builder import UCSBuilder
from .validator import NamingValidator, ValidationResult, ValidationError
from .batch_rename import (
    BatchRenameManager,
    RenameOperation,
    RenameResult,
    ConflictResolution,
)
from .templates import (
    NamingTemplate,
    TemplateManager,
    TemplateVariable,
    BUILTIN_TEMPLATES,
)
from .history import RenameHistory, RenameHistoryEntry

__all__ = [
    # Parser
    'UCSParser',
    'UCSParseResult',
    # Builder
    'UCSBuilder',
    # Validator
    'NamingValidator',
    'ValidationResult',
    'ValidationError',
    # Batch Rename
    'BatchRenameManager',
    'RenameOperation',
    'RenameResult',
    'ConflictResolution',
    # Templates
    'NamingTemplate',
    'TemplateManager',
    'TemplateVariable',
    'BUILTIN_TEMPLATES',
    # History
    'RenameHistory',
    'RenameHistoryEntry',
]
