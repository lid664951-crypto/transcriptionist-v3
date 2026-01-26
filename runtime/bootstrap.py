"""
Bootstrap Module

Initializes the embedded Python runtime environment before the main
application starts. This module should be imported first to ensure
proper environment setup.

Validates: Requirements 12.1, 12.3, 12.5
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Configure basic logging before anything else
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class BootstrapError(Exception):
    """Exception raised during bootstrap process."""
    pass


class RuntimeBootstrap:
    """
    Handles the bootstrap process for the embedded Python runtime.
    
    This class is responsible for:
    - Early environment detection
    - Path configuration
    - Dependency verification
    - Runtime initialization
    """
    
    def __init__(self):
        """Initialize the bootstrap handler."""
        self._initialized = False
        self._errors: list[str] = []
        self._warnings: list[str] = []
    
    @property
    def is_initialized(self) -> bool:
        """Check if bootstrap has completed."""
        return self._initialized
    
    @property
    def errors(self) -> list[str]:
        """Get any errors that occurred during bootstrap."""
        return self._errors.copy()
    
    @property
    def warnings(self) -> list[str]:
        """Get any warnings from bootstrap."""
        return self._warnings.copy()
    
    def bootstrap(self, skip_validation: bool = False) -> bool:
        """
        Perform the bootstrap process.
        
        Args:
            skip_validation: If True, skip dependency validation.
            
        Returns:
            bool: True if bootstrap was successful.
            
        Raises:
            BootstrapError: If a critical error occurs during bootstrap.
        """
        if self._initialized:
            logger.debug("Bootstrap already completed")
            return True
        
        logger.info("Starting runtime bootstrap...")
        
        try:
            # Step 1: Detect and configure runtime
            self._configure_runtime()
            
            # Step 2: Set up environment
            self._setup_environment()
            
            # Step 3: Validate dependencies (optional)
            if not skip_validation:
                self._validate_dependencies()
            
            # Step 4: Initialize logging
            self._initialize_logging()
            
            self._initialized = True
            logger.info("Runtime bootstrap completed successfully")
            
            if self._warnings:
                for warning in self._warnings:
                    logger.warning(warning)
            
            return True
            
        except BootstrapError:
            raise
        except Exception as e:
            error_msg = f"Bootstrap failed: {e}"
            self._errors.append(error_msg)
            logger.error(error_msg)
            raise BootstrapError(error_msg) from e
    
    def _configure_runtime(self) -> None:
        """Configure the runtime paths and settings."""
        logger.debug("Configuring runtime...")
        
        # Import here to avoid circular imports
        from .runtime_config import get_runtime_config
        
        config = get_runtime_config()
        
        # Validate Python version
        version_ok, version_msg = config.validate_python_version()
        if not version_ok:
            raise BootstrapError(version_msg)
        
        logger.debug(f"Runtime mode: {'embedded' if config.is_embedded else 'system'}")
        logger.debug(f"App root: {config.paths.app_root}")
    
    def _setup_environment(self) -> None:
        """Set up the runtime environment."""
        logger.debug("Setting up environment...")
        
        from .environment import get_environment_manager
        
        manager = get_environment_manager()
        
        if not manager.setup_environment():
            raise BootstrapError("Failed to set up environment")
        
        # Check if portable deployment
        if manager.is_portable_deployment():
            logger.debug("Running in portable deployment mode")
    
    def _validate_dependencies(self) -> None:
        """Validate that required dependencies are available."""
        logger.debug("Validating dependencies...")
        
        from .environment import validate_environment
        
        status = validate_environment()
        
        # Collect errors and warnings
        self._errors.extend(status.errors)
        self._warnings.extend(status.warnings)
        
        # Check for missing critical dependencies
        # Note: GTK4/PyGObject is required for GUI mode
        # Core functionality can work without it
        critical_deps = {"sqlalchemy"}
        gui_deps = {"gi", "cairo"}  # PyGObject and PyCairo for GTK4
        optional_deps = {"numpy", "mutagen", "watchdog"}
        missing_critical = []
        missing_gui = []
        
        for dep_status in status.dependency_statuses:
            if not dep_status.available:
                if dep_status.name in critical_deps:
                    missing_critical.append(dep_status.name)
                elif dep_status.name in gui_deps:
                    missing_gui.append(dep_status.name)
        
        if missing_critical:
            raise BootstrapError(
                f"Missing critical dependencies: {', '.join(missing_critical)}. "
                "Please run the recovery tool or reinstall the application."
            )
        
        # Warn about missing GUI dependencies
        if missing_gui:
            self._warnings.append(
                f"GUI dependencies not available: {', '.join(missing_gui)}. "
                "GUI mode will not work. CLI mode is still available."
            )
        
        # Log non-critical missing dependencies as warnings
        for dep_status in status.dependency_statuses:
            if not dep_status.available and dep_status.name not in critical_deps and dep_status.name not in gui_deps:
                self._warnings.append(
                    f"Optional dependency '{dep_status.name}' not available: {dep_status.error}"
                )
    
    def _initialize_logging(self) -> None:
        """Initialize application logging."""
        logger.debug("Initializing logging...")
        
        from .runtime_config import get_runtime_config
        
        config = get_runtime_config()
        logs_dir = config.paths.logs_dir
        
        # Ensure logs directory exists
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Configure file handler for application logs
        log_file = logs_dir / "transcriptionist.log"
        
        # Create rotating file handler
        try:
            from logging.handlers import RotatingFileHandler
            
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
                encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            ))
            
            # Add to root logger
            logging.getLogger().addHandler(file_handler)
            
            logger.debug(f"Log file: {log_file}")
            
        except Exception as e:
            self._warnings.append(f"Could not set up file logging: {e}")


# Global bootstrap instance
_bootstrap: Optional[RuntimeBootstrap] = None


def get_bootstrap() -> RuntimeBootstrap:
    """
    Get the global bootstrap instance.
    
    Returns:
        RuntimeBootstrap: The bootstrap handler.
    """
    global _bootstrap
    if _bootstrap is None:
        _bootstrap = RuntimeBootstrap()
    return _bootstrap


def bootstrap(skip_validation: bool = False) -> bool:
    """
    Perform the runtime bootstrap.
    
    This function should be called at the very start of the application
    before any other imports or initialization.
    
    Args:
        skip_validation: If True, skip dependency validation.
        
    Returns:
        bool: True if bootstrap was successful.
        
    Raises:
        BootstrapError: If bootstrap fails.
    """
    return get_bootstrap().bootstrap(skip_validation=skip_validation)


def is_bootstrapped() -> bool:
    """
    Check if the runtime has been bootstrapped.
    
    Returns:
        bool: True if bootstrap has completed.
    """
    return get_bootstrap().is_initialized


def get_bootstrap_errors() -> list[str]:
    """
    Get any errors from the bootstrap process.
    
    Returns:
        list: Error messages.
    """
    return get_bootstrap().errors


def get_bootstrap_warnings() -> list[str]:
    """
    Get any warnings from the bootstrap process.
    
    Returns:
        list: Warning messages.
    """
    return get_bootstrap().warnings


# Auto-bootstrap when module is imported as main entry point
def _auto_bootstrap() -> None:
    """
    Automatically bootstrap if this module is the entry point.
    
    This allows the module to be used as:
        python -m transcriptionist_v3.runtime.bootstrap
    """
    if __name__ == "__main__":
        try:
            success = bootstrap()
            if success:
                print("Bootstrap completed successfully")
                
                # Print environment info
                from .environment import get_environment_manager
                manager = get_environment_manager()
                info = manager.get_environment_info()
                
                print("\nEnvironment Information:")
                for key, value in info.items():
                    print(f"  {key}: {value}")
                
                # Print any warnings
                warnings = get_bootstrap_warnings()
                if warnings:
                    print("\nWarnings:")
                    for warning in warnings:
                        print(f"  - {warning}")
            else:
                print("Bootstrap failed")
                sys.exit(1)
                
        except BootstrapError as e:
            print(f"Bootstrap error: {e}")
            sys.exit(1)


_auto_bootstrap()
