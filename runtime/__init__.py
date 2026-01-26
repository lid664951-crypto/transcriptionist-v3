"""
Embedded Runtime Module

Handles embedded Python runtime configuration:
- Runtime initialization and environment setup
- Dependency verification
- Recovery instructions for corrupted environments
- Portable deployment support

This module provides the foundation for running Transcriptionist as a
self-contained application with an embedded Python runtime.

Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6

Usage:
    # Bootstrap the runtime (call this first)
    from transcriptionist_v3.runtime import bootstrap
    bootstrap()
    
    # Check environment health
    from transcriptionist_v3.runtime import check_environment_health
    health = check_environment_health()
    
    # Get runtime configuration
    from transcriptionist_v3.runtime import get_runtime_config
    config = get_runtime_config()
"""

from .runtime_config import (
    RuntimeConfig,
    RuntimePaths,
    get_runtime_config,
    get_app_root,
    get_data_dir,
    get_config_dir,
    is_embedded_runtime,
)

from .environment import (
    EnvironmentType,
    EnvironmentStatus,
    DependencyStatus,
    EnvironmentManager,
    get_environment_manager,
    setup_environment,
    validate_environment,
    get_environment_type,
)

from .bootstrap import (
    BootstrapError,
    RuntimeBootstrap,
    get_bootstrap,
    bootstrap,
    is_bootstrapped,
    get_bootstrap_errors,
    get_bootstrap_warnings,
)

from .recovery import (
    CorruptionType,
    CorruptionIssue,
    RecoveryResult,
    EnvironmentHealth,
    RecoveryManager,
    get_recovery_manager,
    check_environment_health,
    get_recovery_instructions,
    attempt_automatic_recovery,
    generate_diagnostic_report,
)


__all__ = [
    # Runtime configuration
    "RuntimeConfig",
    "RuntimePaths",
    "get_runtime_config",
    "get_app_root",
    "get_data_dir",
    "get_config_dir",
    "is_embedded_runtime",
    
    # Environment management
    "EnvironmentType",
    "EnvironmentStatus",
    "DependencyStatus",
    "EnvironmentManager",
    "get_environment_manager",
    "setup_environment",
    "validate_environment",
    "get_environment_type",
    
    # Bootstrap
    "BootstrapError",
    "RuntimeBootstrap",
    "get_bootstrap",
    "bootstrap",
    "is_bootstrapped",
    "get_bootstrap_errors",
    "get_bootstrap_warnings",
    
    # Recovery
    "CorruptionType",
    "CorruptionIssue",
    "RecoveryResult",
    "EnvironmentHealth",
    "RecoveryManager",
    "get_recovery_manager",
    "check_environment_health",
    "get_recovery_instructions",
    "attempt_automatic_recovery",
    "generate_diagnostic_report",
]
