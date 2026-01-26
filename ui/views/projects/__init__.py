"""
Project Management UI Views

Provides GTK4/Libadwaita UI components for project management.
Inspired by Quod Libet's mature playlist browser patterns.
"""

from .project_list_view import ProjectListView
from .project_files_view import ProjectFilesView
from .project_sidebar import ProjectSidebar

__all__ = [
    'ProjectListView',
    'ProjectFilesView',
    'ProjectSidebar',
]
