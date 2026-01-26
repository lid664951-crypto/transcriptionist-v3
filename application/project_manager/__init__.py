"""
Project Manager Module

Provides project management functionality for organizing audio files.
Inspired by Quod Libet's mature playlist system.

Features:
- Project CRUD operations
- File-to-project associations
- Project export with file copying
- Project templates
- Metadata export (JSON sidecar files)
"""

from .manager import ProjectManager
from .repository import ProjectRepository
from .exporter import ProjectExporter
from .templates import ProjectTemplateManager, ProjectTemplate

__all__ = [
    'ProjectManager',
    'ProjectRepository',
    'ProjectExporter',
    'ProjectTemplateManager',
    'ProjectTemplate',
]
