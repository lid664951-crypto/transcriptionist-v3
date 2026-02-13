"""
Transcriptionist v3 - Application Entry Point

This module serves as the main entry point for the application.
It bootstraps the runtime environment and launches the PyQt6 application.

Usage:
    python -m transcriptionist_v3
    
Or via the installed command:
    transcriptionist
"""

from __future__ import annotations

import sys
import multiprocessing


def main() -> int:
    """
    Main entry point for Transcriptionist v3.
    
    Returns:
        int: Exit code (0 for success, non-zero for errors).
    """
    # CRITICAL: 多进程支持（PyInstaller 打包后必需）
    # 必须在程序最开始调用，否则多进程功能会失败
    multiprocessing.freeze_support()
    
    # Windows 11 任务栏图标修复：必须在导入 Qt 之前设置 AppUserModelID
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                'com.transcriptionist.ai-sound-manager.1.2.0'
            )
        except Exception:
            pass  # 非关键，失败不影响运行
    
    # Windows 下显式设置 spawn 模式（确保子进程能正确启动）
    if sys.platform == 'win32':
        try:
            multiprocessing.set_start_method('spawn', force=True)
        except RuntimeError:
            # 已经设置过了，忽略
            pass
    
    # Disable Numba debug logging before any imports
    import os
    os.environ['NUMBA_DISABLE_JIT'] = '0'  # Keep JIT enabled for performance
    os.environ['NUMBA_DEBUG'] = '0'  # Disable verbose debug output
    os.environ['NUMBA_DEBUGINFO'] = '0'  # Disable debug info
    
    # Step 1: Bootstrap the runtime environment
    try:
        from transcriptionist_v3.runtime.bootstrap import bootstrap, BootstrapError
        bootstrap()
    except BootstrapError as e:
        print(f"Failed to initialize runtime: {e}", file=sys.stderr)
        print("\nPlease run the recovery tool or reinstall the application.")
        return 1
    except Exception as e:
        print(f"Unexpected error during startup: {e}", file=sys.stderr)
        return 1
    
    # Step 2: Launch the PyQt6 application
    try:
        from transcriptionist_v3.ui.main_window import run_app
        return run_app()
    except ImportError as e:
        print(f"Failed to import UI components: {e}", file=sys.stderr)
        print("\nThis application requires PyQt6 and PyQt-Fluent-Widgets.")
        print("Please install them: pip install PyQt6 PyQt-Fluent-Widgets")
        return 1
    except Exception as e:
        print(f"Application error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def run_cli() -> int:
    """
    Run in CLI mode (no GUI).
    
    Returns:
        int: Exit code.
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        prog="transcriptionist",
        description="Professional Sound Effects Management Platform"
    )
    
    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="Show version information"
    )
    
    parser.add_argument(
        "--scan",
        metavar="PATH",
        help="Scan a directory for audio files"
    )
    
    parser.add_argument(
        "--search",
        metavar="QUERY",
        help="Search the library"
    )
    
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Run diagnostics and show environment info"
    )
    
    parser.add_argument(
        "--recover",
        action="store_true",
        help="Attempt to recover from environment issues"
    )
    
    args = parser.parse_args()
    
    if args.version:
        from transcriptionist_v3 import __version__
        print(f"Transcriptionist v{__version__}")
        return 0
    
    if args.diagnose:
        from transcriptionist_v3.runtime.recovery import generate_diagnostic_report
        print(generate_diagnostic_report())
        return 0
    
    if args.recover:
        from transcriptionist_v3.runtime.recovery import (
            check_environment_health,
            attempt_automatic_recovery
        )
        
        print("Checking environment health...")
        health = check_environment_health()
        
        if health.is_healthy:
            print("Environment is healthy. No recovery needed.")
            return 0
        
        print(f"Found {len(health.issues)} issue(s). Attempting recovery...")
        result = attempt_automatic_recovery()
        
        print(f"\n{result.message}")
        
        if result.actions_taken:
            print("\nActions taken:")
            for action in result.actions_taken:
                print(f"  - {action}")
        
        if result.remaining_issues:
            print("\nRemaining issues requiring manual intervention:")
            for issue in result.remaining_issues:
                print(f"  - [{issue.severity}] {issue.description}")
        
        return 0 if result.success else 1
    
    # Default: launch GUI
    return main()


if __name__ == "__main__":
    # PyInstaller 多进程：必须在入口最先调用
    multiprocessing.freeze_support()
    # 打包 exe 时，子进程由 multiprocessing 以 -c "from multiprocessing.spawn import main; main(...)" 启动。
    # 若不在此执行该命令并退出，子进程会再次跑主流程（GUI），导致 Pool 子进程无法正常干活。
    if getattr(sys, 'frozen', False) and len(sys.argv) >= 3 and sys.argv[1] == '-c':
        exec(compile(sys.argv[2], '<string>', 'exec'))
        sys.exit(0)
    sys.exit(run_cli())
