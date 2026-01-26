"""
Environment Detection and Setup Module

Handles environment detection, validation, and setup for the embedded
Python runtime. Ensures proper configuration for portable deployment.

Validates: Requirements 12.2, 12.3, 12.5
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from .runtime_config import RuntimeConfig, RuntimePaths, get_runtime_config


class EnvironmentType(Enum):
    """Types of runtime environments."""
    
    SYSTEM = "system"  # Using system Python installation
    EMBEDDED = "embedded"  # Using embedded Python runtime
    FROZEN = "frozen"  # Running from frozen executable (PyInstaller, etc.)
    DEVELOPMENT = "development"  # Development environment


@dataclass
class DependencyStatus:
    """Status of a single dependency."""
    
    name: str
    available: bool
    version: Optional[str] = None
    error: Optional[str] = None


@dataclass
class EnvironmentStatus:
    """Overall status of the runtime environment."""
    
    environment_type: EnvironmentType
    is_valid: bool
    python_version_ok: bool
    paths_valid: bool
    dependencies_ok: bool
    dependency_statuses: list[DependencyStatus]
    errors: list[str]
    warnings: list[str]


class EnvironmentManager:
    """
    Manages environment detection, validation, and setup.
    
    This class is responsible for:
    - Detecting the current environment type
    - Validating the environment configuration
    - Setting up paths and environment variables
    - Checking dependency availability
    """
    
    def __init__(self, config: Optional[RuntimeConfig] = None):
        """
        Initialize the environment manager.
        
        Args:
            config: Runtime configuration. If None, will be auto-detected.
        """
        self._config = config or get_runtime_config()
        self._setup_complete = False
    
    @property
    def config(self) -> RuntimeConfig:
        """Get the runtime configuration."""
        return self._config
    
    @property
    def paths(self) -> RuntimePaths:
        """Get the runtime paths."""
        return self._config.paths
    
    def detect_environment_type(self) -> EnvironmentType:
        """
        Detect the current environment type.
        
        Returns:
            EnvironmentType: The detected environment type.
        """
        if self._config.is_frozen:
            return EnvironmentType.FROZEN
        elif self._config.is_embedded:
            return EnvironmentType.EMBEDDED
        elif self._is_development_environment():
            return EnvironmentType.DEVELOPMENT
        else:
            return EnvironmentType.SYSTEM
    
    def _is_development_environment(self) -> bool:
        """
        Check if running in a development environment.
        
        Returns:
            bool: True if in development environment.
        """
        # Check for common development indicators
        indicators = [
            # Virtual environment
            os.environ.get("VIRTUAL_ENV") is not None,
            # Poetry environment
            os.environ.get("POETRY_ACTIVE") == "1",
            # Conda environment
            os.environ.get("CONDA_DEFAULT_ENV") is not None,
            # Running from source with editable install
            self.paths.app_root.joinpath("pyproject.toml").exists(),
            # IDE debug mode
            os.environ.get("PYCHARM_HOSTED") == "1",
            os.environ.get("VSCODE_PID") is not None,
        ]
        return any(indicators)
    
    def validate_environment(self) -> EnvironmentStatus:
        """
        Validate the current environment.
        
        Returns:
            EnvironmentStatus: Validation results.
        """
        errors: list[str] = []
        warnings: list[str] = []
        
        # Check Python version
        python_ok, python_msg = self._config.validate_python_version()
        if not python_ok:
            errors.append(python_msg)
        
        # Check paths
        paths_ok = self._validate_paths(errors, warnings)
        
        # Check dependencies
        dep_statuses = self._check_dependencies()
        deps_ok = all(d.available for d in dep_statuses)
        
        for dep in dep_statuses:
            if not dep.available:
                errors.append(f"Missing dependency: {dep.name} - {dep.error}")
        
        # Determine overall validity
        is_valid = python_ok and paths_ok and deps_ok
        
        return EnvironmentStatus(
            environment_type=self.detect_environment_type(),
            is_valid=is_valid,
            python_version_ok=python_ok,
            paths_valid=paths_ok,
            dependencies_ok=deps_ok,
            dependency_statuses=dep_statuses,
            errors=errors,
            warnings=warnings,
        )
    
    def _validate_paths(self, errors: list[str], warnings: list[str]) -> bool:
        """
        Validate that required paths exist or can be created.
        
        Args:
            errors: List to append errors to.
            warnings: List to append warnings to.
            
        Returns:
            bool: True if paths are valid.
        """
        paths = self.paths
        valid = True
        
        # Check app root exists
        if not paths.app_root.exists():
            errors.append(f"Application root does not exist: {paths.app_root}")
            valid = False
        
        # Check/create data directories
        data_dirs = [
            paths.data_dir,
            paths.config_dir,
            paths.cache_dir,
            paths.logs_dir,
            paths.database_dir,
            paths.backups_dir,
        ]
        
        for dir_path in data_dirs:
            if not dir_path.exists():
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    errors.append(f"Cannot create directory {dir_path}: {e}")
                    valid = False
        
        # Check resources directory
        if not paths.resources_dir.exists():
            warnings.append(f"Resources directory not found: {paths.resources_dir}")
        
        # Check locale directory
        if not paths.locale_dir.exists():
            warnings.append(f"Locale directory not found: {paths.locale_dir}")
        
        return valid
    
    def _check_dependencies(self) -> list[DependencyStatus]:
        """
        Check availability of required dependencies.
        
        Returns:
            list: Status of each dependency.
        """
        statuses = []
        
        for dep_name in self._config.required_dependencies:
            status = self._check_single_dependency(dep_name)
            statuses.append(status)
        
        return statuses
    
    def _check_single_dependency(self, name: str) -> DependencyStatus:
        """
        Check if a single dependency is available.
        
        Args:
            name: Name of the dependency to check.
            
        Returns:
            DependencyStatus: Status of the dependency.
        """
        # GUI 相关依赖（GTK4/PyGObject）
        # gi 模块可以安全导入
        gui_deps = {"gi", "cairo"}
        
        try:
            spec = importlib.util.find_spec(name)
            if spec is None:
                return DependencyStatus(
                    name=name,
                    available=False,
                    error="Module not found"
                )
            
            # GTK4 依赖可以安全导入
            if name in gui_deps:
                # 尝试导入获取版本
                try:
                    module = importlib.import_module(name)
                    version = getattr(module, "__version__", None)
                    return DependencyStatus(
                        name=name,
                        available=True,
                        version=version
                    )
                except Exception:
                    return DependencyStatus(
                        name=name,
                        available=True,
                        version="(available)"
                    )
            
            # Try to get version for non-GUI deps
            version = None
            try:
                module = importlib.import_module(name)
                version = getattr(module, "__version__", None)
                if version is None:
                    version = getattr(module, "VERSION", None)
            except Exception:
                pass
            
            return DependencyStatus(
                name=name,
                available=True,
                version=version
            )
            
        except Exception as e:
            return DependencyStatus(
                name=name,
                available=False,
                error=str(e)
            )
    
    def setup_environment(self) -> bool:
        """
        Set up the runtime environment.
        
        This method:
        - Sets environment variables
        - Configures Python paths
        - Creates necessary directories
        
        Returns:
            bool: True if setup was successful.
        """
        if self._setup_complete:
            return True
        
        try:
            # Set environment variables
            for key, value in self._config.env_vars.items():
                os.environ[key] = value
            
            # Ensure data directories exist
            self._ensure_directories()
            
            # Configure Python path for embedded mode
            if self._config.is_embedded:
                self._configure_embedded_paths()
            
            self._setup_complete = True
            return True
            
        except Exception:
            return False
    
    def _ensure_directories(self) -> None:
        """Create all required directories."""
        paths = self.paths
        
        directories = [
            paths.data_dir,
            paths.config_dir,
            paths.cache_dir,
            paths.logs_dir,
            paths.database_dir,
            paths.backups_dir,
            paths.plugins_dir,
        ]
        
        for dir_path in directories:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    def _configure_embedded_paths(self) -> None:
        """Configure Python paths for embedded runtime."""
        paths = self.paths
        
        # Add GTK4 site-packages first (for PyGObject/gi module)
        if paths.gtk4_site_packages.exists():
            gtk4_site_str = str(paths.gtk4_site_packages)
            if gtk4_site_str not in sys.path:
                sys.path.insert(0, gtk4_site_str)
        
        # Add site-packages to sys.path if not already present
        site_packages_str = str(paths.site_packages)
        if site_packages_str not in sys.path:
            sys.path.insert(0, site_packages_str)
        
        # Add application root to sys.path
        app_root_str = str(paths.app_root)
        if app_root_str not in sys.path:
            sys.path.insert(0, app_root_str)
        
        # Add GTK4 bin to PATH for DLL loading
        if paths.gtk4_bin.exists():
            current_path = os.environ.get("PATH", "")
            gtk4_bin_str = str(paths.gtk4_bin)
            if gtk4_bin_str not in current_path:
                os.environ["PATH"] = f"{gtk4_bin_str};{current_path}"
    
    def get_environment_info(self) -> dict[str, str]:
        """
        Get detailed information about the current environment.
        
        Returns:
            dict: Environment information for diagnostics.
        """
        env_type = self.detect_environment_type()
        
        info = {
            "environment_type": env_type.value,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "python_executable": sys.executable,
            "platform": sys.platform,
            "app_root": str(self.paths.app_root),
            "data_dir": str(self.paths.data_dir),
            "config_dir": str(self.paths.config_dir),
            "is_embedded": str(self._config.is_embedded),
            "is_frozen": str(self._config.is_frozen),
        }
        
        # Add virtual environment info if applicable
        venv = os.environ.get("VIRTUAL_ENV")
        if venv:
            info["virtual_env"] = venv
        
        return info
    
    def is_portable_deployment(self) -> bool:
        """
        Check if the application is configured for portable deployment.
        
        A portable deployment means all data is stored within the
        application directory and can be moved without breaking.
        
        Returns:
            bool: True if portable deployment is configured.
        """
        # Check if data directory is within app root
        try:
            self.paths.data_dir.relative_to(self.paths.app_root)
            return True
        except ValueError:
            return False


# Global environment manager instance
_environment_manager: Optional[EnvironmentManager] = None


def get_environment_manager() -> EnvironmentManager:
    """
    Get the global environment manager instance.
    
    Returns:
        EnvironmentManager: The environment manager.
    """
    global _environment_manager
    if _environment_manager is None:
        _environment_manager = EnvironmentManager()
    return _environment_manager


def setup_environment() -> bool:
    """
    Set up the runtime environment.
    
    Returns:
        bool: True if setup was successful.
    """
    return get_environment_manager().setup_environment()


def validate_environment() -> EnvironmentStatus:
    """
    Validate the current environment.
    
    Returns:
        EnvironmentStatus: Validation results.
    """
    return get_environment_manager().validate_environment()


def get_environment_type() -> EnvironmentType:
    """
    Get the current environment type.
    
    Returns:
        EnvironmentType: The environment type.
    """
    return get_environment_manager().detect_environment_type()
