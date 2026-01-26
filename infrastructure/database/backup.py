"""
Database Backup Module

Provides automatic backup functionality for the database.

Validates: Requirements 10.3
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class BackupManager:
    """
    Manages database backups.
    
    Features:
    - Create database backups
    - Automatic backup rotation
    - Restore from backup
    """
    
    def __init__(self, db_path: Path, backup_dir: Path, max_backups: int = 7):
        """
        Initialize the backup manager.
        
        Args:
            db_path: Path to the database file
            backup_dir: Directory to store backups
            max_backups: Maximum number of backups to keep
        """
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.max_backups = max_backups
    
    def create_backup(self) -> Optional[Path]:
        """
        Create a backup of the database.
        
        Returns:
            Path: Path to the backup file, or None if failed
        """
        if not self.db_path.exists():
            logger.warning(f"Database file not found: {self.db_path}")
            return None
        
        try:
            # Ensure backup directory exists
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"transcriptionist_{timestamp}.db"
            backup_path = self.backup_dir / backup_name
            
            # Copy database file
            shutil.copy2(self.db_path, backup_path)
            
            logger.info(f"Database backup created: {backup_path}")
            
            # Rotate old backups
            self._rotate_backups()
            
            return backup_path
            
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return None
    
    def _rotate_backups(self) -> None:
        """Remove old backups exceeding the maximum count."""
        backups = self.list_backups()
        
        if len(backups) > self.max_backups:
            # Sort by modification time (oldest first)
            backups.sort(key=lambda p: p.stat().st_mtime)
            
            # Remove oldest backups
            for backup in backups[:-self.max_backups]:
                try:
                    backup.unlink()
                    logger.debug(f"Removed old backup: {backup}")
                except Exception as e:
                    logger.warning(f"Failed to remove old backup {backup}: {e}")
    
    def list_backups(self) -> List[Path]:
        """
        List all available backups.
        
        Returns:
            List[Path]: List of backup file paths
        """
        if not self.backup_dir.exists():
            return []
        
        return list(self.backup_dir.glob("transcriptionist_*.db"))
    
    def get_latest_backup(self) -> Optional[Path]:
        """
        Get the most recent backup.
        
        Returns:
            Path: Path to the latest backup, or None if no backups exist
        """
        backups = self.list_backups()
        
        if not backups:
            return None
        
        # Sort by modification time (newest first)
        backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return backups[0]
    
    def restore_backup(self, backup_path: Path) -> bool:
        """
        Restore the database from a backup.
        
        Args:
            backup_path: Path to the backup file
            
        Returns:
            bool: True if restored successfully
        """
        if not backup_path.exists():
            logger.error(f"Backup file not found: {backup_path}")
            return False
        
        try:
            # Create a backup of current database before restoring
            if self.db_path.exists():
                current_backup = self.db_path.with_suffix(".db.before_restore")
                shutil.copy2(self.db_path, current_backup)
                logger.info(f"Current database backed up to: {current_backup}")
            
            # Restore from backup
            shutil.copy2(backup_path, self.db_path)
            logger.info(f"Database restored from: {backup_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore backup: {e}")
            return False


# Global backup manager instance
_backup_manager: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    """
    Get the global backup manager.
    
    Returns:
        BackupManager: The backup manager instance
    """
    global _backup_manager
    
    if _backup_manager is None:
        from transcriptionist_v3.runtime.runtime_config import get_runtime_config
        from transcriptionist_v3.core.config import get_config
        
        config = get_runtime_config()
        max_backups = get_config("backup.max_backups", 7)
        
        _backup_manager = BackupManager(
            db_path=config.paths.database_dir / "transcriptionist.db",
            backup_dir=config.paths.backups_dir,
            max_backups=max_backups
        )
    
    return _backup_manager


def create_backup() -> Optional[Path]:
    """
    Create a database backup.
    
    Returns:
        Path: Path to the backup file
    """
    return get_backup_manager().create_backup()


def restore_latest_backup() -> bool:
    """
    Restore from the latest backup.
    
    Returns:
        bool: True if restored successfully
    """
    manager = get_backup_manager()
    latest = manager.get_latest_backup()
    
    if latest:
        return manager.restore_backup(latest)
    
    logger.warning("No backups available to restore")
    return False
