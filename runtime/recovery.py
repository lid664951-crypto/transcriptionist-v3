"""
Recovery Utilities Module

Provides recovery mechanisms for corrupted embedded environments.
Handles detection of corruption, provides recovery instructions,
and implements automated recovery where possible.

Validates: Requirements 12.6
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CorruptionType(Enum):
    """Types of environment corruption."""
    
    MISSING_PYTHON = "missing_python"
    MISSING_DEPENDENCIES = "missing_dependencies"
    CORRUPTED_DATABASE = "corrupted_database"
    CORRUPTED_CONFIG = "corrupted_config"
    MISSING_RESOURCES = "missing_resources"
    PATH_MISMATCH = "path_mismatch"
    PERMISSION_ERROR = "permission_error"
    UNKNOWN = "unknown"


@dataclass
class CorruptionIssue:
    """Represents a detected corruption issue."""
    
    corruption_type: CorruptionType
    description: str
    severity: str  # "critical", "warning", "info"
    recoverable: bool
    recovery_action: Optional[str] = None
    affected_path: Optional[Path] = None


@dataclass
class RecoveryResult:
    """Result of a recovery operation."""
    
    success: bool
    message: str
    actions_taken: list[str] = field(default_factory=list)
    remaining_issues: list[CorruptionIssue] = field(default_factory=list)


@dataclass
class EnvironmentHealth:
    """Overall health status of the environment."""
    
    is_healthy: bool
    issues: list[CorruptionIssue]
    last_check: datetime
    recovery_available: bool


class RecoveryManager:
    """
    Manages detection and recovery of corrupted environments.
    
    This class provides:
    - Environment health checks
    - Corruption detection
    - Recovery instructions
    - Automated recovery where possible
    """
    
    # Recovery instructions for different corruption types
    RECOVERY_INSTRUCTIONS = {
        CorruptionType.MISSING_PYTHON: """
The embedded Python runtime is missing or corrupted.

Recovery Steps:
1. Download the latest Transcriptionist installer from the official website
2. Run the installer to repair the installation
3. If the issue persists, perform a clean installation:
   a. Backup your data folder (contains your library database)
   b. Uninstall Transcriptionist completely
   c. Delete the installation folder
   d. Install Transcriptionist fresh
   e. Restore your data folder
""",
        CorruptionType.MISSING_DEPENDENCIES: """
Some required Python packages are missing.

Recovery Steps:
1. If running from source, reinstall dependencies:
   pip install -e ".[dev]"
   
2. If running from installer:
   a. Try running the repair option in the installer
   b. If that fails, reinstall the application
   
3. For portable installations:
   a. Download a fresh copy of the portable package
   b. Copy your 'data' folder to the new installation
""",
        CorruptionType.CORRUPTED_DATABASE: """
The library database appears to be corrupted.

Recovery Steps:
1. Check for automatic backups in the 'data/backups' folder
2. To restore from backup:
   a. Close Transcriptionist
   b. Rename the current database file (transcriptionist.db)
   c. Copy the backup file and rename it to transcriptionist.db
   d. Restart Transcriptionist
   
3. If no backups are available:
   a. Delete the corrupted database
   b. Restart Transcriptionist (a new database will be created)
   c. Re-scan your sound library folders
""",
        CorruptionType.CORRUPTED_CONFIG: """
The configuration file is corrupted or invalid.

Recovery Steps:
1. Transcriptionist will automatically use default settings
2. To reset configuration manually:
   a. Close Transcriptionist
   b. Delete the 'config' folder
   c. Restart Transcriptionist
   
3. Your library data will not be affected
""",
        CorruptionType.MISSING_RESOURCES: """
Application resources (icons, themes, etc.) are missing.

Recovery Steps:
1. Reinstall the application to restore resources
2. For portable installations, download a fresh copy
3. Your library data will not be affected
""",
        CorruptionType.PATH_MISMATCH: """
The application paths are misconfigured.

This can happen if:
- The application folder was moved without updating paths
- Environment variables are incorrectly set

Recovery Steps:
1. For portable installations:
   a. Ensure the entire application folder was moved together
   b. Do not move individual files or folders
   
2. For installed versions:
   a. Reinstall the application
   b. Or update the TRANSCRIPTIONIST_ROOT environment variable
""",
        CorruptionType.PERMISSION_ERROR: """
The application cannot access required files or folders.

Recovery Steps:
1. Check that you have read/write permissions for:
   - The application folder
   - The data folder
   - Your sound library folders
   
2. On Windows:
   a. Right-click the application folder
   b. Select Properties > Security
   c. Ensure your user has Full Control
   
3. On Linux/macOS:
   chmod -R u+rwX /path/to/transcriptionist
""",
        CorruptionType.UNKNOWN: """
An unknown issue was detected.

Recovery Steps:
1. Check the log files in 'data/logs' for more details
2. Try restarting the application
3. If the issue persists:
   a. Backup your 'data' folder
   b. Reinstall the application
   c. Restore your 'data' folder
   
4. Report the issue at: https://github.com/transcriptionist/issues
""",
    }
    
    def __init__(self):
        """Initialize the recovery manager."""
        self._last_health_check: Optional[EnvironmentHealth] = None
    
    def check_health(self) -> EnvironmentHealth:
        """
        Perform a comprehensive health check of the environment.
        
        Returns:
            EnvironmentHealth: Health status and any detected issues.
        """
        issues: list[CorruptionIssue] = []
        
        # Import here to avoid circular imports
        from .runtime_config import get_runtime_config
        
        try:
            config = get_runtime_config()
            paths = config.paths
        except Exception as e:
            issues.append(CorruptionIssue(
                corruption_type=CorruptionType.UNKNOWN,
                description=f"Cannot load runtime configuration: {e}",
                severity="critical",
                recoverable=False,
            ))
            return EnvironmentHealth(
                is_healthy=False,
                issues=issues,
                last_check=datetime.now(),
                recovery_available=False,
            )
        
        # Check Python runtime (for embedded mode)
        if config.is_embedded:
            python_issues = self._check_python_runtime(paths)
            issues.extend(python_issues)
        
        # Check dependencies
        dep_issues = self._check_dependencies()
        issues.extend(dep_issues)
        
        # Check database
        db_issues = self._check_database(paths)
        issues.extend(db_issues)
        
        # Check configuration
        config_issues = self._check_configuration(paths)
        issues.extend(config_issues)
        
        # Check resources
        resource_issues = self._check_resources(paths)
        issues.extend(resource_issues)
        
        # Check permissions
        perm_issues = self._check_permissions(paths)
        issues.extend(perm_issues)
        
        # Determine overall health
        critical_issues = [i for i in issues if i.severity == "critical"]
        is_healthy = len(critical_issues) == 0
        recovery_available = any(i.recoverable for i in issues)
        
        health = EnvironmentHealth(
            is_healthy=is_healthy,
            issues=issues,
            last_check=datetime.now(),
            recovery_available=recovery_available,
        )
        
        self._last_health_check = health
        return health
    
    def _check_python_runtime(self, paths) -> list[CorruptionIssue]:
        """Check the embedded Python runtime."""
        issues = []
        
        if not paths.python_executable.exists():
            issues.append(CorruptionIssue(
                corruption_type=CorruptionType.MISSING_PYTHON,
                description="Embedded Python executable not found",
                severity="critical",
                recoverable=False,
                affected_path=paths.python_executable,
            ))
        
        return issues
    
    def _check_dependencies(self) -> list[CorruptionIssue]:
        """Check for missing dependencies."""
        issues = []
        
        from .environment import validate_environment
        
        status = validate_environment()
        
        missing_deps = [
            d for d in status.dependency_statuses
            if not d.available
        ]
        
        if missing_deps:
            # Categorize by severity
            critical_deps = {"gi", "sqlalchemy", "numpy"}
            
            for dep in missing_deps:
                severity = "critical" if dep.name in critical_deps else "warning"
                issues.append(CorruptionIssue(
                    corruption_type=CorruptionType.MISSING_DEPENDENCIES,
                    description=f"Missing dependency: {dep.name}",
                    severity=severity,
                    recoverable=True,
                    recovery_action=f"Install {dep.name} package",
                ))
        
        return issues
    
    def _check_database(self, paths) -> list[CorruptionIssue]:
        """Check database integrity."""
        issues = []
        
        db_file = paths.database_dir / "transcriptionist.db"
        
        if db_file.exists():
            # Basic integrity check
            try:
                import sqlite3
                conn = sqlite3.connect(str(db_file))
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                conn.close()
                
                if result[0] != "ok":
                    issues.append(CorruptionIssue(
                        corruption_type=CorruptionType.CORRUPTED_DATABASE,
                        description=f"Database integrity check failed: {result[0]}",
                        severity="critical",
                        recoverable=True,
                        recovery_action="Restore from backup",
                        affected_path=db_file,
                    ))
            except Exception as e:
                issues.append(CorruptionIssue(
                    corruption_type=CorruptionType.CORRUPTED_DATABASE,
                    description=f"Cannot open database: {e}",
                    severity="critical",
                    recoverable=True,
                    recovery_action="Restore from backup or delete and rescan",
                    affected_path=db_file,
                ))
        
        return issues
    
    def _check_configuration(self, paths) -> list[CorruptionIssue]:
        """Check configuration files."""
        issues = []
        
        config_file = paths.config_dir / "config.json"
        
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    json.load(f)
            except json.JSONDecodeError as e:
                issues.append(CorruptionIssue(
                    corruption_type=CorruptionType.CORRUPTED_CONFIG,
                    description=f"Invalid configuration file: {e}",
                    severity="warning",
                    recoverable=True,
                    recovery_action="Delete config file to reset to defaults",
                    affected_path=config_file,
                ))
            except Exception as e:
                issues.append(CorruptionIssue(
                    corruption_type=CorruptionType.CORRUPTED_CONFIG,
                    description=f"Cannot read configuration: {e}",
                    severity="warning",
                    recoverable=True,
                    affected_path=config_file,
                ))
        
        return issues
    
    def _check_resources(self, paths) -> list[CorruptionIssue]:
        """Check application resources."""
        issues = []
        
        if not paths.resources_dir.exists():
            issues.append(CorruptionIssue(
                corruption_type=CorruptionType.MISSING_RESOURCES,
                description="Resources directory not found",
                severity="warning",
                recoverable=False,
                affected_path=paths.resources_dir,
            ))
        
        return issues
    
    def _check_permissions(self, paths) -> list[CorruptionIssue]:
        """Check file system permissions."""
        issues = []
        
        # Check write access to data directory
        test_file = paths.data_dir / ".permission_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
        except PermissionError:
            issues.append(CorruptionIssue(
                corruption_type=CorruptionType.PERMISSION_ERROR,
                description="Cannot write to data directory",
                severity="critical",
                recoverable=True,
                recovery_action="Fix directory permissions",
                affected_path=paths.data_dir,
            ))
        except Exception:
            pass  # Other errors are not permission issues
        
        return issues
    
    def get_recovery_instructions(
        self,
        corruption_type: CorruptionType
    ) -> str:
        """
        Get recovery instructions for a specific corruption type.
        
        Args:
            corruption_type: The type of corruption.
            
        Returns:
            str: Recovery instructions.
        """
        return self.RECOVERY_INSTRUCTIONS.get(
            corruption_type,
            self.RECOVERY_INSTRUCTIONS[CorruptionType.UNKNOWN]
        )
    
    def attempt_recovery(
        self,
        issues: Optional[list[CorruptionIssue]] = None
    ) -> RecoveryResult:
        """
        Attempt automatic recovery for detected issues.
        
        Args:
            issues: Specific issues to recover. If None, uses last health check.
            
        Returns:
            RecoveryResult: Result of recovery attempt.
        """
        if issues is None:
            if self._last_health_check is None:
                self.check_health()
            issues = self._last_health_check.issues if self._last_health_check else []
        
        actions_taken = []
        remaining_issues = []
        
        for issue in issues:
            if not issue.recoverable:
                remaining_issues.append(issue)
                continue
            
            recovered = False
            
            if issue.corruption_type == CorruptionType.CORRUPTED_CONFIG:
                recovered = self._recover_config(issue)
                if recovered:
                    actions_taken.append("Reset configuration to defaults")
            
            elif issue.corruption_type == CorruptionType.CORRUPTED_DATABASE:
                recovered = self._recover_database(issue)
                if recovered:
                    actions_taken.append("Restored database from backup")
            
            if not recovered:
                remaining_issues.append(issue)
        
        success = len(remaining_issues) == 0 or all(
            i.severity != "critical" for i in remaining_issues
        )
        
        if success:
            message = "Recovery completed successfully"
        elif actions_taken:
            message = "Partial recovery completed. Some issues require manual intervention."
        else:
            message = "Automatic recovery not possible. Please follow manual recovery instructions."
        
        return RecoveryResult(
            success=success,
            message=message,
            actions_taken=actions_taken,
            remaining_issues=remaining_issues,
        )
    
    def _recover_config(self, issue: CorruptionIssue) -> bool:
        """Attempt to recover corrupted configuration."""
        if issue.affected_path and issue.affected_path.exists():
            try:
                # Backup corrupted config
                backup_path = issue.affected_path.with_suffix(".json.corrupted")
                shutil.copy2(issue.affected_path, backup_path)
                
                # Delete corrupted config (app will use defaults)
                issue.affected_path.unlink()
                
                logger.info(f"Removed corrupted config, backup at {backup_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to recover config: {e}")
        return False
    
    def _recover_database(self, issue: CorruptionIssue) -> bool:
        """Attempt to recover corrupted database from backup."""
        from .runtime_config import get_runtime_config
        
        config = get_runtime_config()
        backups_dir = config.paths.backups_dir
        
        if not backups_dir.exists():
            return False
        
        # Find most recent backup
        backups = sorted(
            backups_dir.glob("transcriptionist_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        if not backups:
            return False
        
        latest_backup = backups[0]
        
        try:
            if issue.affected_path and issue.affected_path.exists():
                # Backup corrupted database
                corrupted_backup = issue.affected_path.with_suffix(".db.corrupted")
                shutil.copy2(issue.affected_path, corrupted_backup)
                issue.affected_path.unlink()
            
            # Restore from backup
            if issue.affected_path:
                shutil.copy2(latest_backup, issue.affected_path)
                logger.info(f"Restored database from {latest_backup}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to recover database: {e}")
        
        return False
    
    def generate_diagnostic_report(self) -> str:
        """
        Generate a diagnostic report for troubleshooting.
        
        Returns:
            str: Diagnostic report text.
        """
        from .environment import get_environment_manager
        from .runtime_config import get_runtime_config
        
        lines = [
            "=" * 60,
            "TRANSCRIPTIONIST DIAGNOSTIC REPORT",
            f"Generated: {datetime.now().isoformat()}",
            "=" * 60,
            "",
        ]
        
        # Environment info
        try:
            manager = get_environment_manager()
            info = manager.get_environment_info()
            
            lines.append("ENVIRONMENT:")
            for key, value in info.items():
                lines.append(f"  {key}: {value}")
            lines.append("")
        except Exception as e:
            lines.append(f"ENVIRONMENT: Error getting info - {e}")
            lines.append("")
        
        # Health check
        health = self.check_health()
        
        lines.append(f"HEALTH STATUS: {'HEALTHY' if health.is_healthy else 'ISSUES DETECTED'}")
        lines.append("")
        
        if health.issues:
            lines.append("DETECTED ISSUES:")
            for issue in health.issues:
                lines.append(f"  [{issue.severity.upper()}] {issue.corruption_type.value}")
                lines.append(f"    Description: {issue.description}")
                if issue.affected_path:
                    lines.append(f"    Affected: {issue.affected_path}")
                if issue.recoverable:
                    lines.append(f"    Recovery: {issue.recovery_action}")
                lines.append("")
        
        # Python info
        lines.append("PYTHON INFO:")
        lines.append(f"  Version: {sys.version}")
        lines.append(f"  Executable: {sys.executable}")
        lines.append(f"  Platform: {sys.platform}")
        lines.append("")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)


# Global recovery manager instance
_recovery_manager: Optional[RecoveryManager] = None


def get_recovery_manager() -> RecoveryManager:
    """
    Get the global recovery manager instance.
    
    Returns:
        RecoveryManager: The recovery manager.
    """
    global _recovery_manager
    if _recovery_manager is None:
        _recovery_manager = RecoveryManager()
    return _recovery_manager


def check_environment_health() -> EnvironmentHealth:
    """
    Check the health of the runtime environment.
    
    Returns:
        EnvironmentHealth: Health status.
    """
    return get_recovery_manager().check_health()


def get_recovery_instructions(corruption_type: CorruptionType) -> str:
    """
    Get recovery instructions for a corruption type.
    
    Args:
        corruption_type: The type of corruption.
        
    Returns:
        str: Recovery instructions.
    """
    return get_recovery_manager().get_recovery_instructions(corruption_type)


def attempt_automatic_recovery() -> RecoveryResult:
    """
    Attempt automatic recovery of detected issues.
    
    Returns:
        RecoveryResult: Result of recovery attempt.
    """
    return get_recovery_manager().attempt_recovery()


def generate_diagnostic_report() -> str:
    """
    Generate a diagnostic report.
    
    Returns:
        str: Diagnostic report text.
    """
    return get_recovery_manager().generate_diagnostic_report()
