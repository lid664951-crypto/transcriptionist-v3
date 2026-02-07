"""
Runtime Configuration Module

Provides configuration for embedded Python paths and environment settings.
Handles detection of runtime mode (embedded vs system Python) and sets up
appropriate paths for portable deployment.

Validates: Requirements 12.1, 12.3, 12.4, 12.5
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RuntimePaths:
    """Container for all runtime-related paths."""
    
    # Base application directory
    app_root: Path
    
    # Python runtime paths
    python_home: Path
    python_executable: Path
    python_lib: Path
    site_packages: Path
    
    # GTK4 runtime paths
    gtk4_home: Path
    gtk4_bin: Path
    gtk4_lib: Path
    gtk4_typelib: Path
    gtk4_share: Path
    gtk4_site_packages: Path
    
    # Application data paths
    data_dir: Path
    config_dir: Path
    cache_dir: Path
    logs_dir: Path
    database_dir: Path
    backups_dir: Path
    
    # Resource paths
    resources_dir: Path
    locale_dir: Path
    plugins_dir: Path
    
    # Embedded runtime marker
    embedded_marker: Path


@dataclass
class RuntimeConfig:
    """
    Configuration for the embedded Python runtime environment.
    
    This class manages all paths and settings needed for the application
    to run in either embedded or system Python mode.
    """
    
    # Runtime mode
    is_embedded: bool = False
    is_frozen: bool = False  # True if running from PyInstaller/cx_Freeze
    
    # Version requirements
    min_python_version: tuple[int, int] = (3, 10)
    
    # Paths
    paths: Optional[RuntimePaths] = None
    
    # PyInstaller internal directory (if frozen)
    _internal_dir: Optional[Path] = None
    
    # Environment variables to set
    env_vars: dict[str, str] = field(default_factory=dict)
    
    # Required dependencies for embedded runtime
    # GTK4/Libadwaita 通过 PyGObject (gi) 和 PyCairo (cairo) 提供
    required_dependencies: list[str] = field(default_factory=lambda: [
        "gi",  # PyGObject for GTK4/Libadwaita
        "cairo",  # PyCairo for Cairo graphics
        "sqlalchemy",
        "alembic",
        "aiohttp",
        "mutagen",
        "soundfile",
        "numpy",
        "watchdog",
        "aiofiles",
        "pydantic",
        "pygame",  # Audio playback
    ])
    
    @classmethod
    def detect(cls) -> RuntimeConfig:
        """
        Detect the current runtime configuration.
        
        Returns:
            RuntimeConfig: Detected configuration for the current environment.
        """
        config = cls()
        
        # Detect if running from frozen executable (PyInstaller, cx_Freeze, etc.)
        config.is_frozen = getattr(sys, 'frozen', False)
        
        # Determine application root
        if config.is_frozen:
            # Running from frozen executable
            # Use os.path to handle encoding properly on Windows
            import os
            exe_path = os.path.abspath(sys.executable)
            app_root = Path(exe_path).parent
            
            # PyInstaller puts data files in _internal directory
            # Check if _internal exists (PyInstaller onedir mode)
            internal_dir = app_root / "_internal"
            if internal_dir.exists():
                # Use _internal as the base for resources
                config._internal_dir = internal_dir
        else:
            # Running from source - find the transcriptionist_v3 package root
            app_root = Path(__file__).parent.parent
            config._internal_dir = None
        
        # Check for embedded runtime marker
        embedded_marker = app_root / "runtime" / ".embedded"
        config.is_embedded = embedded_marker.exists() or config.is_frozen
        
        # Build paths
        config.paths = cls._build_paths(
            app_root, 
            config.is_embedded, 
            config.is_frozen,
            config._internal_dir
        )
        
        # Build environment variables
        config.env_vars = cls._build_env_vars(config.paths, config.is_embedded)
        
        return config
    
    @staticmethod
    def _build_paths(
        app_root: Path,
        is_embedded: bool,
        is_frozen: bool,
        internal_dir: Optional[Path] = None
    ) -> RuntimePaths:
        """
        Build all runtime paths based on the application root.
        
        Args:
            app_root: Root directory of the application.
            is_embedded: Whether running in embedded mode.
            is_frozen: Whether running from frozen executable.
            
        Returns:
            RuntimePaths: Container with all configured paths.
        """
        # Determine Python paths
        if is_frozen:
            # Frozen executable - Python is bundled
            # PyInstaller puts everything in _internal
            if internal_dir:
                python_home = internal_dir / "python"
                python_lib = internal_dir / "lib"
            else:
                python_home = app_root / "python"
                python_lib = app_root / "python" / "lib"
            python_executable = app_root / "python" / "python.exe" if sys.platform == "win32" else app_root / "python" / "bin" / "python3"
            site_packages = python_lib / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        elif is_embedded:
            # Embedded Python runtime (not frozen, but using bundled Python)
            python_home = app_root / "runtime" / "python"
            python_executable = python_home / "python.exe" if sys.platform == "win32" else python_home / "bin" / "python3"
            python_lib = python_home / "lib"
            site_packages = python_lib / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        else:
            # System Python
            python_home = Path(sys.prefix)
            python_executable = Path(sys.executable)
            python_lib = Path(sys.prefix) / "lib"
            site_packages = Path(next(p for p in sys.path if "site-packages" in p))
        
        # GTK4 runtime paths
        gtk4_home = app_root / "runtime" / "gtk4"
        gtk4_bin = gtk4_home / "bin"
        gtk4_lib = gtk4_home / "lib"
        gtk4_typelib = gtk4_lib / "girepository-1.0"
        gtk4_share = gtk4_home / "share"
        gtk4_site_packages = gtk4_lib / "site-packages"
        
        # Application data paths: 便携式安装用 app 目录；Windows 安装到 Program Files 时改为用户目录，避免只读导致 "attempt to write a readonly database"
        data_dir = app_root / "data"
        config_dir = app_root / "config"
        if is_frozen and sys.platform == "win32":
            app_root_str = str(app_root).lower()
            if "program files" in app_root_str or "program files (x86)" in app_root_str:
                appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
                user_data = appdata / "Transcriptionist"
                data_dir = user_data / "data"
                config_dir = user_data / "config"
        
        # Resource paths - handle PyInstaller _internal directory
        if internal_dir and internal_dir.exists():
            # PyInstaller puts resources in _internal
            resources_dir = internal_dir / "ui" / "resources"
            locale_dir = internal_dir / "locale"
            plugins_dir = internal_dir / "plugins"
        else:
            # Normal paths
            resources_dir = app_root / "resources"
            locale_dir = app_root / "locale"
            plugins_dir = app_root / "plugins"
        
        return RuntimePaths(
            app_root=app_root,
            python_home=python_home,
            python_executable=python_executable,
            python_lib=python_lib,
            site_packages=site_packages,
            gtk4_home=gtk4_home,
            gtk4_bin=gtk4_bin,
            gtk4_lib=gtk4_lib,
            gtk4_typelib=gtk4_typelib,
            gtk4_share=gtk4_share,
            gtk4_site_packages=gtk4_site_packages,
            data_dir=data_dir,
            config_dir=config_dir,
            cache_dir=data_dir / "cache",
            logs_dir=data_dir / "logs",
            database_dir=data_dir / "database",
            backups_dir=data_dir / "backups",
            resources_dir=resources_dir,
            locale_dir=locale_dir,
            plugins_dir=plugins_dir,
            embedded_marker=app_root / "runtime" / ".embedded",
        )
    
    @staticmethod
    def _build_env_vars(paths: RuntimePaths, is_embedded: bool) -> dict[str, str]:
        """
        Build environment variables for the runtime.
        
        Args:
            paths: Runtime paths configuration.
            is_embedded: Whether running in embedded mode.
            
        Returns:
            dict: Environment variables to set.
        """
        env_vars = {
            "TRANSCRIPTIONIST_ROOT": str(paths.app_root),
            "TRANSCRIPTIONIST_DATA": str(paths.data_dir),
            "TRANSCRIPTIONIST_CONFIG": str(paths.config_dir),
            "TRANSCRIPTIONIST_CACHE": str(paths.cache_dir),
            "TRANSCRIPTIONIST_LOGS": str(paths.logs_dir),
        }
        
        if is_embedded:
            env_vars.update({
                "PYTHONHOME": str(paths.python_home),
                "PYTHONPATH": str(paths.site_packages),
                # Disable user site-packages for isolation
                "PYTHONNOUSERSITE": "1",
                # Use UTF-8 encoding
                "PYTHONIOENCODING": "utf-8",
            })
            
            # GTK4 environment variables (if GTK4 runtime exists)
            if paths.gtk4_home.exists():
                env_vars.update({
                    # GObject Introspection typelib path
                    "GI_TYPELIB_PATH": str(paths.gtk4_typelib),
                    # XDG data directories for GTK resources
                    "XDG_DATA_DIRS": str(paths.gtk4_share),
                    # GSettings schema directory
                    "GSETTINGS_SCHEMA_DIR": str(paths.gtk4_share / "glib-2.0" / "schemas"),
                    # GDK Pixbuf loader cache
                    "GDK_PIXBUF_MODULE_FILE": str(paths.gtk4_lib / "gdk-pixbuf-2.0" / "2.10.0" / "loaders.cache"),
                    # Windows IME support
                    "GTK_IM_MODULE": "ime",
                })
        
        return env_vars
    
    def validate_python_version(self) -> tuple[bool, str]:
        """
        Validate that the Python version meets requirements.
        
        Returns:
            tuple: (is_valid, message)
        """
        current = (sys.version_info.major, sys.version_info.minor)
        required = self.min_python_version
        
        if current >= required:
            return True, f"Python {current[0]}.{current[1]} meets requirement >= {required[0]}.{required[1]}"
        else:
            return False, f"Python {current[0]}.{current[1]} does not meet requirement >= {required[0]}.{required[1]}"
    
    def get_runtime_info(self) -> dict[str, str]:
        """
        Get information about the current runtime for diagnostics.
        
        Returns:
            dict: Runtime information.
        """
        return {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "python_executable": str(self.paths.python_executable) if self.paths else sys.executable,
            "is_embedded": str(self.is_embedded),
            "is_frozen": str(self.is_frozen),
            "platform": sys.platform,
            "app_root": str(self.paths.app_root) if self.paths else "unknown",
        }


# Global runtime configuration instance
_runtime_config: Optional[RuntimeConfig] = None


def get_runtime_config() -> RuntimeConfig:
    """
    Get the global runtime configuration, detecting it if necessary.
    
    Returns:
        RuntimeConfig: The current runtime configuration.
    """
    global _runtime_config
    if _runtime_config is None:
        _runtime_config = RuntimeConfig.detect()
    return _runtime_config


def get_app_root() -> Path:
    """
    Get the application root directory.
    
    Returns:
        Path: Application root directory.
    """
    return get_runtime_config().paths.app_root


def get_data_dir() -> Path:
    """
    Get the data directory.
    
    Returns:
        Path: Data directory path.
    """
    return get_runtime_config().paths.data_dir


def get_config_dir() -> Path:
    """
    Get the configuration directory.
    
    Returns:
        Path: Configuration directory path.
    """
    return get_runtime_config().paths.config_dir


def is_embedded_runtime() -> bool:
    """
    Check if running in embedded runtime mode.
    
    Returns:
        bool: True if running in embedded mode.
    """
    return get_runtime_config().is_embedded
