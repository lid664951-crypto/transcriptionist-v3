"""
Database Infrastructure Module

Provides database models, connection management, and backup functionality.
"""

from .models import (
    Base,
    AudioFile,
    AudioFileTag,
    AudioFileCustomField,
    Project,
    SavedSearch,
    LibraryPath,
    WaveformCache,
    RenameHistory,
    project_files,
)

from .connection import (
    DatabaseManager,
    get_db_manager,
    get_session,
    session_scope,
)

from .backup import (
    BackupManager,
    get_backup_manager,
    create_backup,
    restore_latest_backup,
)

__all__ = [
    # Models
    "Base",
    "AudioFile",
    "AudioFileTag",
    "AudioFileCustomField",
    "Project",
    "SavedSearch",
    "LibraryPath",
    "WaveformCache",
    "RenameHistory",
    "project_files",
    # Connection
    "DatabaseManager",
    "get_db_manager",
    "get_session",
    "session_scope",
    # Backup
    "BackupManager",
    "get_backup_manager",
    "create_backup",
    "restore_latest_backup",
]
